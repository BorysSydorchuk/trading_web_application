"""Voice notes in the API (docs/api.md M3): store uploads, read, retry. Never transcribes."""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.errors import AUDIO_MISSING, AUDIO_NOT_FAILED, AUDIO_TOO_LARGE, ApiError
from app.models import AudioNote, Trade
from app.models.enums import TradeStatus, TranscriptionStatus

logger = logging.getLogger(__name__)

# Uploads are written in batches of this size (fewer thread hops than per network chunk).
WRITE_BATCH_BYTES = 1024 * 1024
PART_SUFFIX = ".part"


def too_large(max_bytes: int) -> ApiError:
    return ApiError(
        413, AUDIO_TOO_LARGE, f"Audio is larger than {max_bytes} bytes", {"max_bytes": max_bytes}
    )


def empty_body() -> ApiError:
    return ApiError(
        422, "validation_error", "Request validation failed", {"fields": {"body": "empty audio"}}
    )


def _trade_not_found(trade_id: int) -> ApiError:
    return ApiError(404, "not_found", "Trade not found", {"id": trade_id})


def check_trade_accepts_audio(db: Session, trade_id: int) -> None:
    """404 for an unknown trade, 409 `trade_open` for an open one; any closed status is fine."""
    row = db.execute(select(Trade.status, Trade.close_time).where(Trade.id == trade_id)).first()
    db.rollback()  # end the read transaction before the (slow) upload
    if row is None:
        raise _trade_not_found(trade_id)
    status, close_time = row
    if status == TradeStatus.OPEN.value or close_time is None:
        raise ApiError(
            409, "trade_open", "Voice notes can only be added to a closed trade", {"id": trade_id}
        )


async def save_upload(chunks: AsyncIterator[bytes], target: Path, max_bytes: int) -> int:
    """Stream the body to `target` (via `<target>.part`, renamed at the end); returns bytes.

    Stops reading as soon as the limit is passed (413). Partial files are removed; a
    complete upload is never deleted (the note row is inserted after the rename).
    """
    part = target.with_name(target.name + PART_SUFFIX)
    await run_in_threadpool(target.parent.mkdir, parents=True, exist_ok=True)
    handle = await run_in_threadpool(part.open, "xb")
    size = 0
    try:
        batch = bytearray()
        async for chunk in chunks:
            size += len(chunk)
            if size > max_bytes:
                raise too_large(max_bytes)
            batch += chunk
            if len(batch) >= WRITE_BATCH_BYTES:
                await run_in_threadpool(handle.write, bytes(batch))
                batch.clear()
        if size == 0:
            raise empty_body()
        await run_in_threadpool(handle.write, bytes(batch))
        await run_in_threadpool(handle.close)
        await run_in_threadpool(os.replace, part, target)
    except BaseException:
        handle.close()
        with contextlib.suppress(OSError):
            part.unlink()
        raise
    return size


def create_trade_note(db: Session, trade_id: int, file_path: str, mime_type: str) -> AudioNote:
    """Insert a `pending` note for a trade (the file is already on disk)."""
    if db.get(Trade, trade_id) is None:  # deleted during the upload
        logger.warning(
            "Trade %s vanished during an audio upload; file %s kept", trade_id, file_path
        )
        raise _trade_not_found(trade_id)
    note = AudioNote(trade_id=trade_id, file_path=file_path, mime_type=mime_type)
    db.add(note)
    db.commit()
    db.refresh(note)
    logger.info("Audio note %s stored for trade %s (%s)", note.id, trade_id, file_path)
    return note


def get_note(db: Session, note_id: int, *, for_update: bool = False) -> AudioNote:
    query = select(AudioNote).where(AudioNote.id == note_id)
    if for_update:
        query = query.with_for_update()
    note = db.scalars(query).one_or_none()
    if note is None:
        raise ApiError(404, "not_found", "Audio note not found", {"id": note_id})
    return note


def retry_note(db: Session, note_id: int) -> AudioNote:
    """`failed` -> `pending` with progress, error and transcript cleared; else 409."""
    note = get_note(db, note_id, for_update=True)
    if note.transcription_status != TranscriptionStatus.FAILED.value:
        status = note.transcription_status
        db.rollback()
        raise ApiError(
            409,
            AUDIO_NOT_FAILED,
            "Only a failed voice note can be retried",
            {"id": note_id, "status": status},
        )
    note.transcription_status = TranscriptionStatus.PENDING.value
    note.progress = None
    note.error_code = None
    note.transcription_error = None
    note.transcript = None
    note.started_at = None
    note.transcribed_at = None
    db.commit()
    db.refresh(note)
    logger.info("Audio note %s queued again for transcription", note_id)
    return note


def audio_missing(note_id: int) -> ApiError:
    return ApiError(404, AUDIO_MISSING, "Audio file is missing", {"id": note_id})
