"""The `ctrader_balance` worker job: balance, equity and trades of active cTrader accounts.

Separate from the MT5 job and its lock, on the same cadence rule (`is_due`: 60 s in trading
hours, the idle interval otherwise). Every attempt records one `sync_log` row, so the status
bar works as for MT5. A failed read never overwrites a good value.

Equity = balance + the positions' net unrealized P&L (`app.ctrader.money.equity_from`). When
the balance was read but the equity was not, the stored balance/equity pair stays as it is:
Home computes the floating P&L as equity - balance, so a new balance next to an old equity
would show a false number. Only an account with no stored equity gets the balance alone.

Trades (phase b): in the same connection the open positions (reconcile) and the deal history
since the account's window (`history_window_start(require_deals=True)`, extended back to every
DB-open trade and open position) are read and written through the shared trade writer
(`app.services.ctrader_trades`). The row is ``ok`` only when balance, equity and trades all
worked; a read without any deal never moves the window. The trades are written in a savepoint:
a failed history keeps the balance. After the commit the open positions go to the Home
snapshot (`open_positions.json`), as the MT5 sync does.

Specs and conversion rates (phase c): the same connection reads the symbol specs (first cycle,
then at most hourly per account by ``symbol_specs.synced_at``, sooner only for a traded
symbol without a stored spec) and the conversion quotes (`app.ctrader.market`). They are
stored in their own savepoint before the trades (`ctrader_specs.store_market`), so the trade
risk of the same cycle uses them; a failure there is a WARNING and never changes the row's
``ok`` or the balance.

MAE/MFE (phase c, c5): the targets are chosen before the read with the MT5 rule
(`excursion_targets`), read in the same connection after the market step
(`app.ctrader.excursions`, own time limit) and stored after the trades with the MT5
`store_excursions`, in their own savepoint. A failure there is a WARNING and never changes
``ok``, the balance or the trades.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.config_files import ConfigError, get_rules
from app.config_files.rules import RulesConfig
from app.config_files.symbols import SymbolsConfig, get_symbols_config
from app.ctrader.connection import Connector, Sleep, open_websocket
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.excursions import ExcursionRequest
from app.ctrader.history import HistoryRequest, TradingRead
from app.ctrader.market import MarketRequest
from app.ctrader.money import to_stored
from app.ctrader.reader import READ_BUDGET_S, BalanceRead, Credentials, read_balances
from app.ctrader.token_manager import TokenManager
from app.ctrader.tokens import TokenStore, tokens_path
from app.models import Account, SymbolSpec, SyncLog, Trade
from app.models.enums import AccountPlatform, AccountStatus
from app.services import open_positions_snapshot
from app.services.ctrader_specs import store_market
from app.services.ctrader_trades import CtraderTradeResult, write_ctrader_trades
from app.services.excursions import excursion_targets, store_excursions
from app.services.sync import (
    INTERNAL_ERROR,
    MAX_ERROR_MESSAGE,
    POSITIONS_SKIPPED,
    history_window_start,
    is_due,
    skipped_message,
)

logger = logging.getLogger(__name__)

CTRADER_JOB_ID: Final = "ctrader_balance"
CTRADER_JOB_INTERVAL_S: Final = 60
SPEC_REFRESH: Final = timedelta(hours=1)

ReadResults = dict[int, BalanceRead | CtraderError]
BalanceReader = Callable[..., Coroutine[Any, Any, ReadResults]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CtraderJobConfig:
    client_id: str
    client_secret: SecretStr
    store: TokenStore
    connector: Connector = open_websocket
    sleep: Sleep = asyncio.sleep
    now: Callable[[], datetime] = _utc_now
    read: BalanceReader = read_balances
    rules_getter: Callable[[], RulesConfig] = get_rules
    symbols_getter: Callable[[], SymbolsConfig] = get_symbols_config
    budget_s: float = READ_BUDGET_S  # token step + reads, below the job interval
    snapshot_path: Path | None = None  # Home open positions; None = not written

    @classmethod
    def from_settings(cls, settings: Settings) -> CtraderJobConfig:
        return cls(
            client_id=settings.ctrader_client_id.strip(),
            client_secret=settings.ctrader_client_secret,
            store=TokenStore(tokens_path(settings.data_dir)),
            snapshot_path=open_positions_snapshot.snapshot_path(settings.data_dir),
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret.get_secret_value().strip())


@dataclass(frozen=True)
class _Target:
    account_id: int
    ctid: int
    is_live: bool
    request: HistoryRequest
    market: MarketRequest
    excursions: ExcursionRequest


@dataclass(frozen=True)
class _Outcome:
    ok: bool
    code: str | None = None
    message: str | None = None
    trades: CtraderTradeResult | None = None
    open_pnl: dict[int, Decimal | None] = field(default_factory=dict)


def _open_trades(session: Session, account_id: int) -> dict[int, datetime]:
    rows = session.execute(
        select(Trade.position_id, Trade.open_time).where(
            Trade.account_id == account_id, Trade.close_time.is_(None)
        )
    )
    return {row.position_id: row.open_time for row in rows}


def _market_request(
    session: Session, account: Account, symbols: SymbolsConfig, now: datetime
) -> MarketRequest:
    """Specs are due without any stored one or when the newest is `SPEC_REFRESH` old."""
    rows = session.execute(
        select(SymbolSpec.symbol, SymbolSpec.currency_profit, SymbolSpec.synced_at).where(
            SymbolSpec.account_id == account.id
        )
    ).all()
    newest = max((row.synced_at for row in rows), default=None)
    return MarketRequest(
        symbols=symbols,
        firm=account.firm,
        account_currency=account.currency or "",
        refresh_specs=newest is None or now - newest >= SPEC_REFRESH,
        known_specs=frozenset(row.symbol for row in rows),
        stored_currencies=frozenset(row.currency_profit.strip().upper() for row in rows),
    )


def _excursion_request(session: Session, account_id: int, now: datetime) -> ExcursionRequest:
    """The MT5 targets (`excursion_targets`, never raises) and the stored points."""
    targets = tuple(excursion_targets(session, account_id, now))
    if not targets:
        return ExcursionRequest()
    rows = session.execute(
        select(SymbolSpec.symbol, SymbolSpec.point).where(SymbolSpec.account_id == account_id)
    ).all()
    return ExcursionRequest(
        targets, {row.symbol: row.point for row in rows if row.point is not None and row.point > 0}
    )


def _due_targets(
    session_factory: sessionmaker[Session],
    rules: RulesConfig,
    symbols: SymbolsConfig,
    now: datetime,
) -> list[_Target]:
    with session_factory() as session:
        accounts = session.scalars(
            select(Account)
            .where(
                Account.status == AccountStatus.ACTIVE.value,
                Account.platform == AccountPlatform.CTRADER.value,
            )
            .order_by(Account.id)
        ).all()
        return [
            _Target(
                account.id,
                account.ctid_trader_account_id,
                bool(account.ctrader_is_live),
                HistoryRequest(
                    window_from=history_window_start(
                        session, account.id, rules.sync, now, require_deals=True
                    ),
                    to=now,
                    open_trades=_open_trades(session, account.id),
                ),
                _market_request(session, account, symbols, now),
                _excursion_request(session, account.id, now),
            )
            for account in accounts
            if account.ctid_trader_account_id is not None
            and is_due(session, account.id, rules, now)
        ]


def _store_read(account: Account, read: BalanceRead, at: datetime) -> _Outcome:
    """Apply a read to the account. Conversion comes first, so a refusal writes nothing."""
    balance = to_stored(read.balance)
    equity: Decimal | None = to_stored(read.equity) if read.equity is not None else None
    if equity is not None:
        account.balance, account.equity, account.balance_synced_at = balance, equity, at
        return _Outcome(ok=True)
    if account.equity is None:  # nothing to keep consistent with
        account.balance, account.balance_synced_at = balance, at
    return _Outcome(
        ok=False,
        code=CtraderErrorCode.EQUITY_UNAVAILABLE.value,
        message=f"equity not read: {read.equity_error or 'unknown'}",
    )


def _store_trading(
    session: Session,
    account: Account,
    read: BalanceRead,
    trading: TradingRead,
    rules: RulesConfig,
    symbols: SymbolsConfig,
) -> _Outcome:
    """The trades of one read in a savepoint: a failure keeps the balance and is returned."""
    try:
        with session.begin_nested():
            result = write_ctrader_trades(session, account, trading, read.balance, rules, symbols)
    except CtraderError as exc:
        return _Outcome(ok=False, code=exc.code.value, message=exc.message)
    except Exception as exc:
        logger.exception("cTrader trades of account %s not stored", account.id)
        return _Outcome(ok=False, code=INTERNAL_ERROR, message=type(exc).__name__)
    pnl = read.position_pnl
    open_pnl = {pos.position_id: pnl.get(pos.position_id) for pos in trading.positions}
    if result.skipped:
        message = skipped_message(list(result.skipped))
        return _Outcome(True, POSITIONS_SKIPPED, message, trades=result, open_pnl=open_pnl)
    return _Outcome(ok=True, trades=result, open_pnl=open_pnl)


def _joined(*messages: str | None) -> str | None:
    return "; ".join(m for m in messages if m) or None


def _combine(balance: _Outcome, trading: _Outcome) -> _Outcome:
    """Severity of the code: a failed history, then a missing equity (both errors), then a
    trades warning (``positions_skipped``, ok stays True). Every message is kept, joined."""
    if not trading.ok:
        return _Outcome(False, trading.code, _joined(trading.message, balance.message))
    if not balance.ok:
        return _Outcome(
            False,
            balance.code,
            _joined(balance.message, trading.message),
            trades=trading.trades,
            open_pnl=trading.open_pnl,
        )
    return trading


def _apply(
    session: Session,
    account: Account,
    result: BalanceRead | CtraderError,
    started: datetime,
    rules: RulesConfig,
    symbols: SymbolsConfig,
) -> _Outcome:
    try:
        if isinstance(result, CtraderError):
            raise result
        outcome = _store_read(account, result, started)
    except CtraderError as exc:
        return _Outcome(ok=False, code=exc.code.value, message=exc.message)
    store_market(session, account, result.market, symbols, started)  # never raises
    trading = result.trading
    if trading is None:
        return outcome
    if isinstance(trading, CtraderError):
        return _Outcome(ok=False, code=trading.code.value, message=trading.message)
    return _combine(outcome, _store_trading(session, account, result, trading, rules, symbols))


def _store_excursions(
    session: Session, account: Account, result: BalanceRead | CtraderError, at: datetime
) -> None:
    """After the trades, in a savepoint; never raises (a failure is a WARNING)."""
    fetched = result.excursions if isinstance(result, BalanceRead) else None
    if fetched is None or (not fetched.series and not fetched.failed):
        return
    try:
        with session.begin_nested():
            changed = store_excursions(session, fetched, at)
        logger.info("cTrader account %s: MAE/MFE stored for %s trades", account.id, changed)
    except Exception as exc:
        logger.warning(
            "cTrader account %s: MAE/MFE not stored: %s",
            account.id,
            type(exc).__name__,
            exc_info=True,
        )


def _log_row(target: _Target, outcome: _Outcome, started: datetime, finished: datetime) -> SyncLog:
    trades = outcome.trades
    return SyncLog(
        account_id=target.account_id,
        started_at=started,
        finished_at=finished,
        ok=outcome.ok,
        error_code=outcome.code,
        error_message=(outcome.message or "")[:MAX_ERROR_MESSAGE] or None,
        deals_fetched=trades.deals_read if trades is not None else 0,
        trades_created=trades.created if trades is not None else 0,
        trades_updated=trades.updated if trades is not None else 0,
        open_positions=trades.open_positions if trades is not None else 0,
    )


def _record(
    session_factory: sessionmaker[Session],
    target: _Target,
    result: BalanceRead | CtraderError,
    started: datetime,
    config: CtraderJobConfig,
    context: tuple[RulesConfig, SymbolsConfig],
) -> bool:
    """One account's values, trades and sync_log row in one transaction. True on full success."""
    rules, symbols = context
    with session_factory() as session:
        account = session.get(Account, target.account_id)
        if (
            account is None
            or account.status != AccountStatus.ACTIVE.value
            or account.platform != AccountPlatform.CTRADER.value
        ):
            return False  # deleted/archived during the read
        outcome = _apply(session, account, result, started, rules, symbols)
        _store_excursions(session, account, result, started)
        session.add(_log_row(target, outcome, started, config.now()))
        session.commit()
    _log_outcome(target, outcome)
    if outcome.trades is not None:
        _write_snapshot(config.snapshot_path, target.account_id, outcome, started)
    return outcome.ok


def _log_outcome(target: _Target, outcome: _Outcome) -> None:
    trades = outcome.trades
    if outcome.ok:
        logger.info(
            "cTrader account %s synced%s%s",
            target.account_id,
            f": {trades.deals_read} deals, {trades.created} new, {trades.updated} updated "
            f"trades, {trades.open_positions} open"
            if trades is not None
            else "",
            f" ({outcome.code})" if outcome.code else "",
        )
        return
    logger.error(
        "cTrader sync of account %s failed: %s: %s",
        target.account_id,
        outcome.code,
        outcome.message,
    )


def _write_snapshot(path: Path | None, account_id: int, outcome: _Outcome, at: datetime) -> None:
    """After the commit; a failure here is logged, never fails the sync (as for MT5)."""
    if path is None:
        return
    values = {
        pid: open_positions_snapshot.LiveValue(None, pnl, at)
        for pid, pnl in outcome.open_pnl.items()
    }
    try:
        open_positions_snapshot.write_account_values(path, account_id, values, at)
    except Exception:
        logger.exception("cTrader account %s: open positions snapshot not written", account_id)


def _read_all(config: CtraderJobConfig, targets: Sequence[_Target]) -> ReadResults:
    """Every target gets a result; nothing here raises for a cTrader or token problem."""
    began = time.monotonic()
    try:
        if not config.configured:
            raise CtraderError(CtraderErrorCode.NOT_CONFIGURED, "cTrader app is not configured")
        manager = TokenManager(config.store, config.client_id, config.client_secret, now=config.now)
        creds = Credentials(config.client_id, config.client_secret, manager.fresh_access_token())
        budget = config.budget_s - (time.monotonic() - began)  # the token step counts
        if budget <= 0:
            raise CtraderError(CtraderErrorCode.TIMEOUT, "no time left to read cTrader")
        return asyncio.run(
            config.read(
                creds,
                [(t.ctid, t.is_live) for t in targets],
                config.connector,
                sleep=config.sleep,
                budget_s=budget,
                history={t.ctid: t.request for t in targets},
                clock=config.now,
                markets={t.ctid: t.market for t in targets},
                excursions={t.ctid: t.excursions for t in targets},
            )
        )
    except CtraderError as exc:
        return {t.ctid: exc for t in targets}


def run_ctrader_balance_cycle(
    session_factory: sessionmaker[Session], config: CtraderJobConfig
) -> list[int]:
    """Read and store every due cTrader account. Returns the fully updated account ids.

    A broken rules.yaml or symbols.yaml skips the cycle, as for MT5.
    """
    started = config.now()
    try:
        rules = config.rules_getter()
        symbols = config.symbols_getter()
    except ConfigError as exc:
        logger.error("cTrader sync skipped: %s", exc)
        return []
    targets = _due_targets(session_factory, rules, symbols, started)
    if not targets:
        return []
    try:
        results = _read_all(config, targets)
    except Exception as exc:  # a bug must still be visible in the status bar
        logger.error("cTrader balance cycle failed: %s", type(exc).__name__)
        logger.debug("cTrader balance cycle failure", exc_info=exc)
        failure = _internal_error()
        results = {t.ctid: failure for t in targets}
    done: list[int] = []
    for target in targets:
        result = results.get(target.ctid, _internal_error())
        try:
            if _record(session_factory, target, result, started, config, (rules, symbols)):
                done.append(target.account_id)
        except Exception:
            logger.exception("cTrader sync of account %s not stored", target.account_id)
    return done


def _internal_error() -> CtraderError:
    return CtraderError(CtraderErrorCode.INTERNAL_ERROR, "unexpected error, see worker.log")
