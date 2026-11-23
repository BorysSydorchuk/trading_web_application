"""cTrader API schemas (docs/api.md "cTrader"). No token or secret ever appears here."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountPhase, AccountStatus
from app.schemas.accounts import MAX_LOGIN, Currency, Name100, Percent, PositiveMoney

CtidAccountId = Annotated[int, Field(strict=True, gt=0, le=MAX_LOGIN)]


class CtraderStatus(BaseModel):
    configured: bool
    connected: bool
    error_code: str | None


class CtraderConnect(BaseModel):
    authorize_url: str


class CtraderAccountItem(BaseModel):
    ctid_trader_account_id: int
    is_live: bool
    trader_login: int | None
    broker: str
    already_added: bool


class CtraderAccountList(BaseModel):
    items: list[CtraderAccountItem]


class CtraderAccountInput(BaseModel):
    """The chosen cTrader account + the journal fields. Login and server come from cTrader."""

    model_config = ConfigDict(extra="forbid")

    ctid_trader_account_id: CtidAccountId
    name: Name100
    firm: Name100
    program: Name100
    phase: AccountPhase
    starting_balance: PositiveMoney
    currency: Currency
    status: AccountStatus = AccountStatus.ACTIVE
    reference_balance: PositiveMoney | None = None
    daily_loss_pct: Percent | None = None
    max_drawdown_pct: Percent | None = None
    profit_target_pct: Percent | None = None
