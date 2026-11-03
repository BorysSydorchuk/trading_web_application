"""`config/ai_pricing.yaml`: Anthropic prices per million tokens, per model id.

Strictly validated like the other config files (unknown keys, missing prices, negative or
non-numeric values are errors). Used for `cost_usd` in `logs/ai_usage.jsonl`.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)

AI_PRICING_FILE = "ai_pricing.yaml"
_MODEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelPrice(_Strict):
    """USD per million tokens."""

    input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)
    cache_write: Decimal = Field(ge=0)
    cache_read: Decimal = Field(ge=0)

    @field_validator("input", "output", "cache_write", "cache_read", mode="before")
    @classmethod
    def _exact(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("must be a number, not true/false")
        if isinstance(value, float):
            return str(value)  # 0.2 -> "0.2", not the binary float
        return value


class AiPricingConfig(_Strict):
    models: dict[str, ModelPrice] = Field(min_length=1)

    @field_validator("models")
    @classmethod
    def _model_ids(cls, value: dict[str, ModelPrice]) -> dict[str, ModelPrice]:
        bad = sorted(k for k in value if not _MODEL_ID_PATTERN.match(k))
        if bad:
            raise ValueError(f"invalid model ids: {', '.join(bad)}")
        return value

    def price(self, model: str) -> ModelPrice | None:
        return self.models.get(model)


def ai_pricing_path() -> Path:
    return config_dir() / AI_PRICING_FILE


def load_ai_pricing(path: Path | None = None) -> AiPricingConfig:
    """Parse and validate a pricing file (uncached). Raises ConfigError."""
    path = path or ai_pricing_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `models` mapping"])
    try:
        return AiPricingConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None


_cache: FileCache[AiPricingConfig] = FileCache(lambda: [ai_pricing_path()], load_ai_pricing)


def get_ai_pricing() -> AiPricingConfig:
    """Cached prices; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_ai_pricing_cache() -> None:
    _cache.clear()
