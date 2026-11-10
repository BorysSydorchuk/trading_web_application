"""Recompute `trades.bias_alignment*` from the stored bias entries (PRD 6.6; docs/api.md M4).

Two entry points, both flush-only (the caller commits) and both one bias query per batch:

- `recompute_trades`: a given set of trades (the MT5 sync after its upsert).
- `recompute_for_scopes`: every trade a bias note change can affect: opened in the note's
  local day / week / month, symbol equal to one of the note's entry symbols (old and new
  state, so a kind / period / symbol change also fixes the trades it no longer covers).

`bias_alignment_override` is never touched; open and closed trades alike.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import ColumnElement, and_, false, or_, select, tuple_
from sqlalchemy.orm import Session

from app.config_files.bias import BiasConfig, get_bias_config
from app.config_files.loader import ConfigError
from app.config_files.rules import RulesConfig, get_rules
from app.domain.bias_alignment import (
    DEFAULT_PRE_NY_FROM,
    AlignmentSettings,
    BiasLookup,
    BiasPeriod,
    BiasRef,
    TradeBias,
    align_trade,
    lookup_key,
    period_utc_range,
    trade_periods,
)
from app.models import BiasEntry, BiasNote, Trade
from app.models.enums import BiasKind, TradingSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NoteScope:
    """What one state (before or after a change) of a bias note covers."""

    kind: BiasKind
    period_date: date
    symbols: frozenset[str]


def settings_from(bias: BiasConfig, rules: RulesConfig) -> AlignmentSettings:
    premarket = rules.session(TradingSession.PREMARKET.value)
    return AlignmentSettings(
        symbols=bias.symbol_names,
        tz=rules.timezone,
        pre_ny_from=premarket.start if premarket is not None else DEFAULT_PRE_NY_FROM,
    )


def alignment_settings() -> AlignmentSettings:
    """From bias.yaml + rules.yaml. Raises ConfigError when either is broken."""
    return settings_from(get_bias_config(), get_rules())


def scope_of(note: BiasNote) -> NoteScope:
    return NoteScope(
        kind=BiasKind(note.kind),
        period_date=note.period_date,
        symbols=frozenset(e.symbol for e in note.entries),
    )


def load_lookup(session: Session, periods: Iterable[BiasPeriod]) -> BiasLookup:
    """Entries of the notes of ``periods``, in one query."""
    keys = {(p.kind.value, p.period_date) for p in periods}
    if not keys:
        return {}
    rows = session.execute(
        select(
            BiasNote.kind,
            BiasNote.period_date,
            BiasEntry.symbol,
            BiasNote.id,
            BiasEntry.direction,
        )
        .join(BiasEntry, BiasEntry.bias_note_id == BiasNote.id)
        .where(tuple_(BiasNote.kind, BiasNote.period_date).in_(sorted(keys)))
    )
    return {
        lookup_key(BiasKind(kind), period_date, symbol): BiasRef(note_id, direction)
        for kind, period_date, symbol, note_id, direction in rows
    }


def trade_bias(trade: Trade, settings: AlignmentSettings, lookup: BiasLookup) -> TradeBias:
    return align_trade(trade.symbol, trade.direction, trade.open_time, settings, lookup)


def lookup_for(
    session: Session, trades: Sequence[Trade], settings: AlignmentSettings
) -> BiasLookup:
    periods = {p for t in trades for p in trade_periods(t.open_time, settings)}
    return load_lookup(session, periods)


def recompute_trades(session: Session, trades: Sequence[Trade], settings: AlignmentSettings) -> int:
    """Set the three auto alignments of ``trades``; returns how many trades changed."""
    session.flush()
    if not trades:
        return 0
    lookup = lookup_for(session, trades, settings)
    changed = 0
    for trade in trades:
        result = trade_bias(trade, settings, lookup)
        values = (result.daily.value, result.weekly.value, result.monthly.value)
        current = (trade.bias_alignment, trade.bias_alignment_weekly, trade.bias_alignment_monthly)
        if values != current:
            trade.bias_alignment, trade.bias_alignment_weekly, trade.bias_alignment_monthly = values
            changed += 1
    session.flush()
    return changed


def _scope_condition(scope: NoteScope, tz: str) -> ColumnElement[bool]:
    if not scope.symbols:
        return false()
    start, end = period_utc_range(scope.kind, scope.period_date, tz)
    # Trades carry canonical names (M5-08): exact equality, no prefix match.
    symbol = Trade.symbol.in_(sorted(scope.symbols))
    return and_(Trade.open_time >= start, Trade.open_time < end, symbol)


def recompute_for_scopes(
    session: Session, scopes: Iterable[NoteScope | None], settings: AlignmentSettings
) -> int:
    """Recompute every trade a note change can affect (None scopes = nothing before/after).

    Returns the number of trades whose alignment changed.
    """
    session.flush()
    conditions = [_scope_condition(s, settings.tz) for s in scopes if s is not None]
    if not conditions:
        return 0
    trades = session.scalars(select(Trade).where(or_(*conditions)).order_by(Trade.id)).all()
    changed = recompute_trades(session, trades, settings)
    logger.info("Bias alignment: %s of %s affected trades changed", changed, len(trades))
    return changed


def recompute_after_sync(session: Session, account_id: int, trades: Sequence[Trade]) -> None:
    """Sync hook: the synced trades plus every trade (of any account, also archived ones
    that are never synced again) not aligned yet: history from before M4, or a sync while a
    config was broken. Cheap once done (no NULLs left). A broken bias.yaml or rules.yaml
    never fails the sync: ERROR logged, the alignment catches up next sync."""
    try:
        settings = alignment_settings()
    except ConfigError as exc:
        logger.error(
            "Account %s: bias alignment not computed, config is invalid: %s", account_id, exc
        )
        return
    session.flush()
    pending = session.scalars(
        select(Trade).where(
            or_(
                Trade.bias_alignment.is_(None),
                Trade.bias_alignment_weekly.is_(None),
                Trade.bias_alignment_monthly.is_(None),
            ),
        )
    ).all()
    targets = {t.id: t for t in (*trades, *pending)}
    recompute_trades(session, list(targets.values()), settings)
