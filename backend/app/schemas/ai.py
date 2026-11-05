"""Request/response models of the AI endpoints (docs/api.md M2 "AI extraction", "AI usage")."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.bias import BiasKindValue
from app.schemas.common import UtcDatetime
from app.services.ai.key_status import KeyState

EXTRACT_TEXT_MAX_LENGTH = 20000


class ExtractInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=EXTRACT_TEXT_MAX_LENGTH)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class DroppedOut(BaseModel):
    key: str
    reason: str


class ExtractUsageOut(BaseModel):
    model: str
    fallback_used: bool
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None  # JSON string, 4 decimals
    duration_ms: int


class ExtractResult(BaseModel):
    fields: dict[str, Any]
    ai_filled_fields: list[str]
    missing_required: list[str]
    dropped: list[DroppedOut]
    usage: ExtractUsageOut


class BiasExtractInput(ExtractInput):
    """POST /api/bias/notes/extract body: the note text and its kind (prompt context)."""

    kind: BiasKindValue


class BiasDroppedOut(BaseModel):
    symbol: str
    key: str
    reason: str


class BiasExtractEntryOut(BaseModel):
    symbol: str
    fields: dict[str, str | int]  # kept fields only: direction, key_levels, narrative, confidence
    evidence: dict[str, str]  # same keys as `fields`: the model's quote from the text


class BiasExtractResult(BaseModel):
    entries: list[BiasExtractEntryOut]  # bias.yaml order; symbols with no kept value omitted
    dropped: list[BiasDroppedOut]
    usage: ExtractUsageOut


class AiUsageOut(BaseModel):
    month: str  # YYYY-MM, Europe/Brussels
    cost_usd: Decimal
    calls: int
    failed_calls: int
    unpriced_calls: int
    input_tokens: int
    output_tokens: int
    configured: bool
    extraction_model: str
    key_state: KeyState


class AiKeyOut(BaseModel):
    """`ai` in GET /api/health and the POST /api/ai/check answer (docs/api.md M3)."""

    state: KeyState
    checked_at: UtcDatetime | None
