"""Owner-edited option lists of journal choice fields (Settings «Емоції», 2026-11-22).

`value` is the stable key stored on trades and never changes; `label`, `position`, `hidden`
and `synonyms` are editable. A field without rows uses its defaults from journal_fields.yaml.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, jsonb_default


class JournalFieldOption(TimestampMixin, Base):
    __tablename__ = "journal_field_options"
    __table_args__ = (
        UniqueConstraint("field_key", "value"),
        CheckConstraint("jsonb_typeof(synonyms) = 'array'", name="synonyms_is_array"),
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field_key: Mapped[str] = mapped_column(String(63), nullable=False)
    value: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    synonyms: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("[]")
    )
