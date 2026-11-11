"""MT5 -> DB sync of one account (PRD 6.2, 6.3, 6.9; DECISIONS 2026-11-01).

`sync_account` runs one cycle for one account:

1. A `sync_log` row is committed with ``ok = NULL`` (the UI shows "running").
2. Read phase (inside ``connected``, terminal shut down afterwards): account info, server
   offset from a watch-symbol tick, deals of the history window, then *all* deals of every
   position touched in the window or still open, their opening orders, open positions and
   symbol specs (traded symbols + the broker symbol of every config/symbols.yaml name for
   the account's firm; a name the broker lacks is logged as a warning). Trades and specs
   are stored with their canonical name; broker names stay in `trades.broker_symbol` and
   `symbol_specs.symbol` (M5-08). Then the FX quotes and MT5 loss checks of cross-currency
   specs (`app.services.fx_sync`, M5-09; failures are warnings, never fail the cycle).
3. Write phase, one transaction: account balance/offset, symbol specs, FX rates and checks
   (their loss per tick feeds the risk of cross-currency trades), trades (upsert by
   account + position_id; journal fields never touched), exit deals (upsert by account +
   ticket), computed metrics, then re-entry flags and auto violations for the affected weeks,
   then the bias alignment of the synced (and never aligned) trades.
4. The sync_log row is completed in the same commit. On any error everything of step 3 is
   rolled back and the row is marked failed (own commit) with an `Mt5Error` code or
   ``internal_error`` (traceback in the log). Passwords are never logged.
"""

from __future__ import annotations

import logging
import time as monotonic_time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import mt5_password_for, mt5_password_key
from app.config_files.rules import RulesConfig, SyncConfig
from app.config_files.symbols import SymbolsConfig, get_symbols_config
from app.domain import metrics
from app.domain.broker_time import (
    BrokerTimeRule,
    Conversion,
    choose_conversion,
    detect_offset,
    offset_hours,
)
from app.domain.sessions import brussels_weekday_hour, classify, is_trading_time
from app.domain.symbols import broker_candidates, canonical_symbol, resolve_broker_symbol
from app.domain.trade_builder import (
    BuiltTrade,
    Deal,
    DealEntry,
    DealType,
    OrderStops,
    PositionSnapshot,
    SkippedPosition,
    build_trades,
    deal_entry_from_mt5,
    deal_type_from_mt5,
    next_status,
)
from app.models import Account, SymbolSpec, SyncLog, Trade, TradeExitDeal
from app.models.enums import InitialSlSource
from app.mt5.convert import (
    deal_time_utc,
    digits_by_symbol,
    order_stops,
    position_snapshots,
    server_epoch_range,
    to_deals,
)
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.source import Mt5Source, connected
from app.mt5.types import RawAccountInfo, RawDeal, RawOrder, RawPosition, RawSymbolSpec
from app.services.bias_alignment import recompute_after_sync
from app.services.fx_sync import FxFetched, fetch_fx, write_fx
from app.services.fx_values import NO_VALUES, tick_values
from app.services.trade_rules import recompute_rules

logger = logging.getLogger(__name__)

INTERNAL_ERROR = "internal_error"
POSITIONS_SKIPPED = "positions_skipped"
MAX_ERROR_MESSAGE = 500

PasswordLookup = Callable[[int], SecretStr | None]


# --- cadence ---------------------------------------------------------------------------


def sync_interval(sync: SyncConfig, tz: str, at: datetime) -> timedelta:
    """60 s on trading days within trading hours, else the idle interval (rules.yaml)."""
    trading = is_trading_time(
        at, sync.trading_days, sync.trading_hours.start, sync.trading_hours.end, tz
    )
    return timedelta(
        seconds=sync.interval_trading_seconds if trading else sync.interval_idle_seconds
    )


# --- read phase ------------------------------------------------------------------------


@dataclass
class Fetched:
    info: RawAccountInfo
    conversion: Conversion
    detected_offset: int | None
    window_from: datetime
    specs: dict[str, RawSymbolSpec]
    deals: list[RawDeal]  # unique by ticket: window + all deals of touched positions
    orders: dict[int, RawOrder]  # opening orders by ticket
    positions: list[RawPosition]
    position_ids: set[int] = field(default_factory=set)
    fx: FxFetched | None = None  # None: no FX step (no cross-currency data fetched)


def _is_trade_deal(raw: RawDeal) -> bool:
    return deal_type_from_mt5(raw.type) in (DealType.BUY, DealType.SELL) and raw.position_id > 0


def _is_entry(raw: RawDeal) -> bool:
    try:
        return deal_entry_from_mt5(raw.entry) is DealEntry.IN
    except ValueError:
        return False  # the builder reports the unknown code with the deal ticket


def _detect(
    source: Mt5Source, specs: Iterable[RawSymbolSpec], rules: RulesConfig, now: datetime
) -> tuple[Conversion, int | None]:
    """Offset from the newest watch-symbol tick, trusted only during trading time.

    Outside trading time the last ticks are stale (e.g. Friday close); a stale tick still
    sits on a whole hour for a few minutes every hour and would yield a wrong offset, so
    the configured rule is used unverified instead.
    """
    detected: int | None = None
    sync = rules.sync
    if is_trading_time(
        now, sync.trading_days, sync.trading_hours.start, sync.trading_hours.end, rules.timezone
    ):
        ticks = [source.server_tick_epoch(spec.name) for spec in specs]
        newest = max((t for t in ticks if t is not None), default=None)
        if newest is not None:
            detected = detect_offset(newest, now)
    choice = choose_conversion(detected, BrokerTimeRule(rules.broker_time), now)
    if choice.mismatch:
        logger.warning("Broker time: %s", choice.message)
    else:
        logger.debug("Broker time: %s", choice.message)
    if choice.conversion is None:  # pragma: no cover - rules always name a broker_time rule
        raise Mt5Error(Mt5ErrorCode.MT5_ERROR, f"cannot convert server time: {choice.message}")
    return choice.conversion, detected


def watch_specs(source: Mt5Source, symbols: SymbolsConfig, account: Account) -> list[RawSymbolSpec]:
    """The broker spec of every symbols.yaml name for this account's firm (connected).

    One prefix lookup for all candidates, then the pure resolver picks per name. A name the
    broker does not have is logged as a warning (no spec row; the calculator lists it as
    missing).
    """
    firm = account.firm
    candidates = {c for name in symbols.names for c in broker_candidates(symbols, name, firm)}
    by_name = {spec.name: spec for spec in source.symbols_matching(sorted(candidates))}
    found: dict[str, RawSymbolSpec] = {}
    for name in symbols.names:
        broker = resolve_broker_symbol(symbols, name, firm, by_name)
        if broker is None:
            logger.warning(
                "Account %s: symbol %s not found at the broker (tried %s); no spec synced",
                account.id,
                name,
                ", ".join(broker_candidates(symbols, name, firm)),
            )
            continue
        found.setdefault(broker, by_name[broker])
    return list(found.values())


def fetch(
    source: Mt5Source,
    account: Account,
    password: SecretStr,
    rules: RulesConfig,
    now: datetime,
    window_from: datetime,
    symbols: SymbolsConfig,
) -> Fetched:
    """Everything the write phase needs, read while connected. Raises `Mt5Error`."""
    with connected(
        source, account.terminal_path or "", account.login, password, account.server
    ) as info:
        watch = watch_specs(source, symbols, account)
        specs = {s.name: s for s in watch}
        conversion, detected = _detect(source, watch, rules, now)

        lo, hi = server_epoch_range(window_from, now, conversion)
        by_ticket = {d.ticket: d for d in source.deals(lo, hi)}
        positions = source.open_positions()
        pids = {d.position_id for d in by_ticket.values() if _is_trade_deal(d)}
        pids |= {p.identifier for p in positions}

        orders: dict[int, RawOrder] = {}
        for pid in sorted(pids):
            own = source.deals_for_position(pid)
            by_ticket.update((d.ticket, d) for d in own)
            entries = sorted((d for d in own if _is_entry(d)), key=lambda d: (d.time, d.ticket))
            if entries and entries[0].order not in orders:
                order = source.opening_order(entries[0].order)
                if order is not None:
                    orders[order.ticket] = order

        for symbol in sorted({d.symbol for d in by_ticket.values() if _is_trade_deal(d)}):
            if symbol not in specs:
                spec = source.symbol_spec(symbol)
                if spec is not None:
                    specs[spec.name] = spec

        # balance_at_open needs every balance-changing deal from the earliest open onward.
        opens = [deal_time_utc(d, conversion) for d in by_ticket.values() if _is_entry(d)]
        earliest = min(opens, default=window_from)
        if earliest < window_from:
            lo, hi = server_epoch_range(earliest, now, conversion)
            by_ticket.update((d.ticket, d) for d in source.deals(lo, hi))
        fx = fetch_fx(source, specs.values(), info.currency)

    return Fetched(
        info=info,
        conversion=conversion,
        detected_offset=detected,
        window_from=window_from,
        specs=specs,
        deals=sorted(by_ticket.values(), key=lambda d: (d.time, d.ticket)),
        orders=orders,
        positions=positions,
        position_ids=pids,
        fx=fx,
    )


# --- write phase -----------------------------------------------------------------------


@dataclass
class Counters:
    deals_fetched: int = 0
    trades_created: int = 0
    trades_updated: int = 0
    open_positions: int = 0
    symbols_synced: int = 0
    skipped: list[SkippedPosition] = field(default_factory=list)


def _assign(obj: Any, values: dict[str, Any]) -> bool:
    """Set attributes that differ; True if anything changed."""
    changed = False
    for key, value in values.items():
        if getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True
    return changed


def _upsert_specs(
    session: Session,
    account_id: int,
    specs: Iterable[RawSymbolSpec],
    now: datetime,
    canonical: Mapping[str, str] | None = None,
) -> int:
    """Upsert by (account, broker name); ``canonical`` maps broker -> canonical name
    (missing: the broker name itself)."""
    names = canonical or {}
    existing = {
        s.symbol: s
        for s in session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account_id))
    }
    count = 0
    for raw in specs:
        values = {
            "contract_size": raw.contract_size,
            "tick_size": raw.tick_size,
            "tick_value": raw.tick_value,
            "point": raw.point,
            "tick_value_loss": raw.tick_value_loss,
            "volume_min": raw.volume_min,
            "volume_step": raw.volume_step,
            "volume_max": raw.volume_max,
            "digits": raw.digits,
            "currency_profit": raw.currency_profit,
            "currency_margin": raw.currency_margin,
            "canonical_symbol": names.get(raw.name, raw.name),
            "synced_at": now,
        }
        row = existing.get(raw.name)
        if row is None:
            session.add(SymbolSpec(account_id=account_id, symbol=raw.name, **values))
        else:
            _assign(row, values)
        count += 1
    return count


def _first_seen_sl(
    existing: dict[int, Trade], snapshots: dict[int, PositionSnapshot]
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
    deals: list[Deal],
    balance: Decimal,
    spec: RawSymbolSpec | None,
    rules: RulesConfig,
    symbol: str | None = None,
    account_currency: str | None = None,
    fx_loss_per_tick: Decimal | None = None,
) -> dict[str, Any]:
    """Auto (MT5-derived and computed) columns of a trade. Journal fields are not included.

    ``symbol`` is the canonical name (default: the broker name); ``spec`` belongs to the
    broker symbol ``built.symbol``. A spec whose profit currency differs from
    ``account_currency`` (M5-09) uses only ``fx_loss_per_tick`` in the risk fallback, never
    its tick_value (None -> no fallback risk).
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
        "pnl_pct": metrics.pnl_pct(built.net_pnl, balance_open) if closed else None,
        "balance_at_open": balance_open,
        "risk_amount": risk,
        "risk_pct": metrics.risk_pct(risk, balance_open),
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
            }
            row = existing.get(e.ticket)
            if row is None:
                session.add(TradeExitDeal(account_id=account_id, ticket=e.ticket, **values))
                changed.add(pid)
            elif _assign(row, values):
                changed.add(pid)
    return changed


def write(
    session: Session,
    account: Account,
    fetched: Fetched,
    rules: RulesConfig,
    now: datetime,
    symbols: SymbolsConfig,
) -> Counters:
    """Persist one fetched snapshot (no commit). Raises on unexpected data.

    Trades and specs get their canonical name from ``symbols``.
    """
    counters = Counters(
        deals_fetched=len(fetched.deals),
        open_positions=len(fetched.positions),
    )
    digits = digits_by_symbol(fetched.specs.values())
    deals = to_deals(fetched.deals, fetched.conversion, digits)
    snapshots = position_snapshots(fetched.positions, digits)
    orders: dict[int, OrderStops] = {
        ticket: order_stops(order, digits) for ticket, order in fetched.orders.items()
    }

    existing = {
        t.position_id: t
        for t in session.scalars(
            select(Trade).where(
                Trade.account_id == account.id, Trade.position_id.in_(fetched.position_ids)
            )
        )
    }
    # The deals list may hold other positions' deals (balance window); build only the
    # touched ones, whose complete history was fetched and whose rows are in `existing`.
    own = [d for d in deals if d.position_id in fetched.position_ids]
    result = build_trades(own, orders, snapshots, _first_seen_sl(existing, snapshots))
    if result.skipped:
        counters.skipped = list(result.skipped)
        for skipped in result.skipped:
            logger.warning(
                "Account %s: position %s skipped: %s",
                account.id,
                skipped.position_id,
                skipped.reason,
            )

    account.balance = fetched.info.balance
    account.equity = fetched.info.equity
    account.balance_synced_at = now
    account.server_offset_hours = offset_hours(now, fetched.conversion)
    if fetched.detected_offset is not None:
        account.server_offset_detected_at = now
    canonical = {name: canonical_symbol(symbols, name) for name in fetched.specs}
    counters.symbols_synced = _upsert_specs(
        session, account.id, fetched.specs.values(), now, canonical
    )
    fx_loss: dict[str, Decimal | None] = {}
    if fetched.fx is not None:
        fx_loss = write_fx(session, account.id, fetched.fx, fetched.specs, fetched.conversion, now)

    touched: dict[int, tuple[Trade, BuiltTrade]] = {}
    updated: set[int] = set()
    for built in result.trades:
        current = existing.get(built.position_id)
        values = trade_values(
            built,
            current,
            deals=deals,
            balance=fetched.info.balance,
            spec=fetched.specs.get(built.symbol),
            rules=rules,
            symbol=canonical_symbol(symbols, built.symbol),
            account_currency=fetched.info.currency,
            fx_loss_per_tick=fx_loss.get(built.symbol),
        )
        if current is None:
            current = Trade(account_id=account.id, position_id=built.position_id, **values)
            session.add(current)
            counters.trades_created += 1
        elif _assign(current, values):
            updated.add(built.position_id)
        touched[built.position_id] = (current, built)
    session.flush()  # ids for new trades

    created = {pid for pid in touched if pid not in existing}
    updated |= _upsert_exit_deals(session, account.id, touched) - created
    counters.trades_updated = len(updated)

    if result.trades:
        earliest = min(b.open_time for b in result.trades)
        recompute_rules(session, account.id, earliest, rules)
    recompute_after_sync(session, account.id, [trade for trade, _ in touched.values()])
    return counters


# --- orchestration ---------------------------------------------------------------------


def history_window_start(
    session: Session, account_id: int, sync: SyncConfig, now: datetime
) -> datetime:
    """First sync: ``initial_history_days`` back; later: last success - ``overlap_days``."""
    last_ok = session.scalar(
        select(func.max(SyncLog.started_at)).where(
            SyncLog.account_id == account_id, SyncLog.ok.is_(True)
        )
    )
    if last_ok is None:
        return now - timedelta(days=sync.initial_history_days)
    return min(last_ok, now) - timedelta(days=sync.overlap_days)


def skipped_message(skipped: list[SkippedPosition]) -> str:
    details = "; ".join(f"{s.position_id}: {s.reason}" for s in skipped)
    return f"{len(skipped)} positions skipped: {details}"


def _short(text: str) -> str:
    return text if len(text) <= MAX_ERROR_MESSAGE else text[: MAX_ERROR_MESSAGE - 1] + "…"


def sync_account(
    session: Session,
    account: Account,
    source: Mt5Source,
    rules: RulesConfig,
    now_utc: datetime,
    *,
    password_for: PasswordLookup = mt5_password_for,
    symbols: SymbolsConfig | None = None,
) -> SyncLog:
    """One sync cycle for one account; never raises for MT5/data errors (see module doc).

    ``symbols`` defaults to config/symbols.yaml (a broken file fails this sync, recorded).
    Commits. Returns the completed sync_log row (``ok`` True or False).
    """
    started = monotonic_time.monotonic()
    account_id = account.id
    log = SyncLog(account_id=account_id, started_at=now_utc, ok=None)
    session.add(log)
    session.commit()
    log_id = log.id

    def finished() -> datetime:
        return now_utc + timedelta(seconds=monotonic_time.monotonic() - started)

    try:
        password = password_for(account.login)
        if password is None or not password.get_secret_value().strip():
            raise Mt5Error(
                Mt5ErrorCode.PASSWORD_MISSING,
                f"{mt5_password_key(account.login)} is not set in .env",
            )
        config = symbols if symbols is not None else get_symbols_config()
        window_from = history_window_start(session, account_id, rules.sync, now_utc)
        fetched = fetch(source, account, password, rules, now_utc, window_from, config)
        counters = write(session, account, fetched, rules, now_utc, config)
        log.ok = True
        log.finished_at = finished()
        log.deals_fetched = counters.deals_fetched
        log.trades_created = counters.trades_created
        log.trades_updated = counters.trades_updated
        log.open_positions = counters.open_positions
        log.symbols_synced = counters.symbols_synced
        log.server_offset_hours = offset_hours(now_utc, fetched.conversion)
        if counters.skipped:
            # A successful sync with a warning: shown as `warning` in the sync status.
            log.error_code = POSITIONS_SKIPPED
            log.error_message = _short(skipped_message(counters.skipped))
        session.commit()
        logger.info(
            "Account %s synced: %s deals, %s new, %s updated trades, %s open, %s symbols%s",
            account_id,
            counters.deals_fetched,
            counters.trades_created,
            counters.trades_updated,
            counters.open_positions,
            counters.symbols_synced,
            f", {len(counters.skipped)} positions skipped" if counters.skipped else "",
        )
        return log
    except Exception as exc:
        session.rollback()
        if isinstance(exc, Mt5Error):
            code, message = exc.code.value, exc.message
            logger.error("Account %s sync failed: %s: %s", account_id, code, message)
        else:
            code, message = INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"
            logger.exception("Account %s sync failed with an unexpected error", account_id)
        failed = session.get(SyncLog, log_id)
        if failed is None:  # pragma: no cover - the row was committed above
            raise
        failed.ok = False
        failed.finished_at = finished()
        failed.error_code = code
        failed.error_message = _short(message)
        session.commit()
        return failed


# Half the 60 s job interval: an account's start time drifts with the connect time of the
# accounts before it, and a few seconds of drift must not skip a whole cycle.
DUE_SLACK = timedelta(seconds=30)


def is_due(session: Session, account_id: int, rules: RulesConfig, now: datetime) -> bool:
    """True when the cadence interval passed since the account's last attempt.

    `DUE_SLACK` absorbs start-time drift between cycles (see above).
    """
    last = session.scalar(
        select(func.max(SyncLog.started_at)).where(SyncLog.account_id == account_id)
    )
    if last is None:
        return True
    interval = sync_interval(rules.sync, rules.timezone, now)
    return now - last >= interval - DUE_SLACK


def close_orphaned_runs(session: Session, now: datetime) -> int:
    """Mark ``ok = NULL`` rows left by a stopped worker as failed. Commits."""
    rows = session.scalars(select(SyncLog).where(SyncLog.ok.is_(None))).all()
    for row in rows:
        row.ok = False
        row.finished_at = now
        row.error_code = INTERNAL_ERROR
        row.error_message = "worker stopped during the sync"
    session.commit()
    return len(rows)
