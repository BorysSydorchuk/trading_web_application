"""`config/ai_models.yaml`: the Claude models the owner can choose (M8-13).

Strictly validated like the other config files: unknown keys, duplicate ids, a missing call
type or a negative / non-numeric cost are errors.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)

AI_MODELS_FILE = "ai_models.yaml"
CallType = Literal["trade_extraction", "bias_extraction", "digest_summary"]
CALL_TYPES: tuple[CallType, ...] = get_args(CallType)
_MODEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApproxCost(_Strict):
    """Approximate USD of one call, per call type."""

    trade_extraction: Decimal = Field(ge=0)
    bias_extraction: Decimal = Field(ge=0)
    digest_summary: Decimal = Field(ge=0)

    @field_validator("trade_extraction", "bias_extraction", "digest_summary", mode="before")
    @classmethod
    def _exact(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("must be a number, not true/false")
        return str(value) if isinstance(value, float) else value


class AiModel(_Strict):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    approx_usd: ApproxCost

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _MODEL_ID_PATTERN.match(value):
            raise ValueError(f"invalid model id {value!r}")
        return value


class AiModelsConfig(_Strict):
    models: tuple[AiModel, ...] = Field(min_length=1)

    @field_validator("models")
    @classmethod
    def _unique(cls, value: tuple[AiModel, ...]) -> tuple[AiModel, ...]:
        ids = [m.id for m in value]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate model ids: {', '.join(dupes)}")
        return value

    def get(self, model_id: str) -> AiModel | None:
        return next((m for m in self.models if m.id == model_id), None)


def ai_models_path() -> Path:
    return config_dir() / AI_MODELS_FILE


def load_ai_models(path: Path | None = None) -> AiModelsConfig:
    """Parse and validate the models file (uncached). Raises ConfigError."""
    path = path or ai_models_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `models` list"])
    try:
        return AiModelsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None


_cache: FileCache[AiModelsConfig] = FileCache(lambda: [ai_models_path()], load_ai_models)


def get_ai_models() -> AiModelsConfig:
    """Cached; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_ai_models_cache() -> None:
    _cache.clear()
