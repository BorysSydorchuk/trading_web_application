"""GET /api/journal-fields and GET /api/rules: the parsed YAML configs (docs/api.md)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config_files import ConfigError, get_journal_fields, get_rules, get_violations
from app.config_files.journal_fields import RULE_VIOLATIONS_FIELD, JournalFieldsConfig
from app.db import get_db
from app.errors import config_error
from app.services.journal_options import effective_journal_fields

logger = logging.getLogger(__name__)

router = APIRouter()


def _current_config(db: Session) -> JournalFieldsConfig:
    """The owner's lists; with the DB down the form still gets the YAML defaults (logged)."""
    try:
        return effective_journal_fields(db)
    except SQLAlchemyError as exc:
        logger.error("Journal option lists unavailable, using YAML: %s", type(exc).__name__)
        db.rollback()
        return get_journal_fields()


@router.get("/journal-fields")
def journal_fields(db: Session = Depends(get_db)) -> dict[str, Any]:
    """The field definitions with the owner's current option lists; `rule_violations` also
    carries `violation_types` (key -> auto | manual from violations.yaml, docs/api.md)."""
    try:
        data = _current_config(db).to_api()
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
