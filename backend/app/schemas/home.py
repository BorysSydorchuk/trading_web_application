"""`GET /api/home` response (M8-10b; docs/api.md "M8-10b - «Головна» rebuild").

Money 2 dp, percents and R 4 dp (ROUND_HALF_UP at this edge only), prices plain decimals,
all as strings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.calculator import PlainDecimal
from app.schemas.common import UtcDatetime
from app.schemas.dashboard import Money, Pct

R = Pct  # R multiples share the 4 dp string format

SessionKey = Literal["london", "premarket", "ny", "outside"]


class SessionNow(BaseModel):
    key: SessionKey
    entries_allowed: bool


class BiasEntryOut(BaseModel):
    symbol: str
    direction: str


class BiasToday(BaseModel):
    pre_london: list[BiasEntryOut] | None  # None = no pre-London note today
    pre_ny_missing: bool


class LimitBar(BaseModel):
    pct: Pct | None  # None: the account has no usable size
    loss_pct: Pct | None  # None: rule disabled / no account_limits
    profit_pct: Pct | None


class AccountLimitsOut(BaseModel):
    account_id: int
    account_name: str
    currency: str
    day: LimitBar
    week: LimitBar
    month: LimitBar
    trades_week: int
    max_trades_week: int | None
    to_daily_stop_pct: Pct | None
    # M8-10b fixes: equity - balance of a fresh worker sync, added to day/week/month pct;
    # None (and not included) when the sync is stale/unknown while a position is open.
    floating_pnl: Money | None
    floating_included: bool
    # Last synced figures of the account (MT5 or cTrader); balance_fresh is False when that
    # sync is older than the snapshot staleness limit or never happened.
    balance: Money | None
    equity: Money | None
    balance_fresh: bool


class CumPoint(BaseModel):
    time: UtcDatetime
    cum_pnl: Money


class ValuePoint(BaseModel):
    time: UtcDatetime
    value: Pct


class PctPoint(BaseModel):
    time: UtcDatetime
    pct: Pct


class TodayKpi(BaseModel):
    pnl: Money
    pct: Pct | None
    trades: int
    series: list[CumPoint]


class RollingKpi(BaseModel):
    value: Pct | None
    n: int
    window: int
    series: list[ValuePoint]


class DrawdownKpi(BaseModel):
    pct: Pct | None
    limit_pct: Pct | None
    series: list[PctPoint]


EquitySource = Literal["mt5", "balance", "trades"]


class MaxLossKpi(BaseModel):
    """«До макс. збитку» (follow-up 2026-11-20): distance of equity to the FundedNext static
    floor size x (1 + limit_pct / 100), percent of the size."""

    account_id: int
    account_name: str
    pct: Pct
    limit_pct: Pct
    equity: Money
    equity_source: EquitySource
    series: list[PctPoint]


class Kpis(BaseModel):
    today: TodayKpi
    win_rate: RollingKpi
    avg_r: RollingKpi
    drawdown: DrawdownKpi  # kept for compatibility; the UI shows max_loss instead
    max_loss: MaxLossKpi | None  # None: no account_limits or no account with a size


class OpenPositionOut(BaseModel):
    trade_id: int
    symbol: str
    direction: str
    volume: PlainDecimal
    account_id: int
    account_name: str
    open_time: UtcDatetime
    entry_price: PlainDecimal
    initial_sl: PlainDecimal | None
    tp: PlainDecimal | None
    current_price: PlainDecimal | None
    price_time: UtcDatetime | None
    pnl: Money | None
    r_now: R | None
    tp_r: R | None
    mae_r: R | None
    mfe_r: R | None
    risk_pct: Pct | None
    described: bool
    # MT5 no longer reports the position; its close is not in the history yet (no live values).
    close_unconfirmed: bool = False


class OpenTotalsOut(BaseModel):
    pnl: Money | None
    risk_pct: Pct | None
    price_time: UtcDatetime | None


class Home(BaseModel):
    now: UtcDatetime
    timezone: str
    session: SessionNow
    bias_today: BiasToday
    limits: AccountLimitsOut | None  # None: no account to show
    kpis: Kpis
    open_positions: list[OpenPositionOut]
    open_totals: OpenTotalsOut
