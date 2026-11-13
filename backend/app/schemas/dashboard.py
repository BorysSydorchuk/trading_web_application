"""`GET /api/dashboard` response (docs/api.md "Dashboard API (PRD 6.10)", M6-03 details).

Money is a 2 dp string, percents are 4 dp strings (ROUND_HALF_UP, applied here at the API
edge only); prices and volumes keep their full stored precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

from app.domain.period_pnl import LimitState
from app.schemas.calculator import PlainDecimal
from app.schemas.common import UtcDatetime
from app.schemas.trades import InboxCounts

MONEY_Q = Decimal("0.01")
PCT_Q = Decimal("0.0001")


def money_str(value: Decimal) -> str:
    return format(value.quantize(MONEY_Q, rounding=ROUND_HALF_UP), "f")


def pct_str(value: Decimal) -> str:
    return format(value.quantize(PCT_Q, rounding=ROUND_HALF_UP), "f")


Money = Annotated[Decimal, PlainSerializer(money_str, return_type=str)]
Pct = Annotated[Decimal, PlainSerializer(pct_str, return_type=str)]


class PeriodBlock(BaseModel):
    pnl: Money
    pct: Pct
    low_pnl: Money
    low_pct: Pct
    high_pnl: Money
    high_pct: Pct


class Limits(BaseModel):
    """Stop limits from config/rules.yaml; ``None`` = the rule is disabled."""

    daily_loss_pct: Pct | None
    daily_profit_pct: Pct | None
    weekly_loss_pct: Pct | None
    weekly_profit_pct: Pct | None


class DashboardAccount(BaseModel):
    id: int
    name: str
    currency: str
    account_size: Money
    today: PeriodBlock
    week: PeriodBlock
    limits: Limits
    today_state: LimitState
    week_state: LimitState


class StopFlags(BaseModel):
    today: bool
    week: bool


class OpenPosition(BaseModel):
    trade_id: int
    account_name: str
    symbol: str  # canonical (config/symbols.yaml)
    direction: str
    volume: PlainDecimal
    entry_price: PlainDecimal
    open_time: UtcDatetime
    initial_sl: PlainDecimal | None
    risk_amount: Money | None
    risk_pct: Pct | None


class Dashboard(BaseModel):
    now: UtcDatetime
    accounts: list[DashboardAccount]
    stop: StopFlags
    open_positions: list[OpenPosition]
    inbox: InboxCounts
