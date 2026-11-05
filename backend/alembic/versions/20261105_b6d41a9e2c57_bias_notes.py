"""bias_notes: one note per kind + period owns the audio and the per-symbol bias_entries

M4 (docs/api.md "Bias notes and entries", DECISIONS 2026-11-05): a bias note (kind,
period_date, raw_text) holds one bias entry per symbol and owns the audio notes.
- bias_entries: + bias_note_id (FK, CASCADE); kind/period_date/raw_text/transcript move to the
  note; UNIQUE(kind, period_date, symbol) -> UNIQUE(bias_note_id, symbol).
- audio_notes: bias_entry_id -> bias_note_id (FK bias_notes, CASCADE), owner XOR updated.
- chart_links keep bias_entry_id (links are per symbol).

Existing rows are migrated, not dropped: one note per distinct (kind, period_date), its
raw_text = the entries' raw_text and transcript texts (blank-line separated, by entry id);
audio of an entry moves to the entry's note. A weekly row not on a Monday or a monthly row
not on the 1st stops the upgrade with a clear error (fix the row first) instead of moving it.
Downgrade maps back (note raw_text onto every entry, audio to the note's first entry) and
refuses when a note has no entries (its text/audio would have no owner).

Revision ID: b6d41a9e2c57
Revises: 7916fe645fdc
Create Date: 2026-11-05 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d41a9e2c57"
down_revision: str | Sequence[str] | None = "7916fe645fdc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'pre_london', 'pre_ny', 'weekly', 'monthly'"
_WEEKLY_IS_MONDAY = "kind <> 'weekly' OR extract(isodow FROM period_date) = 1"
_MONTHLY_IS_FIRST = "kind <> 'monthly' OR extract(day FROM period_date) = 1"
_AUDIO_NOTE_OWNER = "(trade_id IS NULL) <> (bias_note_id IS NULL)"
_AUDIO_ENTRY_OWNER = "(trade_id IS NULL) <> (bias_entry_id IS NULL)"


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def _refuse_misaligned_periods() -> None:
    bad = (
        op.get_bind()
        .execute(
            sa.text(  # constants only, no user input
                "SELECT id, kind, period_date FROM bias_entries "  # noqa: S608
                f"WHERE NOT ({_WEEKLY_IS_MONDAY}) OR NOT ({_MONTHLY_IS_FIRST}) ORDER BY id"
            )
        )
        .all()
    )
    if bad:
        rows = ", ".join(f"id={r.id} {r.kind} {r.period_date}" for r in bad[:10])
        raise RuntimeError(
            "bias_notes migration stopped: weekly bias rows must be on a Monday and monthly "
            f"rows on the 1st of the month. Fix or delete these bias_entries rows: {rows}"
        )


def _create_bias_notes() -> None:
    op.create_table(
        "bias_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name=op.f("ck_bias_notes_kind_valid")),
        sa.CheckConstraint(_WEEKLY_IS_MONDAY, name=op.f("ck_bias_notes_weekly_is_monday")),
        sa.CheckConstraint(_MONTHLY_IS_FIRST, name=op.f("ck_bias_notes_monthly_is_first")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bias_notes")),
        sa.UniqueConstraint("kind", "period_date", name=op.f("uq_bias_notes_kind_period_date")),
    )


def _link_entries_to_notes() -> None:
    op.execute(
        """
        INSERT INTO bias_notes (kind, period_date, raw_text, created_at, updated_at)
        SELECT kind, period_date,
               string_agg(
                   NULLIF(concat_ws(E'\\n\\n', NULLIF(raw_text, ''), NULLIF(transcript, '')), ''),
                   E'\\n\\n' ORDER BY id
               ),
               min(created_at), max(updated_at)
        FROM bias_entries
        GROUP BY kind, period_date
        """
    )
    op.add_column("bias_entries", sa.Column("bias_note_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE bias_entries e SET bias_note_id = n.id
        FROM bias_notes n
        WHERE n.kind = e.kind AND n.period_date = e.period_date
        """
    )
    op.alter_column("bias_entries", "bias_note_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_bias_entries_bias_note_id_bias_notes"),
        "bias_entries",
        "bias_notes",
        ["bias_note_id"],
        ["id"],
        ondelete="CASCADE",
    )


def _move_audio_to_notes() -> None:
    op.add_column("audio_notes", sa.Column("bias_note_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE audio_notes a SET bias_note_id = e.bias_note_id
        FROM bias_entries e
        WHERE e.id = a.bias_entry_id
        """
    )
    op.drop_constraint(op.f("ck_audio_notes_one_owner"), "audio_notes", type_="check")
    op.drop_index(op.f("ix_audio_notes_bias_entry_id"), table_name="audio_notes")
    op.drop_constraint(
        op.f("fk_audio_notes_bias_entry_id_bias_entries"), "audio_notes", type_="foreignkey"
    )
    op.drop_column("audio_notes", "bias_entry_id")
    op.create_foreign_key(
        op.f("fk_audio_notes_bias_note_id_bias_notes"),
        "audio_notes",
        "bias_notes",
        ["bias_note_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_audio_notes_bias_note_id"), "audio_notes", ["bias_note_id"], unique=False
    )
    op.create_check_constraint(op.f("ck_audio_notes_one_owner"), "audio_notes", _AUDIO_NOTE_OWNER)


def upgrade() -> None:
    """Upgrade schema."""
    _refuse_misaligned_periods()
    _create_bias_notes()
    _link_entries_to_notes()
    _move_audio_to_notes()
    op.drop_constraint(
        op.f("uq_bias_entries_kind_period_date_symbol"), "bias_entries", type_="unique"
    )
    op.drop_index(op.f("ix_bias_entries_period_date"), table_name="bias_entries")
    op.drop_constraint(op.f("ck_bias_entries_kind_valid"), "bias_entries", type_="check")
    for column in ("kind", "period_date", "raw_text", "transcript"):
        op.drop_column("bias_entries", column)
    op.create_unique_constraint(
        op.f("uq_bias_entries_bias_note_id_symbol"), "bias_entries", ["bias_note_id", "symbol"]
    )


def _refuse_notes_without_entries() -> None:
    orphans = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT n.id FROM bias_notes n WHERE NOT EXISTS "
                "(SELECT 1 FROM bias_entries e WHERE e.bias_note_id = n.id) ORDER BY n.id"
            )
        )
        .scalars()
        .all()
    )
    if orphans:
        ids = ", ".join(str(i) for i in orphans[:10])
        raise RuntimeError(
            "bias_notes downgrade stopped: these bias notes have no entries, so their text and "
            f"audio would have no owner in the old schema. Add an entry or delete them: {ids}"
        )


def _restore_entry_columns() -> None:
    op.drop_constraint(op.f("uq_bias_entries_bias_note_id_symbol"), "bias_entries", type_="unique")
    op.add_column("bias_entries", sa.Column("kind", sa.String(length=20), nullable=True))
    op.add_column("bias_entries", sa.Column("period_date", sa.Date(), nullable=True))
    op.add_column("bias_entries", sa.Column("raw_text", sa.Text(), nullable=True))
    op.add_column("bias_entries", sa.Column("transcript", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE bias_entries e SET kind = n.kind, period_date = n.period_date, raw_text = n.raw_text
        FROM bias_notes n
        WHERE n.id = e.bias_note_id
        """
    )
    op.alter_column("bias_entries", "kind", nullable=False)
    op.alter_column("bias_entries", "period_date", nullable=False)
    op.create_check_constraint(
        op.f("ck_bias_entries_kind_valid"), "bias_entries", f"kind IN ({_KINDS})"
    )
    op.create_index(
        op.f("ix_bias_entries_period_date"), "bias_entries", ["period_date"], unique=False
    )
    op.create_unique_constraint(
        op.f("uq_bias_entries_kind_period_date_symbol"),
        "bias_entries",
        ["kind", "period_date", "symbol"],
    )


def _move_audio_to_entries() -> None:
    op.add_column("audio_notes", sa.Column("bias_entry_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE audio_notes a SET bias_entry_id = first_entry.id
        FROM (SELECT bias_note_id, min(id) AS id FROM bias_entries GROUP BY bias_note_id)
             AS first_entry
        WHERE first_entry.bias_note_id = a.bias_note_id
        """
    )
    op.drop_constraint(op.f("ck_audio_notes_one_owner"), "audio_notes", type_="check")
    op.drop_index(op.f("ix_audio_notes_bias_note_id"), table_name="audio_notes")
    op.drop_constraint(
        op.f("fk_audio_notes_bias_note_id_bias_notes"), "audio_notes", type_="foreignkey"
    )
    op.drop_column("audio_notes", "bias_note_id")
    op.create_foreign_key(
        op.f("fk_audio_notes_bias_entry_id_bias_entries"),
        "audio_notes",
        "bias_entries",
        ["bias_entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_audio_notes_bias_entry_id"), "audio_notes", ["bias_entry_id"], unique=False
    )
    op.create_check_constraint(op.f("ck_audio_notes_one_owner"), "audio_notes", _AUDIO_ENTRY_OWNER)


def downgrade() -> None:
    """Downgrade schema."""
    _refuse_notes_without_entries()
    _restore_entry_columns()
    _move_audio_to_entries()
    op.drop_constraint(
        op.f("fk_bias_entries_bias_note_id_bias_notes"), "bias_entries", type_="foreignkey"
    )
    op.drop_column("bias_entries", "bias_note_id")
    op.drop_table("bias_notes")
