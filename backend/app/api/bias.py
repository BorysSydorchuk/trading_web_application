"""Bias endpoints (docs/api.md M4). M4-03: `GET /api/bias/config`; notes come in M4-05."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.config_files import config_error
from app.config_files import ConfigError, get_bias_config

router = APIRouter(prefix="/bias", tags=["bias"])


@router.get("/config")
def bias_config() -> dict[str, Any]:
    try:
        return get_bias_config().to_api()
    except ConfigError as exc:
        raise config_error(exc) from None
