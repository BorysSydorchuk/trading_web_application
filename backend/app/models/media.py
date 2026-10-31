"""Chart links and audio notes, each owned by exactly one trade or bias entry."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_check
from app.models.enums import ChartLinkKind, TranscriptionStatus

if TYPE_CHECKING:
    from app.models.bias import BiasEntry
    from app.models.trade import Trade

# Exactly one owner: a trade XOR a bias entry.
_ONE_OWNER = "(trade_id IS NULL) <> (bias_entry_id IS NULL)"


class ChartLink(TimestampMixin, Base):
    __tablename__ = "chart_links"
    __table_args__ = (
        CheckConstraint(_ONE_OWNER, name="one_owner"),
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
        CheckConstraint(_ONE_OWNER, name="one_owner"),
        enum_check("transcription_status", TranscriptionStatus, "transcription_status_valid"),
        CheckConstraint("duration_seconds >= 0", name="duration_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    bias_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("bias_entries.id", ondelete="CASCADE"), index=True
    )
    # Relative to the data dir (e.g. `audio/2026/10/<uuid>.webm`); file survives failures.
    file_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    transcript: Mapped[str | None] = mapped_column(Text)
    transcription_status: Mapped[str] = mapped_column(
        String(20), index=True, server_default=TranscriptionStatus.PENDING.value
    )
    transcription_error: Mapped[str | None] = mapped_column(Text)
    transcribed_at: Mapped[datetime | None]

    trade: Mapped[Trade | None] = relationship(back_populates="audio_notes")
    bias_entry: Mapped[BiasEntry | None] = relationship(back_populates="audio_notes")
