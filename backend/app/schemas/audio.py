"""Voice-note API schema (docs/api.md M3 "AudioNote")."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.models import AudioNote
from app.schemas.common import UtcDatetime


class AudioNoteOut(BaseModel):
    id: int
    trade_id: int | None
    bias_note_id: int | None
    status: str
    # A JSON number 0.0..1.0 (a fraction for a progress bar, not money).
    progress: float | None
    duration_seconds: Decimal | None
    mime_type: str
    transcript: str | None
    error_code: str | None
    created_at: UtcDatetime
    transcribed_at: UtcDatetime | None
    file_url: str


def audio_file_url(note_id: int) -> str:
    return f"/api/audio/{note_id}/file"


def to_audio_out(note: AudioNote) -> AudioNoteOut:
    return AudioNoteOut(
        id=note.id,
        trade_id=note.trade_id,
        bias_note_id=note.bias_note_id,
        status=note.transcription_status,
        progress=float(note.progress) if note.progress is not None else None,
        duration_seconds=note.duration_seconds,
        mime_type=note.mime_type,
        transcript=note.transcript,
        error_code=note.error_code,
        created_at=note.created_at,
        transcribed_at=note.transcribed_at,
        file_url=audio_file_url(note.id),
    )
