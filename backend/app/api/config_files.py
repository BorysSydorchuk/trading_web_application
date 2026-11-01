"""GET /api/journal-fields and GET /api/rules: the parsed YAML configs (docs/api.md)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.config_files import ConfigError, get_journal_fields, get_rules
from app.errors import ApiError

logger = logging.getLogger(__name__)

router = APIRouter()


def config_error(exc: ConfigError) -> ApiError:
    logger.error("Config error: %s", exc)
    return ApiError(
        500,
        "config_error",
        str(exc),
        {"file": exc.path.name, "problems": exc.problems},
    )


@router.get("/journal-fields")
def journal_fields() -> dict[str, Any]:
    try:
        return get_journal_fields().to_api()
    except ConfigError as exc:
        raise config_error(exc) from None


@router.get("/rules")
def rules() -> dict[str, Any]:
    try:
        return get_rules().to_api()
    except ConfigError as exc:
        raise config_error(exc) from None
