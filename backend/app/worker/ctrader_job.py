"""The `ctrader_balance` worker job: balance and equity of active cTrader accounts.

Separate from the MT5 job and its lock, on the same cadence rule (`is_due`: 60 s in trading
hours, the idle interval otherwise). Every attempt records one `sync_log` row, so the status
bar works as for MT5. A failed read never overwrites a good value.

Equity = balance + the positions' net unrealized P&L (`app.ctrader.money.equity_from`). When
the balance was read but the equity was not, the stored balance/equity pair stays as it is:
Home computes the floating P&L as equity - balance, so a new balance next to an old equity
would show a false number. Only an account with no stored equity gets the balance alone.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.config_files import ConfigError, get_rules
from app.config_files.rules import RulesConfig
from app.ctrader.connection import Connector, Sleep, open_websocket
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.money import to_stored
from app.ctrader.reader import READ_BUDGET_S, BalanceRead, Credentials, read_balances
from app.ctrader.token_manager import TokenManager
from app.ctrader.tokens import TokenStore, tokens_path
from app.models import Account, SyncLog
from app.models.enums import AccountPlatform, AccountStatus
from app.services.sync import MAX_ERROR_MESSAGE, is_due

logger = logging.getLogger(__name__)

CTRADER_JOB_ID: Final = "ctrader_balance"
CTRADER_JOB_INTERVAL_S: Final = 60

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
    budget_s: float = READ_BUDGET_S  # token step + reads, below the job interval

    @classmethod
    def from_settings(cls, settings: Settings) -> CtraderJobConfig:
        return cls(
            client_id=settings.ctrader_client_id.strip(),
            client_secret=settings.ctrader_client_secret,
            store=TokenStore(tokens_path(settings.data_dir)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret.get_secret_value().strip())


@dataclass(frozen=True)
class _Target:
    account_id: int
    ctid: int
    is_live: bool


@dataclass(frozen=True)
class _Outcome:
    ok: bool
    code: str | None = None
    message: str | None = None


def _due_targets(
    session_factory: sessionmaker[Session], rules: RulesConfig, now: datetime
) -> list[_Target]:
    with session_factory() as session:
        rows = session.execute(
            select(Account.id, Account.ctid_trader_account_id, Account.ctrader_is_live)
            .where(
                Account.status == AccountStatus.ACTIVE.value,
                Account.platform == AccountPlatform.CTRADER.value,
            )
            .order_by(Account.id)
        ).all()
        return [
            _Target(account_id, ctid, bool(is_live))
            for account_id, ctid, is_live in rows
            if ctid is not None and is_due(session, account_id, rules, now)
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


def _record(
    session_factory: sessionmaker[Session],
    target: _Target,
    result: BalanceRead | CtraderError,
    started: datetime,
    now: Callable[[], datetime],
) -> bool:
    """One account's values and its sync_log row in one transaction. True on a full success."""
    with session_factory() as session:
        account = session.get(Account, target.account_id)
        if (
            account is None
            or account.status != AccountStatus.ACTIVE.value
            or account.platform != AccountPlatform.CTRADER.value
        ):
            return False  # deleted/archived during the read
        try:
            if isinstance(result, CtraderError):
                raise result
            outcome = _store_read(account, result, started)
        except CtraderError as exc:
            outcome = _Outcome(ok=False, code=exc.code.value, message=exc.message)
        session.add(
            SyncLog(
                account_id=target.account_id,
                started_at=started,
                finished_at=now(),
                ok=outcome.ok,
                error_code=outcome.code,
                error_message=(outcome.message or "")[:MAX_ERROR_MESSAGE] or None,
            )
        )
        session.commit()
    if outcome.ok:
        logger.info("cTrader balance of account %s updated", target.account_id)
    else:
        logger.error(
            "cTrader balance of account %s failed: %s: %s",
            target.account_id,
            outcome.code,
            outcome.message,
        )
    return outcome.ok


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
            )
        )
    except CtraderError as exc:
        return {t.ctid: exc for t in targets}


def run_ctrader_balance_cycle(
    session_factory: sessionmaker[Session], config: CtraderJobConfig
) -> list[int]:
    """Read and store every due cTrader account. Returns the fully updated account ids.

    A broken rules.yaml skips the cycle, as for MT5.
    """
    started = config.now()
    try:
        rules = config.rules_getter()
    except ConfigError as exc:
        logger.error("cTrader balance sync skipped: %s", exc)
        return []
    targets = _due_targets(session_factory, rules, started)
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
            if _record(session_factory, target, result, started, config.now):
                done.append(target.account_id)
        except Exception:
            logger.exception("cTrader balance of account %s not stored", target.account_id)
    return done


def _internal_error() -> CtraderError:
    return CtraderError(CtraderErrorCode.INTERNAL_ERROR, "unexpected error, see worker.log")
