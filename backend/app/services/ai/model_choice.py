"""Which Claude model a call uses (M8-13; docs/api.md "M8-13").

Per call type: a one-off model from the request, else the owner's default from Settings
(``<DATA_DIR>/ai_models.json``), else the model from ``.env`` (ANTHROPIC_MODEL_EXTRACTION
for trade and bias extraction, ANTHROPIC_MODEL_SUMMARY for the digest summary), i.e.
nothing changes until the owner chooses. Every id must be listed in config/ai_models.yaml.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.config_files.ai_models import CALL_TYPES, AiModelsConfig, CallType
from app.config_files.loader import ConfigError
from app.errors import ApiError, config_error
from app.services.ai.extraction import ExtractionSettings

logger = logging.getLogger(__name__)

CHOICE_FILE = "ai_models.json"


def env_default(call_type: CallType, settings: Settings) -> str:
    if call_type == "digest_summary":
        return settings.anthropic_model_summary
    return settings.anthropic_model_extraction


def _read(data_dir: Path) -> dict[str, str]:
    try:
        raw = json.loads((data_dir / CHOICE_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("AI model choice not readable (%s); .env models are used", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in CALL_TYPES and isinstance(v, str)}


def defaults(settings: Settings, models: AiModelsConfig) -> dict[CallType, str]:
    """Effective default per call type (a stored id no longer in the list falls back)."""
    chosen = _read(settings.data_dir)
    result: dict[CallType, str] = {}
    for call_type in CALL_TYPES:
        stored = chosen.get(call_type)
        result[call_type] = (
            stored
            if stored is not None and models.get(stored) is not None
            else env_default(call_type, settings)
        )
    return result


def unknown_model(model: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        "Request validation failed",
        {"fields": {"model": f"unknown model {model!r} (config/ai_models.yaml)"}},
    )


def save_defaults(
    settings: Settings, models: AiModelsConfig, changes: Mapping[CallType, str]
) -> dict[CallType, str]:
    """Store the owner's defaults (422 for an id not in the list); returns the effective ones."""
    if not changes:
        return defaults(settings, models)
    for model in changes.values():
        if models.get(model) is None:
            raise unknown_model(model)
    merged = _read(settings.data_dir) | dict(changes)
    path = settings.data_dir / CHOICE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="ai_models", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(merged, ensure_ascii=False))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    logger.info("AI model defaults changed: %s", dict(changes))
    return defaults(settings, models)


def one_off_settings(settings: ExtractionSettings, requested: str | None) -> ExtractionSettings:
    """A model the owner picked for this call is never silently replaced by the fallback."""
    return settings if requested is None else replace(settings, fallback_model=None)


def resolve(
    call_type: CallType,
    requested: str | None,
    settings: Settings,
    load_models: Callable[[], AiModelsConfig],
) -> str:
    """The model for one call: the requested one (422 if not listed) or the default.

    A missing or broken config/ai_models.yaml only matters for a requested model (the
    ConfigError is raised); without one the call falls back to the .env model (logged).
    """
    if requested is not None:
        try:
            listed = load_models().get(requested) is not None
        except ConfigError as exc:
            raise config_error(exc) from None
        if not listed:
            raise unknown_model(requested)
        return requested
    try:
        models = load_models()
    except ConfigError as exc:
        logger.warning("AI models list unusable (%s); the .env model is used", exc)
        return env_default(call_type, settings)
    return defaults(settings, models)[call_type]
