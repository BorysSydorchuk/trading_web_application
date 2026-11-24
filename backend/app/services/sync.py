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
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import takewhile

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import mt5_password_for, mt5_password_key
from app.config_files.rules import RulesConfig, SyncConfig
from app.config_files.symbols import SymbolsConfig, get_symbols_config
from app.domain.broker_time import (
    BrokerTimeRule,
    Conversion,
    choose_conversion,
    detect_offset,
    offset_hours,
)
from app.domain.sessions import is_trading_time
from app.domain.symbols import broker_candidates, canonical_symbol, resolve_broker_symbol
from app.domain.trade_builder import (
    DealEntry,
    DealType,
    SkippedPosition,
    deal_entry_from_mt5,
    deal_type_from_mt5,
)
from app.models import Account, SymbolSpec, SyncLog, Trade
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
from app.services.excursions import (
    ExcursionTarget,
    excursion_targets,
    fetch_series,
    store_excursions,
)
from app.services.excursions import Fetched as ExcursionFetched
from app.services.fx_sync import FxFetched, fetch_fx, write_fx
from app.services.starting_balance_suggestion import FirstDeposit, read_history_deposit
from app.services.trade_writer import (
    TradeBatch,
    assign_changed,
    write_trades,
)

logger = logging.getLogger(__name__)

INTERNAL_ERROR = "internal_error"
POSITIONS_SKIPPED = "positions_skipped"
MAX_ERROR_MESSAGE = 500

PasswordLookup = Callable[[int], SecretStr | None]
# M8-10b: receives (account_id, positions read by this sync, sync time UTC) after a
# successful sync, e.g. to write the open-positions snapshot. Its failure is only logged.
PositionsSink = Callable[[int, Sequence[RawPosition], datetime], None]
# Starting balance suggestion: receives (account_id, first deposit or None, sync time UTC)
# after a successful sync that read the full deal history. Its failure is only logged.
DepositSink = Callable[[int, FirstDeposit | None, datetime], None]


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
    # DB-open positions MT5 does not report whose close is not in the history (yet).
    unconfirmed_closes: frozenset[int] = frozenset()
    fx: FxFetched | None = None  # None: no FX step (no cross-currency data fetched)
    # M8-16: price series of trades whose MAE/MFE is due (read in the same connection).
    excursions: ExcursionFetched = field(default_factory=lambda: ExcursionFetched([], []))
    # Starting balance suggestion: True when the full history was read (then
    # ``first_deposit`` is the answer, None = no deposit in the history).
    deposit_checked: bool = False
    first_deposit: FirstDeposit | None = None


# A terminal the worker has just started answers history/positions calls with empty lists
# until it has downloaded them (owner bug 2026-11-20: 0 deals, 0 positions ~10 ms after
# connect, all there 3 s later). Retry only while the terminal looks cold (no window deal and
# no position at all) and a DB-open position's own history is empty: a real position always
# has its entry deal. A warm terminal without that history (purged, other server) is not
# waited for on every sync; the trade is only reported as unconfirmed.
HISTORY_READ_ATTEMPTS = 4
HISTORY_READ_PAUSE_S = 2.0


READY_PAUSE_S = 2.0
# After this many not-ready attempts in a row the account shows a red error and returns to its
# normal cadence (still retried), so a terminal that never loads cannot stay amber forever.
NOT_READY_MAX_ATTEMPTS = 10
_NOT_READY_CODES = frozenset(
    {Mt5ErrorCode.TERMINAL_LOADING.value, Mt5ErrorCode.TERMINAL_NOT_READY.value}
)


def _tickets(deals: Iterable[RawDeal]) -> frozenset[int]:
    return frozenset(d.ticket for d in deals)


def ensure_terminal_ready(
    source: Mt5Source,
    lo: int,
    hi: int,
    *,
    balance: Decimal,
    pause: Callable[[float], None] = monotonic_time.sleep,
) -> None:
    """Readiness gate before anything is read for the write phase (owner bug 2026-11-20).

    ``account_info`` was already verified by `connected`. Here: ``terminal_info().connected``;
    a non-empty window must read the same twice. An empty window is checked against the full
    history: a funded account always has a balance deal, so no deal at all with a non-zero
    balance is a terminal still loading (one more look after READY_PAUSE_S). A quiet window
    with older history, or a new account with zero balance, is ready and waits for nothing.
    Raises ``Mt5Error(TERMINAL_LOADING)``: no cursor moves and no snapshot is written.
    """
    if not source.terminal_connected():
        raise Mt5Error(Mt5ErrorCode.TERMINAL_LOADING, "terminal not connected to the trade server")
    first = _tickets(source.deals(lo, hi))
    if first:
        second = _tickets(source.deals(lo, hi))
        if first != second:
            raise Mt5Error(
                Mt5ErrorCode.TERMINAL_LOADING,
                f"deal history still loading ({len(first)} then {len(second)} deals)",
            )
        return
    if balance == 0 or source.deals(0, hi):
        return
    pause(READY_PAUSE_S)
    detail = "still loading" if source.deals(0, hi) else "empty"
    raise Mt5Error(
        Mt5ErrorCode.TERMINAL_LOADING,
        f"no deal history yet although the account has a balance (history {detail})",
    )


@dataclass(frozen=True)
class TradingRead:
    by_ticket: dict[int, RawDeal]  # window deals by ticket
    positions: list[RawPosition]
    pids: set[int]  # positions to build: window trade deals + open + DB-open missing ones
    own: dict[int, list[RawDeal]]  # every deal of each pid (history_deals_get(position=))
    unconfirmed: frozenset[int]  # DB-open, not reported by MT5, history not fully closed


def _fully_closed(deals: Iterable[RawDeal]) -> bool:
    """Exit volume covers the entry volume (a partial close alone is not a close)."""
    trade = [d for d in deals if _is_trade_deal(d)]
    opened = sum((d.volume for d in trade if _is_entry(d)), Decimal(0))
    closed = sum((d.volume for d in trade if not _is_entry(d)), Decimal(0))
    return opened > 0 and closed >= opened


def read_trading(
    source: Mt5Source,
    lo: int,
    hi: int,
    open_pids: Collection[int],
    *,
    pause: Callable[[float], None] = monotonic_time.sleep,
    attempts: int = HISTORY_READ_ATTEMPTS,
) -> TradingRead:
    """Window deals, open positions and the full history of every position to build.

    Reconciliation: a position the DB has open but ``positions_get`` does not report is
    always read by position id, so it is closed from its exit deals however old they are.
    If its history is still empty and the terminal looks cold (nothing at all in the window
    and no position: just started), everything is read again after
    ``HISTORY_READ_PAUSE_S``; after ``attempts`` it stays open in the DB and is reported in
    ``unconfirmed`` (retried next sync, never shown as a live position).
    """
    for attempt in range(1, attempts + 1):
        by_ticket = {d.ticket: d for d in source.deals(lo, hi)}
        positions = source.open_positions()
        live = {p.identifier for p in positions}
        missing = set(open_pids) - live
        pids = {d.position_id for d in by_ticket.values() if _is_trade_deal(d)} | live | missing
        own = {pid: source.deals_for_position(pid) for pid in sorted(pids)}
        not_loaded = {pid for pid in missing if not own[pid]}
        cold = not by_ticket and not positions
        if not (not_loaded and cold) or attempt == attempts:
            break
        logger.info(
            "MT5 history not loaded yet for %s open position(s); reading again (%s/%s)",
            len(not_loaded),
            attempt,
            attempts - 1,
        )
        pause(HISTORY_READ_PAUSE_S)
    unconfirmed = frozenset(pid for pid in missing if not _fully_closed(own[pid]))
    # A position without any deal cannot be built; keep it out of the build set.
    pids -= {pid for pid in missing if not own[pid]}
    return TradingRead(by_ticket, positions, pids, own, unconfirmed)


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
    excursions: Sequence[ExcursionTarget] = (),
    *,
    read_first_deposit: bool = False,
    open_pids: Collection[int] = (),
    pause: Callable[[float], None] = monotonic_time.sleep,
) -> Fetched:
    """Everything the write phase needs, read while connected. Raises `Mt5Error`.

    ``open_pids``: positions the DB still has open; each one MT5 no longer reports is read
    from its own deal history (no time window) so its close is never missed (see
    `read_trading`). A terminal that is not ready raises first (`ensure_terminal_ready`).

    ``excursions``: trades whose MAE/MFE price series is read last (never raises, M8-16).
    ``read_first_deposit``: also read the full deal history for the starting balance
    suggestion (never raises; a failure leaves ``deposit_checked`` False).
    """
    with connected(
        source, account.terminal_path or "", account.login, password, account.server
    ) as info:
        watch = watch_specs(source, symbols, account)
        specs = {s.name: s for s in watch}
        conversion, detected = _detect(source, watch, rules, now)

        lo, hi = server_epoch_range(window_from, now, conversion)
        ensure_terminal_ready(source, lo, hi, balance=info.balance, pause=pause)
        read = read_trading(source, lo, hi, open_pids, pause=pause)
        by_ticket, positions, pids = read.by_ticket, read.positions, read.pids

        orders: dict[int, RawOrder] = {}
        for pid in sorted(pids):
            own = read.own[pid]
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
        found = _read_excursions(source, excursions, conversion, specs, now)
        checked, deposit = (
            read_history_deposit(source, account.id, hi, conversion)
            if read_first_deposit
            else (False, None)
        )

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
        unconfirmed_closes=read.unconfirmed,
        fx=fx,
        excursions=found,
        deposit_checked=checked,
        first_deposit=deposit,
    )


def _read_excursions(
    source: Mt5Source,
    targets: Sequence[ExcursionTarget],
    conversion: Conversion,
    specs: Mapping[str, RawSymbolSpec],
    now: datetime,
) -> ExcursionFetched:
    """M8-16 read step: whatever happens here never fails the sync."""
    try:
        return fetch_series(source, targets, conversion, specs, now)
    except Exception:
        logger.exception("MAE/MFE price history not read")
        return ExcursionFetched([], [])


# --- write phase -----------------------------------------------------------------------


@dataclass
class Counters:
    deals_fetched: int = 0
    trades_created: int = 0
    trades_updated: int = 0
    open_positions: int = 0
    symbols_synced: int = 0
    skipped: list[SkippedPosition] = field(default_factory=list)


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
            assign_changed(row, values)
        count += 1
    return count


def write(
    session: Session,
    account: Account,
    fetched: Fetched,
    rules: RulesConfig,
    now: datetime,
    symbols: SymbolsConfig,
) -> Counters:
    """Persist one fetched snapshot (no commit). Raises on unexpected data.

    MT5 account values, symbol specs and FX here; the trades go through the
    platform-neutral `app.services.trade_writer.write_trades` (canonical names from
    ``symbols``).
    """
    counters = Counters(
        deals_fetched=len(fetched.deals),
        open_positions=len(fetched.positions),
    )
    digits = digits_by_symbol(fetched.specs.values())
    deals = to_deals(fetched.deals, fetched.conversion, digits)

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

    batch = TradeBatch(
        deals=deals,
        position_ids=fetched.position_ids,
        snapshots=position_snapshots(fetched.positions, digits),
        orders={ticket: order_stops(o, digits) for ticket, o in fetched.orders.items()},
        balance=fetched.info.balance,
        currency=fetched.info.currency,
        specs=fetched.specs,
        fx_loss=fx_loss,
    )
    counts = write_trades(session, account, batch, rules, symbols)
    counters.trades_created = counts.created
    counters.trades_updated = counts.updated
    counters.skipped = list(counts.skipped)
    return counters


# --- orchestration ---------------------------------------------------------------------


def open_position_ids(session: Session, account_id: int) -> set[int]:
    """Positions the DB still has open for this account (reconciled every sync)."""
    return set(
        session.scalars(
            select(Trade.position_id).where(
                Trade.account_id == account_id, Trade.close_time.is_(None)
            )
        )
    )


def history_window_start(
    session: Session,
    account_id: int,
    sync: SyncConfig,
    now: datetime,
    *,
    require_deals: bool = False,
) -> datetime:
    """First sync: ``initial_history_days`` back; later: last success - ``overlap_days``.

    ``require_deals`` (cTrader): only a success that read at least one deal and skipped no
    position moves the window, so an empty read never advances it and a skipped position is
    read again; the window then never starts more than ``initial_history_days`` back.
    """
    conditions = [SyncLog.account_id == account_id, SyncLog.ok.is_(True)]
    if require_deals:
        conditions.append(SyncLog.deals_fetched > 0)
        conditions.append(SyncLog.error_code.is_distinct_from(POSITIONS_SKIPPED))
    last_ok = session.scalar(select(func.max(SyncLog.started_at)).where(*conditions))
    first = now - timedelta(days=sync.initial_history_days)
    if last_ok is None:
        return first
    start = min(last_ok, now) - timedelta(days=sync.overlap_days)
    return max(start, first) if require_deals else start


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
    positions_sink: PositionsSink | None = None,
    deposit_sink: DepositSink | None = None,
    pause: Callable[[float], None] = monotonic_time.sleep,
) -> SyncLog:
    """One sync cycle for one account; never raises for MT5/data errors (see module doc).

    ``symbols`` defaults to config/symbols.yaml (a broken file fails this sync, recorded).
    ``positions_sink`` gets the open positions after a successful sync (M8-10b).
    ``deposit_sink``: when set, the full deal history is read and its first deposit goes
    there after a successful sync (starting balance suggestion).
    ``pause``: wait between history re-reads of a terminal not ready yet (tests: no-op).
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
        targets = excursion_targets(session, account_id, now_utc)
        open_pids = open_position_ids(session, account_id)
        session.commit()  # no transaction left idle through the MT5 reads and pauses
        args = (source, account, password, rules, now_utc, window_from, config)
        fetched = fetch(
            *args,
            excursions=targets,
            read_first_deposit=deposit_sink is not None,
            open_pids=open_pids,
            pause=pause,
        )
        counters = write(session, account, fetched, rules, now_utc, config)
        log.ok = True
        log.finished_at = finished()
        log.deals_fetched = counters.deals_fetched
        log.trades_created = counters.trades_created
        log.trades_updated = counters.trades_updated
        log.open_positions = counters.open_positions
        log.symbols_synced = counters.symbols_synced
        log.server_offset_hours = offset_hours(now_utc, fetched.conversion)
        if fetched.unconfirmed_closes:
            logger.warning(
                "Account %s: %s open trade(s) not reported by MT5 and no close in the history "
                "yet (positions %s); kept open, retried next sync",
                account_id,
                len(fetched.unconfirmed_closes),
                ", ".join(str(pid) for pid in sorted(fetched.unconfirmed_closes)),
            )
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
        _store_excursions(session, account_id, fetched, now_utc)
        _sink_positions(positions_sink, account_id, fetched, now_utc)
        _sink_deposit(deposit_sink, account_id, fetched, now_utc)
        return log
    except Exception as exc:
        session.rollback()
        if isinstance(exc, Mt5Error):
            code, message = exc.code.value, exc.message
            if exc.code is Mt5ErrorCode.TERMINAL_LOADING:
                if _not_ready_streak(session, account_id, log_id) >= NOT_READY_MAX_ATTEMPTS:
                    code = Mt5ErrorCode.TERMINAL_NOT_READY.value
                logger.warning("Account %s not synced: %s: %s", account_id, code, message)
            else:
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


def _not_ready_streak(session: Session, account_id: int, current_log_id: int) -> int:
    """Attempts right before this one that ended with the terminal not ready."""
    codes = session.scalars(
        select(SyncLog.error_code)
        .where(SyncLog.account_id == account_id, SyncLog.id != current_log_id)
        .order_by(SyncLog.started_at.desc(), SyncLog.id.desc())
        .limit(NOT_READY_MAX_ATTEMPTS)
    ).all()
    return sum(1 for _ in takewhile(lambda code: code in _NOT_READY_CODES, codes))


def _store_excursions(session: Session, account_id: int, fetched: Fetched, now: datetime) -> None:
    """M8-16, after the sync committed: a failure here is logged, never fails the sync."""
    if not fetched.excursions.series and not fetched.excursions.failed:
        return
    try:
        changed = store_excursions(session, fetched.excursions, now)
        session.commit()
        logger.info("Account %s: MAE/MFE stored for %s trades", account_id, changed)
    except Exception:
        session.rollback()
        logger.exception("Account %s: MAE/MFE not stored", account_id)


def _sink_positions(
    sink: PositionsSink | None, account_id: int, fetched: Fetched, now: datetime
) -> None:
    """M8-10b, after the sync committed: a failure here is logged, never fails the sync."""
    if sink is None:
        return
    try:
        sink(account_id, fetched.positions, now)
    except Exception:
        logger.exception("Account %s: open positions snapshot not written", account_id)


def _sink_deposit(
    sink: DepositSink | None, account_id: int, fetched: Fetched, now: datetime
) -> None:
    """After the sync committed: a failure here is logged, never fails the sync."""
    if sink is None or not fetched.deposit_checked:
        return
    try:
        sink(account_id, fetched.first_deposit, now)
    except Exception:
        logger.exception("Account %s: starting balance suggestion not written", account_id)


# Half the 60 s job interval: an account's start time drifts with the connect time of the
# accounts before it, and a few seconds of drift must not skip a whole cycle.
DUE_SLACK = timedelta(seconds=30)


LOADING_RETRY = timedelta(seconds=60)  # one worker cycle (sync_job.SYNC_JOB_INTERVAL_S)


def is_due(session: Session, account_id: int, rules: RulesConfig, now: datetime) -> bool:
    """True when the cadence interval passed since the account's last attempt.

    `DUE_SLACK` absorbs start-time drift between cycles (see above). An attempt that found
    the terminal still loading is retried on the next worker cycle (LOADING_RETRY), not only
    after the idle interval.
    """
    last = session.execute(
        select(SyncLog.started_at, SyncLog.error_code)
        .where(SyncLog.account_id == account_id)
        .order_by(SyncLog.started_at.desc())
        .limit(1)
    ).first()
    if last is None:
        return True
    started, code = last
    interval = sync_interval(rules.sync, rules.timezone, now)
    if code == Mt5ErrorCode.TERMINAL_LOADING.value:
        interval = min(interval, LOADING_RETRY)
    return now - started >= interval - DUE_SLACK


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
