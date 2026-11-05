"""Bias notes / entries / status API schemas (docs/api.md M4)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.domain.chart_links import MAX_LINKS
from app.schemas.audio import AudioNoteOut
from app.schemas.common import UtcDatetime
from app.schemas.trades import RAW_TEXT_MAX_LENGTH, ChartLinkOut, check_chart_url

TEXT_MAX_LENGTH = 5000
MAX_ENTRIES = 20  # one per bias.yaml symbol; generous upper bound for the request size
BiasKindValue = Literal["pre_london", "pre_ny", "weekly", "monthly"]
BiasDirectionValue = Literal["bullish", "bearish", "neutral", "no_trade"]
# Entry fields the AI can fill (docs/api.md "Bias extraction").
AiFillable = Literal["direction", "key_levels", "narrative", "confidence"]


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


OptionalText = Annotated[
    str | None, Field(max_length=TEXT_MAX_LENGTH), AfterValidator(_strip_or_none)
]


def _date_string(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError('must be a date string "YYYY-MM-DD"')
    return value


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BiasLinkIn(_StrictInput):
    url: str

    _tradingview = field_validator("url")(check_chart_url)


class BiasEntryInput(_StrictInput):
    symbol: str  # checked against bias.yaml by the service
    direction: BiasDirectionValue
    key_levels: OptionalText = None
    narrative: OptionalText = None
    confidence: Annotated[int | None, Field(ge=1, le=3)] = None
    chart_links: list[BiasLinkIn] = Field(default_factory=list, max_length=MAX_LINKS)
    ai_filled_fields: list[AiFillable] = Field(default_factory=list, max_length=10)


class BiasNoteInput(_StrictInput):
    kind: BiasKindValue
    # A "YYYY-MM-DD" string only; normalized to the Monday / 1st by the service.
    period_date: Annotated[date, BeforeValidator(_date_string), Field(strict=False)]
    raw_text: str | None = Field(default=None, max_length=RAW_TEXT_MAX_LENGTH)
    entries: list[BiasEntryInput] = Field(max_length=MAX_ENTRIES)


class BiasResultInput(_StrictInput):
    was_correct: bool | None


class BiasEntryOut(BaseModel):
    id: int
    symbol: str
    direction: str
    key_levels: str | None
    narrative: str | None
    confidence: int | None
    chart_links: list[ChartLinkOut]
    was_correct: bool | None
    was_correct_source: str | None
    ai_filled_fields: list[str]


class BiasNoteOut(BaseModel):
    id: int
    kind: str
    period_date: date
    raw_text: str | None
    entries: list[BiasEntryOut]  # bias.yaml symbol order
    audio_notes: list[AudioNoteOut]  # oldest first
    created_at: UtcDatetime
    updated_at: UtcDatetime


class BiasNoteList(BaseModel):
    items: list[BiasNoteOut]


class BiasSessionStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note_id: int | None
    missing: bool
    remind: bool
    start: str = Field(alias="from")  # "HH:MM" Brussels
    until: str


class BiasSessions(BaseModel):
    pre_london: BiasSessionStatus
    pre_ny: BiasSessionStatus


class BiasPeriodStatus(BaseModel):
    note_id: int | None


class BiasStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    today: date = Field(alias="date")  # Brussels date
    weekday: bool
    now: UtcDatetime
    sessions: BiasSessions
    weekly: BiasPeriodStatus
    monthly: BiasPeriodStatus
