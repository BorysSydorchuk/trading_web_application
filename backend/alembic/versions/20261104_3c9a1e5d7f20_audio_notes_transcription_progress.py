"""audio_notes: progress, error_code, started_at for the transcription queue (hand-written)

M3 voice notes (docs/api.md "M3 / Voice notes"): the worker claims the oldest pending note,
reports `progress` (0..1) while processing and stores a stable `error_code` on failure
(`transcription_error` keeps the English detail). A partial index serves the claim query.

Revision ID: 3c9a1e5d7f20
Revises: 7b0cc62b13f4
Create Date: 2026-11-04 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c9a1e5d7f20"
down_revision: str | Sequence[str] | None = "7b0cc62b13f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ERROR_CODES = (
    "'audio_unreadable', 'audio_missing', 'no_speech', 'model_unavailable', "
    "'timeout', 'transcription_failed'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("audio_notes", sa.Column("error_code", sa.String(length=30), nullable=True))
    op.add_column(
        "audio_notes", sa.Column("progress", sa.Numeric(precision=4, scale=3), nullable=True)
    )
    op.add_column("audio_notes", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_audio_notes_progress_range"), "audio_notes", "progress >= 0 AND progress <= 1"
    )
    op.create_check_constraint(
        op.f("ck_audio_notes_error_code_valid"), "audio_notes", f"error_code IN ({_ERROR_CODES})"
    )
    op.create_check_constraint(
        op.f("ck_audio_notes_error_code_only_failed"),
        "audio_notes",
        "error_code IS NULL OR transcription_status = 'failed'",
    )
    op.create_index(
        "ix_audio_notes_pending_created_at",
        "audio_notes",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("transcription_status = 'pending'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_audio_notes_pending_created_at",
        table_name="audio_notes",
        postgresql_where=sa.text("transcription_status = 'pending'"),
    )
    op.drop_constraint(op.f("ck_audio_notes_error_code_only_failed"), "audio_notes", type_="check")
    op.drop_constraint(op.f("ck_audio_notes_error_code_valid"), "audio_notes", type_="check")
    op.drop_constraint(op.f("ck_audio_notes_progress_range"), "audio_notes", type_="check")
    op.drop_column("audio_notes", "started_at")
    op.drop_column("audio_notes", "progress")
    op.drop_column("audio_notes", "error_code")
