"""Voice-note endpoints (docs/api.md "M3 / Voice notes"). The API never transcribes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.db import get_db
from app.domain.audio import (
    AUDIO_EXTENSIONS,
    MAX_AUDIO_BYTES,
    audio_extension,
    base_content_type,
    new_audio_relpath,
    resolve_audio_path,
)
from app.errors import UNSUPPORTED_MEDIA_TYPE, ApiError
from app.models import AudioNote
from app.schemas.audio import AudioNoteOut, to_audio_out
from app.services import audio_notes as service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])


def _declared_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _unsupported(content_type: str | None) -> ApiError:
    return ApiError(
        415,
        UNSUPPORTED_MEDIA_TYPE,
        "Unsupported audio type",
        {"content_type": content_type, "allowed": sorted(AUDIO_EXTENSIONS)},
    )


async def _receive_upload(
    request: Request,
    settings: Settings,
    check_owner: Callable[[], None],
    create_note: Callable[[str, str], AudioNote],
) -> AudioNoteOut:
    """Raw audio body -> file `<DATA_DIR>/audio/YYYY/MM/<uuid>.<ext>` -> `pending` note.

    Shared by trade and bias-note uploads: same checks, order and queue (DECISIONS M3-04).
    """
    content_type = request.headers.get("content-type")
    extension = audio_extension(content_type)
    mime_type = base_content_type(content_type)
    if extension is None or mime_type is None:
        raise _unsupported(content_type)
    declared = _declared_length(request)
    if declared is not None and declared > MAX_AUDIO_BYTES:
        raise service.too_large(MAX_AUDIO_BYTES)
    if declared == 0:
        raise service.empty_body()
    await run_in_threadpool(check_owner)
    relpath = new_audio_relpath(extension, datetime.now(UTC))
    target = settings.data_dir / relpath
    await service.save_upload(request.stream(), target, MAX_AUDIO_BYTES)
    note = await run_in_threadpool(create_note, relpath, mime_type)
    return to_audio_out(note)


@router.post("/trades/{trade_id}/audio", status_code=201, response_model=AudioNoteOut)
async def upload_trade_audio(
    trade_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AudioNoteOut:
    return await _receive_upload(
        request,
        settings,
        lambda: service.check_trade_accepts_audio(db, trade_id),
        lambda path, mime: service.create_trade_note(db, trade_id, path, mime),
    )


@router.post("/bias/notes/{bias_note_id}/audio", status_code=201, response_model=AudioNoteOut)
async def upload_bias_audio(
    bias_note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AudioNoteOut:
    """Voice for a bias note (docs/api.md M4): same rules as a trade's voice note."""
    return await _receive_upload(
        request,
        settings,
        lambda: service.check_bias_note_accepts_audio(db, bias_note_id),
        lambda path, mime: service.create_bias_note_audio(db, bias_note_id, path, mime),
    )


@router.get("/audio/{note_id}", response_model=AudioNoteOut)
def get_audio(note_id: int, db: Session = Depends(get_db)) -> AudioNoteOut:
    return to_audio_out(service.get_note(db, note_id))


@router.get("/audio/{note_id}/file", response_class=FileResponse)
def get_audio_file(
    note_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    note = service.get_note(db, note_id)
    path = resolve_audio_path(settings.data_dir, note.file_path)
    if path is None:
        logger.error(
            "Audio note %s: stored path %r is outside DATA_DIR/audio; refusing to serve it",
            note_id,
            note.file_path,
        )
        raise service.audio_missing(note_id)
    if not path.is_file():
        logger.warning("Audio note %s: file %s is missing", note_id, path)
        raise service.audio_missing(note_id)
    return FileResponse(path, media_type=note.mime_type)


@router.post("/audio/{note_id}/retry", response_model=AudioNoteOut)
def retry_audio(note_id: int, db: Session = Depends(get_db)) -> AudioNoteOut:
    return to_audio_out(service.retry_note(db, note_id))
