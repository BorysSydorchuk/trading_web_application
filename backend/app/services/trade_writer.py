"""Platform-neutral trade writer: built trades -> `trades` / `trade_exit_deals` rows.

Shared by the MT5 sync (`app.services.sync.write`) and the cTrader sync
(`app.services.ctrader_trades`). Each platform converts its records into the domain inputs
of `app.domain.trade_builder` (UTC `Deal`s, `PositionSnapshot`s, `OrderStops`) and passes
them as a `TradeBatch`; everything after that (build, upsert by account + position_id,
journal fields never touched, exit deals, metrics, exit reason prefill, rule recompute,
bias alignment) is one code path for every platform.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files.rules import RulesConfig
from app.config_files.symbols import SymbolsConfig
from app.domain import metrics
from app.domain.sessions import brussels_weekday_hour, classify
from app.domain.symbols import canonical_symbol
from app.domain.trade_builder import (
    BuiltTrade,
    Deal,
    OrderStops,
    PositionSnapshot,
    SkippedPosition,
    build_trades,
    next_status,
)
from app.models import Account, Trade, TradeExitDeal
from app.models.enums import InitialSlSource
from app.mt5.types import RawSymbolSpec
from app.services.bias_alignment import recompute_after_sync
from app.services.exit_reason import prefill_exit_reason
from app.services.fx_values import NO_VALUES, tick_values
from app.services.trade_rules import recompute_rules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeBatch:
    """What one platform read, as domain inputs.

    ``deals``: every deal read (UTC), also other positions' (``balance_at_open`` needs all
    balance-changing deals from the earliest open). ``position_ids``: the positions to build;
    each must have its complete deal history in ``deals``. ``specs`` are keyed by broker
    symbol; ``balance`` and ``currency`` are the account's at read time.
    """

    deals: Sequence[Deal]
    position_ids: Collection[int]
    snapshots: Mapping[int, PositionSnapshot]
    balance: Decimal
    currency: str | None
    orders: Mapping[int, OrderStops] = field(default_factory=dict)
    specs: Mapping[str, RawSymbolSpec] = field(default_factory=dict)
    fx_loss: Mapping[str, Decimal | None] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeCounts:
    created: int
    updated: int
    skipped: tuple[SkippedPosition, ...]


def assign_changed(obj: Any, values: dict[str, Any]) -> bool:
    """Set attributes that differ; True if anything changed."""
    changed = False
    for key, value in values.items():
        if getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True
    return changed


def _first_seen_sl(
    existing: dict[int, Trade], snapshots: Mapping[int, PositionSnapshot]
) -> dict[int, Decimal]:
    """SL first seen on the open position: persisted ones win over the current snapshot."""
    seen: dict[int, Decimal] = {
        pid: t.initial_sl
        for pid, t in existing.items()
        if t.initial_sl is not None and t.initial_sl_source == InitialSlSource.POSITION.value
    }
    for pid, snap in snapshots.items():
        if snap.sl is not None and snap.sl != 0:
            seen.setdefault(pid, snap.sl)
    return seen


def _initial_sl(built: BuiltTrade, current: Trade | None) -> tuple[Decimal | None, str | None]:
    """User-entered SL is never overwritten; a known SL is never cleared."""
    if current is not None and current.initial_sl_source == InitialSlSource.USER.value:
        return current.initial_sl, current.initial_sl_source
    if built.initial_sl is not None and built.initial_sl_source is not None:
        return built.initial_sl, built.initial_sl_source.value
    if current is not None:
        return current.initial_sl, current.initial_sl_source
    return None, None


def trade_values(
    built: BuiltTrade,
    current: Trade | None,
    *,
    deals: Sequence[Deal],
    balance: Decimal,
    spec: RawSymbolSpec | None,
    rules: RulesConfig,
    account_size: Decimal | None,
    symbol: str | None = None,
    account_currency: str | None = None,
    fx_loss_per_tick: Decimal | None = None,
) -> dict[str, Any]:
    """Auto (platform-derived and computed) columns of a trade. Journal fields are not included.

    ``symbol`` is the canonical name (default: the broker name); ``spec`` belongs to the
    broker symbol ``built.symbol``. A spec whose profit currency differs from
    ``account_currency`` (M5-09) uses only ``fx_loss_per_tick`` in the risk fallback, never
    its tick_value (None -> no fallback risk). Risk % and P&L % divide by
    ``account_size`` (accounts.reference_balance, M5-10; None -> both None);
    ``balance`` only feeds ``balance_at_open`` (information).
    """
    initial_sl, sl_source = _initial_sl(built, current)
    balance_open = metrics.balance_at_open(balance, built.open_time, deals)
    # Same rule as a user-entered SL (app.services.fx_values, M5-09).
    per_tick = (
        tick_values(spec.currency_profit, spec.tick_value, account_currency, fx_loss_per_tick)
        if spec is not None
        else NO_VALUES
    )
    risk = metrics.risk_amount(
        entry_price=built.entry_price,
        initial_sl=initial_sl,
        volume=built.volume,
        exit_price=built.exit_price,
        exit_volume=built.exit_volume,
        gross_pnl=built.gross_pnl,
        tick_size=spec.tick_size if spec is not None else None,
        tick_value=per_tick.tick_value,
        loss_per_tick=per_tick.loss_per_tick,
    )
    closed = built.is_closed
    weekday, hour = brussels_weekday_hour(built.open_time, rules.timezone)
    status = next_status(
        current.status if current is not None else None,
        is_closed=closed,
        has_initial_sl=initial_sl is not None,
        described=current is not None and current.described_at is not None,
    )
    return {
        "symbol": symbol if symbol is not None else built.symbol,
        "broker_symbol": built.symbol,
        "direction": built.direction.value,
        "open_time": built.open_time,
        "close_time": built.close_time,
        "duration_seconds": built.duration_seconds,
        "entry_price": built.entry_price,
        "exit_price": built.exit_price,
        "volume": built.volume,
        "initial_sl": initial_sl,
        "initial_sl_source": sl_source,
        "last_sl": built.last_sl,
        "tp": built.tp,
        "commission": built.commission,
        "swap": built.swap,
        "gross_pnl": built.gross_pnl,
        "net_pnl": built.net_pnl,
        # P&L % and R describe the final result: only for closed trades.
        "pnl_pct": metrics.pnl_pct(built.net_pnl, account_size) if closed else None,
        "balance_at_open": balance_open,
        "risk_amount": risk,
        "risk_pct": metrics.risk_pct(risk, account_size),
        "r_multiple": metrics.r_multiple(built.net_pnl, risk) if closed else None,
        "planned_rr": metrics.planned_rr(built.entry_price, initial_sl, built.tp),
        "session": classify(built.open_time, rules.sessions, rules.timezone),
        "weekday": weekday,
        "hour": hour,
        "status": status.value,
    }


def _upsert_exit_deals(
    session: Session, account_id: int, trades: dict[int, tuple[Trade, BuiltTrade]]
) -> set[int]:
    """Upsert exit deals by (account, ticket); returns position ids whose deals changed."""
    tickets = [e.ticket for _, built in trades.values() for e in built.exit_deals]
    existing = {
        d.ticket: d
        for d in session.scalars(
            select(TradeExitDeal).where(
                TradeExitDeal.account_id == account_id, TradeExitDeal.ticket.in_(tickets)
            )
        )
    }
    changed: set[int] = set()
    for pid, (trade, built) in trades.items():
        for e in built.exit_deals:
            values = {
                "trade_id": trade.id,
                "time": e.time,
                "price": e.price,
                "volume": e.volume,
                "profit": e.profit,
                "commission": e.commission,
                "swap": e.swap,
                "reason": e.reason,
                "reason_code": e.reason_code,
            }
            row = existing.get(e.ticket)
            if row is None:
                session.add(TradeExitDeal(account_id=account_id, ticket=e.ticket, **values))
                changed.add(pid)
            elif assign_changed(row, values):
                changed.add(pid)
    return changed


def _prefill_exit_reasons(
    session: Session,
    trades: dict[int, tuple[Trade, BuiltTrade]],
    specs: Mapping[str, RawSymbolSpec],
) -> set[int]:
    """M8-09: exit_reason from the final closing deal; returns position ids changed."""
    changed: set[int] = set()
    for pid, (trade, built) in trades.items():
        spec = specs.get(built.symbol)
        tick = spec.tick_size if spec is not None else None
        if prefill_exit_reason(session, trade, built.exit_deals, tick) is not None:
            changed.add(pid)
    return changed


def write_trades(
    session: Session,
    account: Account,
    batch: TradeBatch,
    rules: RulesConfig,
    symbols: SymbolsConfig,
) -> TradeCounts:
    """Build and upsert the batch's positions (no commit). Raises on unexpected data."""
    existing = {
        t.position_id: t
        for t in session.scalars(
            select(Trade).where(
                Trade.account_id == account.id, Trade.position_id.in_(batch.position_ids)
            )
        )
    }
    # The deals list may hold other positions' deals (balance window); build only the
    # touched ones, whose complete history was fetched and whose rows are in `existing`.
    own = [d for d in batch.deals if d.position_id in batch.position_ids]
    result = build_trades(
        own, batch.orders, batch.snapshots, _first_seen_sl(existing, batch.snapshots)
    )
    for skipped in result.skipped:
        logger.warning(
            "Account %s: position %s skipped: %s", account.id, skipped.position_id, skipped.reason
        )

    touched: dict[int, tuple[Trade, BuiltTrade]] = {}
    updated: set[int] = set()
    created = 0
    for built in result.trades:
        current = existing.get(built.position_id)
        values = trade_values(
            built,
            current,
            deals=batch.deals,
            balance=batch.balance,
            spec=batch.specs.get(built.symbol),
            rules=rules,
            symbol=canonical_symbol(symbols, built.symbol),
            account_currency=batch.currency,
            fx_loss_per_tick=batch.fx_loss.get(built.symbol),
            account_size=account.reference_balance,
        )
        if current is None:
            current = Trade(account_id=account.id, position_id=built.position_id, **values)
            session.add(current)
            created += 1
        elif assign_changed(current, values):
            updated.add(built.position_id)
        touched[built.position_id] = (current, built)
    session.flush()  # ids for new trades

    new = {pid for pid in touched if pid not in existing}
    updated |= _upsert_exit_deals(session, account.id, touched) - new
    updated |= _prefill_exit_reasons(session, touched, batch.specs) - new

    if result.trades:
        earliest = min(b.open_time for b in result.trades)
        recompute_rules(session, account.id, earliest, rules)
    recompute_after_sync(session, account.id, [trade for trade, _ in touched.values()])
    return TradeCounts(created=created, updated=len(updated), skipped=tuple(result.skipped))
