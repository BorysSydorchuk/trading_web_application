"""Weekly / monthly digests (PRD 6.7; docs/api.md "Digests API", "Norm and deviation").

Generating a digest reads, with a fixed number of queries whatever the data size: the
non-archived accounts, the closed trades from the norm-window start to the period end (with
their rule violations), the first close per account, and the period's bias entries. The
result is a JSON snapshot in ``digests.metrics`` (``app.services.digest_snapshot``).
Periods and the suggestion clock are Brussels local time (DECISIONS 2026-10-31).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config_files import ConfigError, get_journal_fields, get_rules
from app.config_files.journal_fields import RELATION_FIELDS, JournalField
from app.domain import digest_metrics as dm
from app.domain.sessions import DEFAULT_TZ
from app.errors import ApiError, config_error
from app.models import Account, BiasEntry, BiasNote, Digest, Trade
from app.models.enums import AccountStatus, BiasKind, DigestKind
from app.schemas import digests as schemas
from app.services.digest_snapshot import Json, Scope, SnapshotInput, build_snapshot

logger = logging.getLogger(__name__)

SUGGESTION_HOUR = time(16)
FRIDAY = 4
# Journal field types that are not one value per trade (child tables, lists).
_NON_SCALAR_TYPES = frozenset({"multi_enum", "links"})
_DAILY_BIAS_KINDS = (BiasKind.PRE_LONDON.value, BiasKind.PRE_NY.value)


# --- time helpers ----------------------------------------------------------------------------


def _zone() -> ZoneInfo:
    return ZoneInfo(DEFAULT_TZ)


def _local_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=_zone()).astimezone(UTC)


def _period(kind: dm.PeriodKind, day: date) -> tuple[date, date]:
    start = dm.period_start(kind, day)
    return start, dm.period_end(kind, start)


# --- loading ---------------------------------------------------------------------------------


def _not_archived() -> ColumnElement[bool]:
    return Account.status != AccountStatus.ARCHIVED.value


def _closed() -> ColumnElement[bool]:
    return and_(Trade.close_time.is_not(None), Trade.net_pnl.is_not(None))


def _journal_specs() -> tuple[JournalField, ...]:
    """Analytics journal fields with one scalar value per trade, in file order."""
    return tuple(
        f
        for f in get_journal_fields().fields
        if f.analytics and f.type not in _NON_SCALAR_TYPES and f.key not in RELATION_FIELDS
    )


def _journal_value(value: Any) -> dm.JournalValue:
    if value is None or isinstance(value, str | int | bool):
        return value
    return str(value)  # e.g. a float or list typed into `extra` by hand


def _to_digest_trade(trade: Trade, specs: Sequence[JournalField]) -> dm.DigestTrade:
    extra = trade.extra or {}
    journal = {
        f.key: _journal_value(extra.get(f.key) if f.storage == "extra" else getattr(trade, f.key))
        for f in specs
    }
    close_time, net_pnl = trade.close_time, trade.net_pnl
    if close_time is None or net_pnl is None:  # excluded by _closed(); keeps the types honest
        raise ValueError(f"trade {trade.id} is not closed")
    return dm.DigestTrade(
        id=trade.id,
        account_id=trade.account_id,
        symbol=trade.symbol,
        close_time=close_time,
        net_pnl=net_pnl,
        r_multiple=trade.r_multiple,
        session=trade.session,
        hour=trade.hour,
        weekday=trade.weekday,
        bias_alignment=trade.bias_alignment_override or trade.bias_alignment,
        bias_alignment_weekly=trade.bias_alignment_weekly,
        bias_alignment_monthly=trade.bias_alignment_monthly,
        journal=journal,
        violations=tuple(v.rule_key for v in trade.rule_violations),
    )


def _load_trades(
    db: Session, since: date, until: date, specs: Sequence[JournalField]
) -> list[dm.DigestTrade]:
    """Closed trades of non-archived accounts with a Brussels close date in [since, until]."""
    rows = db.scalars(
        select(Trade)
        .join(Account, Account.id == Trade.account_id)
        .where(
            _not_archived(),
            _closed(),
            Trade.close_time >= _local_midnight_utc(since),
            Trade.close_time < _local_midnight_utc(until + timedelta(days=1)),
        )
        .options(selectinload(Trade.rule_violations))
        .order_by(Trade.close_time, Trade.id)
    ).all()
    return [_to_digest_trade(t, specs) for t in rows]


def _first_close_by_account(db: Session) -> dict[int, date]:
    rows = db.execute(
        select(Trade.account_id, func.min(Trade.close_time))
        .join(Account, Account.id == Trade.account_id)
        .where(_not_archived(), _closed())
        .group_by(Trade.account_id)
    )
    return {account_id: dm.brussels_date(first) for account_id, first in rows if first is not None}


def _bias_marks(db: Session, start: date, end: date) -> dict[str, list[bool | None]]:
    """Daily + weekly notes inside the period, the monthly note of the start's month."""
    in_period = BiasNote.period_date.between(start, end)
    rows = db.execute(
        select(BiasNote.kind, BiasEntry.was_correct)
        .join(BiasEntry, BiasEntry.bias_note_id == BiasNote.id)
        .where(
            or_(
                and_(BiasNote.kind.in_(_DAILY_BIAS_KINDS), in_period),
                and_(BiasNote.kind == BiasKind.WEEKLY.value, in_period),
                and_(
                    BiasNote.kind == BiasKind.MONTHLY.value,
                    BiasNote.period_date == start.replace(day=1),
                ),
            )
        )
        .order_by(BiasEntry.id)
    )
    marks: dict[str, list[bool | None]] = {}
    for kind, was_correct in rows:
        scope = "daily" if kind in _DAILY_BIAS_KINDS else kind
        marks.setdefault(scope, []).append(was_correct)
    return marks


# --- snapshot --------------------------------------------------------------------------------


def _currency(period: Sequence[dm.DigestTrade], accounts: Mapping[int, Account]) -> str | None:
    used = {accounts[t.account_id].currency for t in period}
    if len(used) > 1:
        raise ApiError(
            409,
            "mixed_currency",
            "The period has trades in more than one account currency",
            {"currencies": sorted(used)},
        )
    if used:
        return used.pop()
    every = {a.currency for a in accounts.values()}
    return every.pop() if len(every) == 1 else None


def _scope(
    period: Sequence[dm.DigestTrade],
    window: Sequence[dm.DigestTrade],
    first: date | None,
    start: date,
) -> Scope:
    days = 0 if first is None else dm.weekdays_between(first, start)
    return Scope(period=period, window=window, norm_available=days >= dm.NORM_MIN_TRADING_DAYS)


def _snapshot(db: Session, kind: dm.PeriodKind, start: date, end: date) -> Json:
    try:
        sigma = get_rules().digest.deviation_sigma
        specs = _journal_specs()
    except ConfigError as exc:
        raise config_error(exc) from exc
    accounts = {a.id: a for a in db.scalars(select(Account).where(_not_archived()))}
    trades = _load_trades(db, dm.norm_window_start(kind, start), end, specs)
    period = dm.trades_in_period(trades, kind, start)
    window = dm.norm_window_trades(trades, kind, start)
    currency = _currency(period, accounts)
    firsts = _first_close_by_account(db)
    period_accounts = sorted({t.account_id for t in period})
    by_account = {
        a: _scope(
            [t for t in period if t.account_id == a],
            [t for t in window if t.account_id == a],
            firsts.get(a),
            start,
        )
        for a in period_accounts
    }
    inp = SnapshotInput(
        kind=kind,
        start=start,
        currency=currency,
        sigma=sigma,
        sizes={a.id: a.reference_balance for a in accounts.values()},
        account_names={a.id: a.name for a in accounts.values()},
        combined=_scope(period, window, min(firsts.values(), default=None), start),
        by_account=by_account,
        journal_fields=[f.key for f in specs],
        bias_marks=_bias_marks(db, start, end),
    )
    return build_snapshot(inp)


# --- read models -----------------------------------------------------------------------------


def _is_reviewed(*texts: str | None) -> bool:
    return any(texts)


def _next_bias_note_id(db: Session, digest: Digest) -> int | None:
    next_start = digest.period_end + timedelta(days=1)
    kind = BiasKind.WEEKLY if digest.kind == DigestKind.WEEKLY.value else BiasKind.MONTHLY
    return db.scalar(
        select(BiasNote.id).where(BiasNote.kind == kind.value, BiasNote.period_date == next_start)
    )


def _out(db: Session, digest: Digest) -> schemas.DigestOut:
    return schemas.DigestOut(
        id=digest.id,
        kind=digest.kind,
        period_start=digest.period_start,
        period_end=digest.period_end,
        generated_at=digest.generated_at,
        what_worked=digest.what_worked,
        what_to_fix=digest.what_to_fix,
        focus_next=digest.focus_next,
        ai_summary=digest.ai_summary,
        reviewed=_is_reviewed(digest.what_worked, digest.what_to_fix, digest.focus_next),
        next_bias_note_id=_next_bias_note_id(db, digest),
        metrics=digest.metrics,
    )


def _find(db: Session, kind: str, start: date) -> Digest | None:
    return db.scalar(select(Digest).where(Digest.kind == kind, Digest.period_start == start))


def _get_or_404(db: Session, digest_id: int) -> Digest:
    digest = db.get(Digest, digest_id)
    if digest is None:
        raise ApiError(404, "not_found", f"Digest {digest_id} not found")
    return digest


# --- public API ------------------------------------------------------------------------------


def generate(
    db: Session, kind: dm.PeriodKind, day: date, now: datetime
) -> tuple[schemas.DigestOut, bool]:
    """Create or regenerate the digest of the period containing ``day``; True = created.

    Review texts and ai_summary of an existing digest are kept.
    """
    start, end = _period(kind, day)
    if start > dm.brussels_date(now):
        raise ApiError(422, "period_in_future", f"The {kind} period {start} has not started yet")
    metrics = _snapshot(db, kind, start, end)
    digest = _find(db, kind, start)
    created = digest is None
    if digest is None:
        digest = Digest(kind=kind, period_start=start, period_end=end)
        db.add(digest)
    digest.metrics = metrics
    digest.generated_at = now
    db.commit()
    logger.info("Digest %s %s %s", kind, start, "created" if created else "regenerated")
    return _out(db, digest), created


def get(db: Session, digest_id: int) -> schemas.DigestOut:
    return _out(db, _get_or_404(db, digest_id))


def get_by_period(db: Session, kind: dm.PeriodKind, day: date) -> schemas.DigestOut:
    start, _ = _period(kind, day)
    digest = _find(db, kind, start)
    if digest is None:
        raise ApiError(404, "not_found", f"No {kind} digest for the period starting {start}")
    return _out(db, digest)


def update_review(db: Session, digest_id: int, patch: schemas.DigestPatch) -> schemas.DigestOut:
    """Set the given review texts; ``""`` / null clears. Snapshot and ai_summary untouched."""
    digest = _get_or_404(db, digest_id)
    for name in schemas.REVIEW_FIELDS:
        if name in patch.model_fields_set:
            setattr(digest, name, getattr(patch, name) or None)
    db.commit()
    return _out(db, digest)


def _summary_value(block: Mapping[str, Any], name: str, default: Any) -> Any:
    entry = block.get(name)
    return entry.get("value", default) if isinstance(entry, Mapping) else default


def list_digests(db: Session, kind: dm.PeriodKind | None) -> schemas.DigestList:
    """Newest period first; the summary numbers come from the snapshot (one query)."""
    query = select(
        Digest.id,
        Digest.kind,
        Digest.period_start,
        Digest.period_end,
        Digest.generated_at,
        Digest.what_worked,
        Digest.what_to_fix,
        Digest.focus_next,
        Digest.metrics["combined"]["metrics"].label("summary"),
    ).order_by(Digest.period_start.desc(), Digest.id.desc())
    if kind is not None:
        query = query.where(Digest.kind == kind)
    items = []
    for row in db.execute(query):
        summary: Mapping[str, Any] = row.summary if isinstance(row.summary, Mapping) else {}
        items.append(
            schemas.DigestListItem(
                id=row.id,
                kind=row.kind,
                period_start=row.period_start,
                period_end=row.period_end,
                generated_at=row.generated_at,
                trades=_summary_value(summary, "trades", 0),
                net_pnl=_summary_value(summary, "net_pnl", "0.00"),
                net_pnl_pct=_summary_value(summary, "net_pnl_pct", None),
                total_r=_summary_value(summary, "total_r", "0.0000"),
                win_rate=_summary_value(summary, "win_rate", None),
                reviewed=_is_reviewed(row.what_worked, row.what_to_fix, row.focus_next),
            )
        )
    return schemas.DigestList(items=items)


# --- suggestion ------------------------------------------------------------------------------


def _last_weekday(month_start: date) -> date:
    day = dm.period_end("monthly", month_start)
    while day.weekday() >= dm.SATURDAY:
        day -= timedelta(days=1)
    return day


def _due(kind: dm.PeriodKind, start: date) -> datetime:
    """When the suggestion of the period starting ``start`` appears (aware Brussels time)."""
    day = start + timedelta(days=FRIDAY) if kind == "weekly" else _last_weekday(start)
    return datetime.combine(day, SUGGESTION_HOUR, tzinfo=_zone())


def _next_start(kind: dm.PeriodKind, start: date) -> date:
    return dm.period_end(kind, start) + timedelta(days=1)


def _oldest_unreviewed(
    kind: dm.PeriodKind, first: date, now: datetime, reviewed: set[tuple[str, date]]
) -> schemas.PeriodRef | None:
    start = dm.period_start(kind, first)
    while now >= _due(kind, start):
        if (kind, start) not in reviewed:
            return schemas.PeriodRef(period_start=start)
        start = _next_start(kind, start)
    return None


def suggestion(db: Session, now: datetime) -> schemas.DigestSuggestion:
    """Oldest due period of each kind (from the first closed trade on) without a review."""
    first_close = db.scalar(
        select(func.min(Trade.close_time))
        .join(Account, Account.id == Trade.account_id)
        .where(_not_archived(), _closed())
    )
    if first_close is None:
        return schemas.DigestSuggestion(weekly=None, monthly=None)
    has_review = or_(
        *(
            func.length(col) > 0
            for col in (Digest.what_worked, Digest.what_to_fix, Digest.focus_next)
        )
    )
    reviewed = {
        (k, s) for k, s in db.execute(select(Digest.kind, Digest.period_start).where(has_review))
    }
    first = dm.brussels_date(first_close)
    return schemas.DigestSuggestion(
        weekly=_oldest_unreviewed("weekly", first, now, reviewed),
        monthly=_oldest_unreviewed("monthly", first, now, reviewed),
    )
