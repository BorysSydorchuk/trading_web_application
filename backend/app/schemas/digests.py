"""Digests API request/response models (docs/api.md "Digests API").

The ``metrics`` snapshot is plain JSON built by ``app.services.digest_snapshot`` (numbers are
already 2 dp / 4 dp strings there); these models only shape the envelope around it.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

type DigestKindIn = Literal["weekly", "monthly"]
REVIEW_TEXT_MAX = 10_000
REVIEW_FIELDS: tuple[str, ...] = ("what_worked", "what_to_fix", "focus_next")


class DigestCreate(BaseModel):
    kind: DigestKindIn
    date: date


class DigestPatch(BaseModel):
    """Review texts; omitted = unchanged, ``""`` or null = cleared. Other keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    what_worked: str | None = Field(default=None, max_length=REVIEW_TEXT_MAX)
    what_to_fix: str | None = Field(default=None, max_length=REVIEW_TEXT_MAX)
    focus_next: str | None = Field(default=None, max_length=REVIEW_TEXT_MAX)


class DigestOut(BaseModel):
    id: int
    kind: str
    period_start: date
    period_end: date
    generated_at: UtcDatetime | None
    what_worked: str | None
    what_to_fix: str | None
    focus_next: str | None
    ai_summary: str | None
    reviewed: bool
    next_bias_note_id: int | None
    metrics: dict[str, Any]


class DigestListItem(BaseModel):
    id: int
    kind: str
    period_start: date
    period_end: date
    generated_at: UtcDatetime | None
    trades: int
    net_pnl: str
    net_pnl_pct: str | None
    total_r: str
    win_rate: str | None
    reviewed: bool


class DigestList(BaseModel):
    items: list[DigestListItem]


class PeriodRef(BaseModel):
    period_start: date


class DigestSuggestion(BaseModel):
    weekly: PeriodRef | None
    monthly: PeriodRef | None
