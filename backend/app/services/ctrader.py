"""cTrader connection logic behind `app.api.ctrader`: OAuth, account list, saved accounts.

The callback never puts a token or the code in its redirect, and tokens are stored only after
the grant was verified as view-only.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import urlencode

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.ctrader import oauth
from app.ctrader.connection import Connector, open_websocket
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.reader import AccountGrant, Credentials, CtidAccount, fetch_account_list
from app.ctrader.state import OAuthStateStore
from app.ctrader.token_manager import TokenManager
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.errors import ApiError
from app.models import Account, SyncLog
from app.models.enums import AccountPlatform
from app.schemas.ctrader import CtraderAccountInput, CtraderAccountItem, CtraderStatus

logger = logging.getLogger(__name__)

_MAX_CODE_LENGTH: Final = 2048
_TOKEN_CODES: Final = frozenset(
    {CtraderErrorCode.TOKEN_INVALID.value, CtraderErrorCode.TOKEN_EXPIRED.value}
)
_HTTP_STATUS: Final[dict[CtraderErrorCode, int]] = {
    CtraderErrorCode.NOT_CONFIGURED: 503,
    CtraderErrorCode.TOKEN_EXPIRED: 409,
    CtraderErrorCode.TOKEN_INVALID: 409,
    CtraderErrorCode.TRADE_SCOPE_REFUSED: 403,
    CtraderErrorCode.NOT_AUTHORIZED: 403,
    CtraderErrorCode.RATE_LIMITED: 429,
    CtraderErrorCode.TIMEOUT: 504,
}

_shared_states: Final = OAuthStateStore()


@dataclass(frozen=True)
class CtraderDeps:
    settings: Settings
    store: TokenStore
    states: OAuthStateStore
    http: oauth.TokenHttp = oauth.call_token_endpoint
    connector: Connector = open_websocket

    @property
    def client_id(self) -> str:
        return self.settings.ctrader_client_id.strip()

    @property
    def client_secret(self) -> SecretStr:
        return self.settings.ctrader_client_secret


def default_deps(settings: Settings) -> CtraderDeps:
    return CtraderDeps(settings, TokenStore(tokens_path(settings.data_dir)), _shared_states)


def to_api_error(exc: CtraderError) -> ApiError:
    """The JSON error of a failed cTrader operation: `ctrader_<code>`, safe message."""
    status = _HTTP_STATUS.get(exc.code, 502)
    return ApiError(status, f"ctrader_{exc.code.value}", exc.message)


def _require_configured(deps: CtraderDeps) -> None:
    if not deps.settings.ctrader_configured:
        raise CtraderError(CtraderErrorCode.NOT_CONFIGURED, "cTrader app is not configured")


def _latest_token_error(db: Session, pair: TokenPair) -> str | None:
    """A token error the worker recorded after this token pair was obtained."""
    row = db.execute(
        select(SyncLog.error_code, SyncLog.started_at)
        .join(Account, Account.id == SyncLog.account_id)
        .where(Account.platform == AccountPlatform.CTRADER.value)
        .order_by(SyncLog.started_at.desc(), SyncLog.id.desc())
        .limit(1)
    ).first()
    if row is None or row.error_code not in _TOKEN_CODES or row.started_at < pair.obtained_at:
        return None
    return str(row.error_code)


def get_status(deps: CtraderDeps, db: Session, now: datetime) -> CtraderStatus:
    """No network call: the token file and the worker's last recorded attempt."""
    if not deps.settings.ctrader_configured:
        code = CtraderErrorCode.NOT_CONFIGURED.value
        return CtraderStatus(configured=False, connected=False, error_code=code)
    try:
        pair = deps.store.read()
    except CtraderError as exc:
        return CtraderStatus(configured=True, connected=False, error_code=exc.code.value)
    if pair is None:
        return CtraderStatus(configured=True, connected=False, error_code=None)
    if pair.expires_at <= now:
        code = CtraderErrorCode.TOKEN_EXPIRED.value
        return CtraderStatus(configured=True, connected=False, error_code=code)
    error = _latest_token_error(db, pair)
    return CtraderStatus(configured=True, connected=error is None, error_code=error)


def start_connect(deps: CtraderDeps) -> str:
    _require_configured(deps)
    return oauth.build_authorize_url(deps.client_id, deps.states.issue())


def _frontend_redirect(deps: CtraderDeps, **query: str) -> str:
    base = f"http://127.0.0.1:{deps.settings.frontend_port}/settings"
    return f"{base}?{urlencode(query)}"


def _fetch_grant(deps: CtraderDeps, access_token: SecretStr) -> AccountGrant:
    creds = Credentials(deps.client_id, deps.client_secret, access_token)
    return asyncio.run(fetch_account_list(creds, deps.connector))


def _forget(deps: CtraderDeps) -> None:
    with deps.store.lock():
        deps.store.delete()


def _refuse_trade_scope(deps: CtraderDeps) -> CtraderError:
    """A token that can trade is never kept, nor is anything stored before it."""
    _forget(deps)
    logger.error("cTrader grant refused: the token is not view-only; tokens deleted")
    return CtraderError(CtraderErrorCode.TRADE_SCOPE_REFUSED, "the cTrader grant is not view-only")


def _complete_callback(
    deps: CtraderDeps, code: str | None, state: str | None, error: str | None
) -> None:
    _require_configured(deps)
    if not state or not deps.states.consume(state):
        raise CtraderError(CtraderErrorCode.STATE_INVALID, "invalid or expired state")
    if error:  # the provider's text is never reflected
        raise CtraderError(CtraderErrorCode.ACCESS_DENIED, "access was not granted")
    if not code or len(code) > _MAX_CODE_LENGTH:
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "authorization code is missing")
    pair = oauth.exchange_code(code, deps.client_id, deps.client_secret, http=deps.http)
    grant = _fetch_grant(deps, pair.access_token)
    if not grant.view_only:
        raise _refuse_trade_scope(deps)
    with deps.store.lock():
        deps.store.write(pair)


def finish_callback(
    deps: CtraderDeps, code: str | None, state: str | None, error: str | None
) -> str:
    """The URL to send the browser to. Never raises, never holds a token or the code."""
    try:
        _complete_callback(deps, code, state, error)
    except CtraderError as exc:
        logger.error("cTrader connect failed: %s", exc.code.value)
        return _frontend_redirect(deps, ctrader_error=exc.code.value)
    except Exception as exc:  # the type only: a message could echo the request
        logger.error("cTrader connect failed unexpectedly: %s", type(exc).__name__)
        return _frontend_redirect(deps, ctrader_error=CtraderErrorCode.INTERNAL_ERROR.value)
    logger.info("cTrader connected")
    return _frontend_redirect(deps, ctrader="connected")


def _current_grant(deps: CtraderDeps) -> AccountGrant:
    _require_configured(deps)
    manager = TokenManager(deps.store, deps.client_id, deps.client_secret, http=deps.http)
    grant = _fetch_grant(deps, manager.fresh_access_token())
    if not grant.view_only:
        raise _refuse_trade_scope(deps)
    return grant


def list_accounts(deps: CtraderDeps, db: Session) -> list[CtraderAccountItem]:
    grant = _current_grant(deps)
    added = set(
        db.scalars(
            select(Account.ctid_trader_account_id).where(
                Account.ctid_trader_account_id.is_not(None)
            )
        )
    )
    return [
        CtraderAccountItem(
            ctid_trader_account_id=item.ctid,
            is_live=item.is_live,
            trader_login=item.trader_login,
            broker=item.broker,
            already_added=item.ctid in added,
        )
        for item in grant.accounts
    ]


def _granted_account(deps: CtraderDeps, ctid: int) -> CtidAccount:
    for item in _current_grant(deps).accounts:
        if item.ctid == ctid:
            return item
    raise ApiError(
        422,
        "ctrader_account_not_granted",
        "This account is not in the list granted to the cTrader token",
        {"field": "ctid_trader_account_id"},
    )


def build_account(deps: CtraderDeps, body: CtraderAccountInput) -> Account:
    """A new (unsaved) account for an id the token really grants."""
    granted = _granted_account(deps, body.ctid_trader_account_id)
    if granted.trader_login is None or granted.trader_login <= 0:
        raise ApiError(
            422,
            "ctrader_account_incomplete",
            "cTrader did not return a login for this account",
            {"field": "ctid_trader_account_id"},
        )
    data = body.model_dump()
    data["phase"] = body.phase.value
    data["status"] = body.status.value
    if data["reference_balance"] is None:  # as POST /api/accounts
        data["reference_balance"] = body.starting_balance
    return Account(
        **data,
        platform=AccountPlatform.CTRADER.value,
        ctrader_is_live=granted.is_live,
        login=granted.trader_login,
        server=granted.broker,
        terminal_path=None,
    )


def forget_connection(deps: CtraderDeps) -> None:
    """Accounts stay; the worker then records `token_invalid` for them."""
    _forget(deps)
    logger.info("cTrader connection forgotten")
