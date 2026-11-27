"""GET /api/dashboard/charts (M8-14): money as strings (2 dp), percents and R (4 dp)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime
from app.schemas.dashboard import Money, Pct


class EquityPointOut(BaseModel):
    time: UtcDatetime
    cum_pnl: Money
    cum_pct: Pct | None


class DayPnlOut(BaseModel):
    day: date  # Brussels
    net_pnl: Money
    pct: Pct | None
    trades: int


class RollingPointOut(BaseModel):
    time: UtcDatetime
    n: int
    win_rate: Pct
    avg_r: Pct | None


class HomeCharts(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    currency: str | None
    account_size: Money | None
    trades: int
    equity: list[EquityPointOut]
    daily: list[DayPnlOut]
    rolling: list[RollingPointOut]
    rolling_window: int
    # «Головна» %-only (owner 2026-11-27): the range result in % (equal-weighted average of the
    # accounts' %, `app.domain.equal_weight`), the plain sum of R, and how many accounts count.
    total_pct: Pct | None
    total_r: Pct | None
    accounts_counted: int
