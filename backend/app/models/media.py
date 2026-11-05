"""Chart links (owned by a trade or a bias entry) and audio notes (a trade or a bias note)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_check
from app.models.enums import ChartLinkKind, TranscriptionErrorCode, TranscriptionStatus

if TYPE_CHECKING:
    from app.models.bias import BiasEntry, BiasNote
    from app.models.trade import Trade

# Exactly one owner: a trade XOR a bias entry (links are per symbol) / a bias note (audio).
_LINK_ONE_OWNER = "(trade_id IS NULL) <> (bias_entry_id IS NULL)"
_AUDIO_ONE_OWNER = "(trade_id IS NULL) <> (bias_note_id IS NULL)"


class ChartLink(TimestampMixin, Base):
    __tablename__ = "chart_links"
    __table_args__ = (
        CheckConstraint(_LINK_ONE_OWNER, name="one_owner"),
        enum_check("kind", ChartLinkKind, "kind_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    bias_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("bias_entries.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))

    trade: Mapped[Trade | None] = relationship(back_populates="chart_links")
    bias_entry: Mapped[BiasEntry | None] = relationship(back_populates="chart_links")


class AudioNote(TimestampMixin, Base):
    __tablename__ = "audio_notes"
    __table_args__ = (
        CheckConstraint(_AUDIO_ONE_OWNER, name="one_owner"),
        enum_check("transcription_status", TranscriptionStatus, "transcription_status_valid"),
        CheckConstraint("duration_seconds >= 0", name="duration_non_negative"),
        CheckConstraint("progress >= 0 AND progress <= 1", name="progress_range"),
        enum_check("error_code", TranscriptionErrorCode, "error_code_valid"),
        CheckConstraint(
            "error_code IS NULL OR transcription_status = 'failed'", name="error_code_only_failed"
        ),
        # Worker claim: oldest pending note first (docs/api.md M3).
        Index(
            "ix_audio_notes_pending_created_at",
            "created_at",
            "id",
            postgresql_where=text("transcription_status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    bias_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("bias_notes.id", ondelete="CASCADE"), index=True
    )
    # Relative to the data dir (e.g. `audio/2026/10/<uuid>.webm`); file survives failures.
    file_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    transcript: Mapped[str | None] = mapped_column(Text)
    transcription_status: Mapped[str] = mapped_column(
        String(20), index=True, server_default=TranscriptionStatus.PENDING.value
    )
    # English detail for logs/debugging; never shown in the UI (the UI uses error_code).
    transcription_error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(30))
    # Transcribed audio seconds / duration while processing, 1 when done, else NULL.
    progress: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    started_at: Mapped[datetime | None]  # when the worker claimed the note
    transcribed_at: Mapped[datetime | None]

    trade: Mapped[Trade | None] = relationship(back_populates="audio_notes")
    bias_note: Mapped[BiasNote | None] = relationship(back_populates="audio_notes")
