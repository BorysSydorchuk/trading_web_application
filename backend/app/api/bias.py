"""Bias endpoints (docs/api.md M4): config, notes CRUD, entry result, status.

Voice upload for a note lives with the other audio endpoints (`app/api/audio.py`).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config_files import BiasConfig, ConfigError, get_bias_config
from app.db import get_db
from app.domain.bias_alignment import AlignmentSettings
from app.domain.sessions import DEFAULT_TZ, to_local
from app.errors import ApiError, config_error
from app.models.enums import BiasKind
from app.schemas.bias import (
    BiasEntryOut,
    BiasNoteInput,
    BiasNoteList,
    BiasNoteOut,
    BiasResultInput,
    BiasStatus,
)
from app.services import bias_notes as service
from app.services.bias_alignment import alignment_settings
from app.services.bias_status import bias_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bias", tags=["bias"])

DEFAULT_LIST_DAYS = 30  # today and the 29 days before, like the journal's "30 days"


def bias_config() -> BiasConfig:
    try:
        return get_bias_config()
    except ConfigError as exc:
        raise config_error(exc) from None


def write_context() -> tuple[BiasConfig, AlignmentSettings]:
    """bias.yaml + rules.yaml for a write; broken → 500 config_error before any change."""
    try:
        return get_bias_config(), alignment_settings()
    except ConfigError as exc:
        raise config_error(exc) from None


@router.get("/config")
def get_config() -> dict[str, Any]:
    return bias_config().to_api()


@router.get("/notes", response_model=BiasNoteList)
def list_notes(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    kind: list[BiasKind] = Query(default_factory=list),
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> BiasNoteList:
    config = bias_config()
    span = timedelta(days=DEFAULT_LIST_DAYS - 1)
    if date_to is None:
        date_to = date_from + span if date_from is not None else to_local(now, DEFAULT_TZ).date()
    if date_from is None:
        date_from = date_to - span
    if date_from > date_to:
        raise ApiError(
            422,
            "validation_error",
            "Request validation failed",
            {"fields": {"from": "must not be after `to`"}},
        )
    notes = service.list_notes(db, date_from, date_to, kind)
    return BiasNoteList(items=[service.note_out(n, config) for n in notes])


@router.get("/notes/by-period", response_model=BiasNoteOut)
def note_by_period(
    kind: BiasKind,
    day: date = Query(alias="date"),
    db: Session = Depends(get_db),
) -> BiasNoteOut:
    config = bias_config()
    note = service.find_note(db, kind, day)
    if note is None:
        raise ApiError(
            404, "not_found", "No bias note for this period", {"kind": kind.value, "date": str(day)}
        )
    return service.note_out(note, config)


@router.get("/notes/{note_id}", response_model=BiasNoteOut)
def get_note(note_id: int, db: Session = Depends(get_db)) -> BiasNoteOut:
    config = bias_config()
    return service.note_out(service.get_note(db, note_id), config)


def _reload(db: Session, note_id: int, config: BiasConfig) -> BiasNoteOut:
    db.expire_all()  # read back as stored (timestamps, link ids)
    return service.note_out(service.get_note(db, note_id), config)


@router.post("/notes", status_code=201, response_model=BiasNoteOut)
def create_note(body: BiasNoteInput, db: Session = Depends(get_db)) -> BiasNoteOut:
    config, settings = write_context()
    note = service.create_note(db, body, config, settings)
    db.commit()
    return _reload(db, note.id, config)


@router.put("/notes/{note_id}", response_model=BiasNoteOut)
def update_note(note_id: int, body: BiasNoteInput, db: Session = Depends(get_db)) -> BiasNoteOut:
    config, settings = write_context()
    note = service.get_note(db, note_id)
    service.update_note(db, note, body, config, settings)
    db.commit()
    return _reload(db, note_id, config)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db)) -> Response:
    _, settings = write_context()
    service.delete_note(db, service.get_note(db, note_id), settings)
    db.commit()
    return Response(status_code=204)


@router.patch("/entries/{entry_id}/result", response_model=BiasEntryOut)
def set_entry_result(
    entry_id: int, body: BiasResultInput, db: Session = Depends(get_db)
) -> BiasEntryOut:
    entry = service.set_result(db, entry_id, body.was_correct)
    db.commit()
    logger.info("Bias entry %s: was_correct set to %s", entry_id, body.was_correct)
    db.refresh(entry)
    return service.entry_out(entry)


@router.get("/status", response_model=BiasStatus, response_model_by_alias=True)
def get_status(db: Session = Depends(get_db), now: datetime = Depends(utc_now)) -> BiasStatus:
    return bias_status(db, bias_config(), now)
