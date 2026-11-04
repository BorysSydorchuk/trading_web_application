"""When each journal field became required (docs/api.md M3 "New required fields").

`journal_field_requirements` has one row per field that is `required: true` in
config/journal_fields.yaml now; `app.services.journal_requirements` keeps it in sync.
`journal_requirements_state` is a single row (seeded by the migration) whose
`initial_fill_at` records that the one-time first fill (required_since = 1970) happened.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

STATE_ROW_ID = 1


class JournalFieldRequirement(Base):
    __tablename__ = "journal_field_requirements"

    key: Mapped[str] = mapped_column(String(63), primary_key=True)  # YAML field key
    required_since: Mapped[datetime]


class JournalRequirementsState(Base):
    __tablename__ = "journal_requirements_state"
    __table_args__ = (CheckConstraint(f"id = {STATE_ROW_ID}", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    # NULL until the first sync ever; never reset (a later empty table is not a first fill).
    initial_fill_at: Mapped[datetime | None]
