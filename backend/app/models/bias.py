"""Bias (expectation) notes and their per-symbol entries, PRD 6.6 (docs/api.md M4).

A `BiasNote` is one input (text and/or voice) for one kind + period; it owns the audio notes
and holds one `BiasEntry` per symbol. Chart links stay per entry (they show one symbol).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_check, jsonb_default
from app.models.enums import BiasCorrectSource, BiasDirection, BiasKind

if TYPE_CHECKING:
    from app.models.media import AudioNote, ChartLink


class BiasNote(TimestampMixin, Base):
    __tablename__ = "bias_notes"
    __table_args__ = (
        # Also serves the alignment lookup (kind, period_date).
        UniqueConstraint("kind", "period_date"),
        enum_check("kind", BiasKind, "kind_valid"),
        CheckConstraint(
            "kind <> 'weekly' OR extract(isodow FROM period_date) = 1", name="weekly_is_monday"
        ),
        CheckConstraint(
            "kind <> 'monthly' OR extract(day FROM period_date) = 1", name="monthly_is_first"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    # Brussels calendar date the bias is for: the trading day (pre_london/pre_ny),
    # the Monday of the week (weekly) or the 1st of the month (monthly).
    # Indexed for date-range listing across kinds (the unique is kind-first).
    period_date: Mapped[date] = mapped_column(Date, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text)

    entries: Mapped[list[BiasEntry]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BiasEntry.id",
    )
    audio_notes: Mapped[list[AudioNote]] = relationship(
        back_populates="bias_note",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AudioNote.id",
    )


class BiasEntry(TimestampMixin, Base):
    __tablename__ = "bias_entries"
    __table_args__ = (
        # Also serves the per-symbol lookup inside a note.
        UniqueConstraint("bias_note_id", "symbol"),
        enum_check("direction", BiasDirection, "direction_valid"),
        enum_check("was_correct_source", BiasCorrectSource, "was_correct_source_valid"),
        CheckConstraint("confidence BETWEEN 1 AND 3", name="confidence_range"),
        CheckConstraint(
            "jsonb_typeof(ai_filled_fields) = 'array'", name="ai_filled_fields_is_array"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bias_note_id: Mapped[int] = mapped_column(ForeignKey("bias_notes.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(20))
    key_levels: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    was_correct: Mapped[bool | None] = mapped_column(Boolean)
    was_correct_source: Mapped[str | None] = mapped_column(String(10))
    ai_filled_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=jsonb_default("[]"))

    note: Mapped[BiasNote] = relationship(back_populates="entries")
    chart_links: Mapped[list[ChartLink]] = relationship(
        back_populates="bias_entry", cascade="all, delete-orphan", passive_deletes=True
    )
