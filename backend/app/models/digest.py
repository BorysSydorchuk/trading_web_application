"""Weekly / monthly digests, PRD 6.7."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, enum_check, jsonb_default
from app.models.enums import DigestKind


class Digest(TimestampMixin, Base):
    __tablename__ = "digests"
    __table_args__ = (
        UniqueConstraint("kind", "period_start"),
        enum_check("kind", DigestKind, "kind_valid"),
        CheckConstraint("period_end >= period_start", name="period_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    period_start: Mapped[date] = mapped_column(Date)  # inclusive, Brussels calendar date
    period_end: Mapped[date] = mapped_column(Date)  # inclusive
    # Snapshot of computed metrics/breakdowns/deviations at generation time.
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=jsonb_default("{}"))
    generated_at: Mapped[datetime | None]
    what_worked: Mapped[str | None] = mapped_column(Text)
    what_to_fix: Mapped[str | None] = mapped_column(Text)
    focus_next: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
