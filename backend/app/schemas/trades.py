"""Trades / inbox / journal API schemas (docs/api.md M1 "Trades", M2 journal)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.chart_links import MAX_LINKS, MAX_URL_LENGTH, is_valid_chart_url
from app.models.enums import ExitReasonSource, InitialSlSource, StatsExclusionAction
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
    # M8-01: left out of strategy statistics (still counted in money and risk).
    excluded_from_stats: bool
    excluded_reason: str | None
    excluded_at: UtcDatetime | None
    # M8-16: MAE / MFE in R (None without an initial SL or before it is computed).
    mfe_r: Decimal | None
    mae_r: Decimal | None
    excursion_status: str | None  # final | running («поточні») | unavailable | None


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
    reason: str | None  # lowercase DEAL_REASON key
    reason_code: int | None  # raw MT5 DEAL_REASON (M8-09); None before M8-09 / not reported


class RuleViolationOut(BaseModel):
    rule_key: str
    source: str
    details: str | None


class ChartLinkOut(BaseModel):
    id: int
    url: str
    kind: str
    preview_url: str | None  # snapshot image; None for /chart links


class StatsExclusionOut(BaseModel):
    """One M8-01 history row: excluded from or returned to strategy statistics."""

    action: StatsExclusionAction
    reason: str | None
    at: UtcDatetime


class BiasNoteIds(BaseModel):
    """Bias notes whose entry decided each alignment (null = no_bias / config broken)."""

    daily: int | None
    weekly: int | None
    monthly: int | None


class TradeDetail(TradeRow):
    """M2 shape (docs/api.md "TradeDetail in M2"): journal values live in `journal`."""

    initial_sl_source: InitialSlSource | None
    # Who set journal.exit_reason (M8-09): mt5_reason / price_match = prefilled from MT5
    # (the UI marks it until the owner changes it), owner, or None.
    exit_reason_source: ExitReasonSource | None
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
    exclusion_history: list[StatsExclusionOut]  # M8-01, oldest first
    # M8-16: extreme prices, symbol points and times (long = bid, short = ask).
    mfe_price: Decimal | None
    mfe_points: Decimal | None
    mfe_time: UtcDatetime | None
    mae_price: Decimal | None
    mae_points: Decimal | None
    mae_time: UtcDatetime | None
    excursion_source: str | None
    excursion_at: UtcDatetime | None


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
    # M8-02: the form was built while the trade was open (pre-entry fields only). If the
    # trade has closed since, the save keeps the stored after-trade values and links.
    form_open: bool = False


class TradePatch(BaseModel):
    """Only the initial SL (docs/api.md); journal fields use PUT .../journal."""

    model_config = ConfigDict(extra="forbid")

    initial_sl: Price


EXCLUSION_REASON_MAX_LENGTH = 1000


def _trimmed(value: str | None) -> str | None:
    if value is None:
        return None
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    text = value.strip()
    if len(text) > EXCLUSION_REASON_MAX_LENGTH:
        raise ValueError(f"must be at most {EXCLUSION_REASON_MAX_LENGTH} characters")
    return text or None


class ExcludeInput(BaseModel):
    """POST /api/trades/{id}/exclude (docs/api.md M8-01): the reason is mandatory."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str

    @field_validator("reason")
    @classmethod
    def _required(cls, value: str) -> str:
        text = _trimmed(value)
        if text is None:
            raise ValueError("must not be empty")
        return text


class IncludeInput(BaseModel):
    """POST /api/trades/{id}/include: optional reason, blank = none."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str | None = None

    _trim = field_validator("reason")(_trimmed)


class InboxCounts(BaseModel):
    needs_sl: int
    needs_description: int
    draft: int


class SymbolList(BaseModel):
    items: list[str]
