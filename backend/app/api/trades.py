"""Trades read API, initial-SL entry, journal save and inbox counts (docs/api.md)."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.config_files import config_error
from app.config_files import ConfigError, JournalFieldsConfig, get_journal_fields
from app.db import get_db
from app.domain import metrics
from app.domain.sessions import DEFAULT_TZ
from app.domain.trade_builder import next_status
from app.errors import ApiError
from app.models import Account, RuleViolation, SymbolSpec, Trade
from app.models.enums import AccountStatus, Direction, InitialSlSource, TradeStatus
from app.schemas import trades as schemas
from app.schemas.audio import to_audio_out
from app.services.trade_journal import journal_view, save_journal
from app.services.trade_rules import recompute_rules_for_trade

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trades"])

INBOX_STATUSES = (TradeStatus.NEEDS_SL, TradeStatus.NEEDS_DESCRIPTION, TradeStatus.DRAFT)

_ROW_EXTRA = {"account_name", "violations"}
_DETAIL_EXTRA = _ROW_EXTRA | {
    "exit_deals",
    "rule_violations",
    "journal",
    "chart_links",
    "missing_required",
    "audio_notes",
}
ROW_COLUMNS = [f for f in schemas.TradeRow.model_fields if f not in _ROW_EXTRA]
DETAIL_COLUMNS = [f for f in schemas.TradeDetail.model_fields if f not in _DETAIL_EXTRA]


def _validation_error(field: str, message: str) -> ApiError:
    return ApiError(
        422, "validation_error", "Request validation failed", {"fields": {field: message}}
    )


def parse_bound(value: str | None, field: str, *, end: bool) -> tuple[datetime, bool] | None:
    """`from`/`to` → (UTC instant, inclusive).

    A date is a Brussels calendar day: `from` starts at its local midnight, `to` covers the
    whole day (exclusive next local midnight). A datetime without offset is taken as UTC.
    """
    if value is None or value.strip() == "":
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            day = date.fromisoformat(text)
            if end:
                day += timedelta(days=1)
            local = datetime.combine(day, time(0), tzinfo=ZoneInfo(DEFAULT_TZ))
            return local.astimezone(UTC), not end
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise _validation_error(field, "must be an ISO date or datetime") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC), True


def _filters(
    account_ids: Sequence[int],
    symbols: Sequence[str],
    statuses: Sequence[TradeStatus],
    date_from: str | None,
    date_to: str | None,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if account_ids:
        conditions.append(Trade.account_id.in_(account_ids))
    if symbols:
        conditions.append(Trade.symbol.in_(symbols))
    if statuses:
        conditions.append(Trade.status.in_([s.value for s in statuses]))
    # Closed trades are filtered on close_time, open positions on open_time.
    when = func.coalesce(Trade.close_time, Trade.open_time)
    lower = parse_bound(date_from, "from", end=False)
    if lower is not None:
        conditions.append(when >= lower[0])
    upper = parse_bound(date_to, "to", end=True)
    if upper is not None:
        conditions.append(when <= upper[0] if upper[1] else when < upper[0])
    return conditions


def _violation_keys(db: Session, trade_ids: Sequence[int]) -> dict[int, list[str]]:
    keys: dict[int, list[str]] = defaultdict(list)
    if trade_ids:
        rows = db.execute(
            select(RuleViolation.trade_id, RuleViolation.rule_key)
            .where(RuleViolation.trade_id.in_(trade_ids))
            .order_by(RuleViolation.trade_id, RuleViolation.rule_key)
        )
        for trade_id, rule_key in rows:
            keys[trade_id].append(rule_key)
    return keys


def to_row(trade: Trade, account_name: str, violations: list[str]) -> schemas.TradeRow:
    data: dict[str, Any] = {f: getattr(trade, f) for f in ROW_COLUMNS}
    return schemas.TradeRow.model_validate(
        data | {"account_name": account_name, "violations": violations}
    )


def to_detail(trade: Trade, account_name: str, config: JournalFieldsConfig) -> schemas.TradeDetail:
    data: dict[str, Any] = {f: getattr(trade, f) for f in DETAIL_COLUMNS}
    violations = sorted(trade.rule_violations, key=lambda v: v.rule_key)
    view = journal_view(trade, config)
    return schemas.TradeDetail.model_validate(
        data
        | {
            "account_name": account_name,
            "journal": view.journal,
            "chart_links": view.chart_links,
            "missing_required": view.missing_required,
            "audio_notes": [
                to_audio_out(n)
                for n in sorted(trade.audio_notes, key=lambda n: (n.created_at, n.id))
            ],
            "violations": [v.rule_key for v in violations],
            "rule_violations": [
                {"rule_key": v.rule_key, "source": v.source, "details": v.details}
                for v in violations
            ],
            "exit_deals": [
                {
                    "ticket": d.ticket,
                    "time": d.time,
                    "price": d.price,
                    "volume": d.volume,
                    "profit": d.profit,
                    "commission": d.commission,
                    "swap": d.swap,
                    "reason": d.reason,
                }
                for d in trade.exit_deals
            ],
        }
    )


def journal_config() -> JournalFieldsConfig:
    try:
        return get_journal_fields()
    except ConfigError as exc:
        raise config_error(exc) from None


def _load_detail(db: Session, trade_id: int) -> tuple[Trade, str]:
    row = db.execute(
        select(Trade, Account.name)
        .join(Account, Account.id == Trade.account_id)
        .where(Trade.id == trade_id)
        .options(
            selectinload(Trade.exit_deals),
            selectinload(Trade.rule_violations),
            selectinload(Trade.chart_links),
            selectinload(Trade.audio_notes),
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Trade not found", {"id": trade_id})
    return row[0], row[1]


@router.get("/trades", response_model=schemas.TradeList)
def list_trades(
    account_id: list[int] = Query(default_factory=list),
    symbol: list[str] = Query(default_factory=list),
    status: list[TradeStatus] = Query(default_factory=list),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    sort: schemas.TradeSort = Query(default="close_time"),
    order: schemas.SortOrder = Query(default="desc"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.TradeList:
    conditions = _filters(account_id, symbol, status, date_from, date_to)
    total = db.scalar(select(func.count()).select_from(Trade).where(*conditions)) or 0

    column = getattr(Trade, sort)
    direction = column.asc() if order == "asc" else column.desc()
    tiebreak = Trade.id.asc() if order == "asc" else Trade.id.desc()
    query = (
        select(Trade, Account.name)
        .join(Account, Account.id == Trade.account_id)
        .where(*conditions)
        .order_by(direction.nulls_last(), tiebreak)
        .limit(limit)
        .offset(offset)
    )
    page = db.execute(query).all()
    violations = _violation_keys(db, [t.id for t, _ in page])
    return schemas.TradeList(
        items=[to_row(t, name, violations.get(t.id, [])) for t, name in page], total=total
    )


@router.get("/trades/symbols", response_model=schemas.SymbolList)
def trade_symbols(db: Session = Depends(get_db)) -> schemas.SymbolList:
    symbols = db.scalars(select(Trade.symbol).distinct().order_by(Trade.symbol))
    return schemas.SymbolList(items=list(symbols))


@router.get("/trades/{trade_id}", response_model=schemas.TradeDetail)
def get_trade(trade_id: int, db: Session = Depends(get_db)) -> schemas.TradeDetail:
    config = journal_config()
    return to_detail(*_load_detail(db, trade_id), config)


def _check_stop_side(trade: Trade, sl: Decimal) -> None:
    if sl == trade.entry_price:
        raise _validation_error("initial_sl", "must differ from the entry price")
    if trade.direction == Direction.BUY.value and sl > trade.entry_price:
        raise _validation_error("initial_sl", "must be below the entry price for a buy")
    if trade.direction == Direction.SELL.value and sl < trade.entry_price:
        raise _validation_error("initial_sl", "must be above the entry price for a sell")


def apply_initial_sl(db: Session, trade: Trade, sl: Decimal) -> None:
    """Set a user-entered initial SL; recompute risk, risk %, R, planned RR and violations."""
    spec = db.scalar(
        select(SymbolSpec).where(
            SymbolSpec.account_id == trade.account_id, SymbolSpec.symbol == trade.symbol
        )
    )
    exit_volume = sum((d.volume for d in trade.exit_deals), Decimal(0)) or trade.volume
    risk = metrics.risk_amount(
        entry_price=trade.entry_price,
        initial_sl=sl,
        volume=trade.volume,
        exit_price=trade.exit_price,
        exit_volume=exit_volume,
        gross_pnl=trade.gross_pnl,
        tick_size=spec.tick_size if spec is not None else None,
        tick_value=spec.tick_value if spec is not None else None,
    )
    trade.initial_sl = sl
    trade.initial_sl_source = InitialSlSource.USER.value
    trade.risk_amount = risk
    trade.risk_pct = metrics.risk_pct(risk, trade.balance_at_open)
    trade.r_multiple = metrics.r_multiple(trade.net_pnl, risk)
    trade.planned_rr = metrics.planned_rr(trade.entry_price, sl, trade.tp)
    trade.status = next_status(trade.status, is_closed=True, has_initial_sl=True).value
    # Same recompute as the MT5 sync (risk %, planned RR and breakeven depend on the SL).
    recompute_rules_for_trade(db, trade, "initial SL")


@router.patch("/trades/{trade_id}", response_model=schemas.TradeDetail)
def update_trade(
    trade_id: int, body: schemas.TradePatch, db: Session = Depends(get_db)
) -> schemas.TradeDetail:
    config = journal_config()
    trade, account_name = _load_detail(db, trade_id)
    if trade.status == TradeStatus.OPEN.value or trade.close_time is None:
        raise ApiError(
            409, "trade_open", "Initial SL can only be set on a closed trade", {"id": trade_id}
        )
    _check_stop_side(trade, body.initial_sl)
    old_status = trade.status
    apply_initial_sl(db, trade, body.initial_sl)
    db.commit()
    logger.info(
        "Trade %s: user initial SL set, status %s -> %s", trade.id, old_status, trade.status
    )
    db.expire(trade)  # reload as stored (NUMERIC scale), not the in-memory input values
    trade, account_name = _load_detail(db, trade_id)
    return to_detail(trade, account_name, config)


@router.put("/trades/{trade_id}/journal", response_model=schemas.TradeDetail)
def put_journal(
    trade_id: int, body: schemas.JournalInput, db: Session = Depends(get_db)
) -> schemas.TradeDetail:
    """Save the journal (docs/api.md M2 "Journal save"): draft or complete."""
    config = journal_config()
    trade, _ = _load_detail(db, trade_id)
    save_journal(db, trade, body, config, now=datetime.now(UTC))
    db.commit()
    db.expire_all()
    return to_detail(*_load_detail(db, trade_id), config)


@router.get("/inbox/counts", response_model=schemas.InboxCounts)
def inbox_counts(db: Session = Depends(get_db)) -> schemas.InboxCounts:
    """Trades waiting for the user, on accounts that are not archived."""
    rows = db.execute(
        select(Trade.status, func.count())
        .join(Account, Account.id == Trade.account_id)
        .where(
            Account.status != AccountStatus.ARCHIVED.value,
            Trade.status.in_([s.value for s in INBOX_STATUSES]),
        )
        .group_by(Trade.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in rows}
    return schemas.InboxCounts(
        needs_sl=counts.get(TradeStatus.NEEDS_SL.value, 0),
        needs_description=counts.get(TradeStatus.NEEDS_DESCRIPTION.value, 0),
        draft=counts.get(TradeStatus.DRAFT.value, 0),
    )
