"""Trades / inbox / journal API schemas (docs/api.md M1 "Trades", M2 journal)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.chart_links import MAX_LINKS, MAX_URL_LENGTH, is_valid_chart_url
from app.models.enums import InitialSlSource
from app.schemas.audio import AudioNoteOut
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

RAW_TEXT_MAX_LENGTH = 20000
MAX_AI_FILLED_FIELDS = 100

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
    # M4 (PRD 6.6): daily = effective value (override ?? auto); weekly/monthly are auto only.
    bias_alignment: str | None
    bias_alignment_weekly: str | None
    bias_alignment_monthly: str | None


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


class ChartLinkOut(BaseModel):
    id: int
    url: str
    kind: str
    preview_url: str | None  # snapshot image; None for /chart links


class BiasNoteIds(BaseModel):
    """Bias notes whose entry decided each alignment (null = no_bias / config broken)."""

    daily: int | None
    weekly: int | None
    monthly: int | None


class TradeDetail(TradeRow):
    """M2 shape (docs/api.md "TradeDetail in M2"): journal values live in `journal`."""

    initial_sl_source: InitialSlSource | None
    exit_deals: list[ExitDeal]
    rule_violations: list[RuleViolationOut]
    # Every YAML key except links fields (config/journal_fields.yaml), None when empty.
    journal: dict[str, Any]
    chart_links: list[ChartLinkOut]
    raw_text: str | None
    transcript: str | None
    ai_filled_fields: list[str]
    described_at: UtcDatetime | None
    missing_required: list[str]  # what blocks `complete` now, YAML order
    # Required now, empty, made required after this trade closed (M3, informational).
    missing_new_fields: list[str]
    audio_notes: list[AudioNoteOut]  # oldest first (M3)
    bias_note_ids: BiasNoteIds  # M4: links from Describe to the bias notes


def check_chart_url(value: str) -> str:
    """TradingView link rule of docs/api.md M2 (trade and bias links)."""
    if len(value) > MAX_URL_LENGTH:
        raise ValueError(f"must be at most {MAX_URL_LENGTH} characters")
    if not is_valid_chart_url(value):
        raise ValueError("must be a TradingView snapshot (/x/<id>) or chart (/chart) link")
    return value


class ChartLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    url: str
    kind: Literal["before", "after"]

    _tradingview = field_validator("url")(check_chart_url)


class JournalInput(BaseModel):
    """PUT /api/trades/{id}/journal (docs/api.md "Journal save"). All keys required.

    `fields` values are validated against config/journal_fields.yaml by the service.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    fields: dict[str, Any]
    chart_links: list[ChartLinkIn] = Field(max_length=MAX_LINKS)
    raw_text: str | None = Field(max_length=RAW_TEXT_MAX_LENGTH)
    ai_filled_fields: list[str] = Field(max_length=MAX_AI_FILLED_FIELDS)
    complete: bool


class TradePatch(BaseModel):
    """Only the initial SL (docs/api.md); journal fields use PUT .../journal."""

    model_config = ConfigDict(extra="forbid")

    initial_sl: Price


class InboxCounts(BaseModel):
    needs_sl: int
    needs_description: int
    draft: int


class SymbolList(BaseModel):
    items: list[str]
