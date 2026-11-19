"""GET /api/journal-fields and GET /api/rules: the parsed YAML configs (docs/api.md)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.config_files import ConfigError, get_journal_fields, get_rules, get_violations
from app.config_files.journal_fields import RULE_VIOLATIONS_FIELD
from app.errors import config_error

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/journal-fields")
def journal_fields() -> dict[str, Any]:
    """The field definitions; `rule_violations` also carries `violation_types`
    (key -> auto | manual from violations.yaml, docs/api.md merge B shapes)."""
    try:
        data = get_journal_fields().to_api()
        types = {v.key: v.type for v in get_violations().violations}
    except ConfigError as exc:
        raise config_error(exc) from None
    fields = [
        f | {"violation_types": types} if f["key"] == RULE_VIOLATIONS_FIELD else f
        for f in data["fields"]
    ]
    return data | {"fields": fields}


@router.get("/rules")
def rules() -> dict[str, Any]:
    try:
        return get_rules().to_api()
    except ConfigError as exc:
        raise config_error(exc) from None
