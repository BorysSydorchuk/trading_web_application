"""Bias (expectation) entries, PRD 6.6."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class BiasEntry(TimestampMixin, Base):
    __tablename__ = "bias_entries"
    __table_args__ = (
        UniqueConstraint("kind", "period_date", "symbol"),
        enum_check("kind", BiasKind, "kind_valid"),
        enum_check("direction", BiasDirection, "direction_valid"),
        enum_check("was_correct_source", BiasCorrectSource, "was_correct_source_valid"),
        CheckConstraint("confidence BETWEEN 1 AND 3", name="confidence_range"),
        CheckConstraint(
            "jsonb_typeof(ai_filled_fields) = 'array'", name="ai_filled_fields_is_array"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    # Brussels calendar date the bias is for: the trading day (pre_london/pre_ny),
    # the Monday of the week (weekly) or the 1st of the month (monthly).
    period_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(20))
    key_levels: Mapped[str | None] = mapped_column(Text)
    narrative: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    was_correct: Mapped[bool | None] = mapped_column(Boolean)
    was_correct_source: Mapped[str | None] = mapped_column(String(10))
    raw_text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    ai_filled_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=jsonb_default("[]"))

    chart_links: Mapped[list[ChartLink]] = relationship(
        back_populates="bias_entry", cascade="all, delete-orphan", passive_deletes=True
    )
    audio_notes: Mapped[list[AudioNote]] = relationship(
        back_populates="bias_entry", cascade="all, delete-orphan", passive_deletes=True
    )
