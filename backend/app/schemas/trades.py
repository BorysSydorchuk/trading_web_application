"""Trades / inbox API schemas (docs/api.md M1 "Trades")."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InitialSlSource
from app.schemas.common import DecimalIn, UtcDatetime

# Columns of `trades` callers may sort by (docs/api.md); anything else is a 422.
TradeSort = Literal[
    "open_time",
    "close_time",
    "symbol",
    "net_pnl",
    "r_multiple",
    "risk_pct",
    "volume",
    "session",
    "status",
]
SortOrder = Literal["asc", "desc"]

# NUMERIC(20,8) like every price column.
Price = Annotated[DecimalIn, Field(gt=0, max_digits=20, decimal_places=8)]


class TradeRow(BaseModel):
    id: int
    account_id: int
    account_name: str
    position_id: int
    symbol: str
    direction: str
    status: str
    open_time: UtcDatetime
    close_time: UtcDatetime | None
    duration_seconds: int | None
    entry_price: Decimal
    exit_price: Decimal | None
    volume: Decimal
    initial_sl: Decimal | None
    last_sl: Decimal | None
    tp: Decimal | None
    commission: Decimal
    swap: Decimal
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    pnl_pct: Decimal | None
    balance_at_open: Decimal | None
    risk_amount: Decimal | None
    risk_pct: Decimal | None
    r_multiple: Decimal | None
    planned_rr: Decimal | None
    session: str | None
    weekday: int | None
    hour: int | None
    is_reentry: bool
    violations: list[str]  # rule keys, sorted


class TradeList(BaseModel):
    items: list[TradeRow]
    total: int


class ExitDeal(BaseModel):
    ticket: int
    time: UtcDatetime
    price: Decimal
    volume: Decimal
    profit: Decimal
    commission: Decimal
    swap: Decimal
    reason: str | None


class RuleViolationOut(BaseModel):
    rule_key: str
    source: str
    details: str | None


class TradeDetail(TradeRow):
    initial_sl_source: InitialSlSource | None
    exit_deals: list[ExitDeal]
    rule_violations: list[RuleViolationOut]
    # Journal fields (PRD 6.4): stored values as-is; filled from M2.
    setup_context: str | None
    poi_type: str | None
    poi_type_other: str | None
    fvg_kind: str | None
    entry_model: str | None
    exit_reason: str | None
    bias_alignment: str | None
    bias_alignment_weekly: str | None
    bias_alignment_monthly: str | None
    bias_alignment_override: str | None
    bias_alignment_override_reason: str | None
    followed_plan: bool | None
    emotion_before: str | None
    emotion_before_text: str | None
    emotion_after: str | None
    emotion_after_text: str | None
    mistakes: str | None
    lesson: str | None
    quality_rating: int | None
    raw_text: str | None
    transcript: str | None
    ai_filled_fields: list[str]
    extra: dict[str, Any]
    described_at: UtcDatetime | None


class TradePatch(BaseModel):
    """M1 accepts only the initial SL (docs/api.md). Journal fields come in M2."""

    model_config = ConfigDict(extra="forbid")

    initial_sl: Price


class InboxCounts(BaseModel):
    needs_sl: int
    needs_description: int
    draft: int


class SymbolList(BaseModel):
    items: list[str]
