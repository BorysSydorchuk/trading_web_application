"""Bias notes CRUD (docs/api.md M4 "Bias notes and entries"). Flush-only except where noted.

Every create / update / delete recomputes the bias alignment of the affected trades in the
same transaction (`app.services.bias_alignment`); the endpoint commits.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config_files.bias import BiasConfig
from app.domain.bias_alignment import AlignmentSettings, normalize_period
from app.domain.chart_links import duplicate_link_indexes, preview_url
from app.errors import ApiError
from app.models import BiasEntry, BiasNote, ChartLink
from app.models.enums import BiasCorrectSource, BiasKind, ChartLinkKind
from app.schemas.audio import to_audio_out
from app.schemas.bias import BiasEntryInput, BiasEntryOut, BiasNoteInput, BiasNoteOut
from app.services.bias_alignment import NoteScope, recompute_for_scopes, scope_of

logger = logging.getLogger(__name__)

BIAS_NOTE_EXISTS = "bias_note_exists"
UNIQUE_NOTE_CONSTRAINT = "uq_bias_notes_kind_period_date"
# Same date: the later daily note first, then weekly, then monthly.
_KIND_ORDER = {
    BiasKind.PRE_NY.value: 0,
    BiasKind.PRE_LONDON.value: 1,
    BiasKind.WEEKLY.value: 2,
    BiasKind.MONTHLY.value: 3,
}


# --- read ---


def _note_query() -> Select[BiasNote]:
    return select(BiasNote).options(
        selectinload(BiasNote.entries).selectinload(BiasEntry.chart_links),
        selectinload(BiasNote.audio_notes),
    )


def get_note(db: Session, note_id: int) -> BiasNote:
    note = db.scalars(_note_query().where(BiasNote.id == note_id)).one_or_none()
    if note is None:
        raise ApiError(404, "not_found", "Bias note not found", {"id": note_id})
    return note


def find_note(db: Session, kind: BiasKind, day: date) -> BiasNote | None:
    period = normalize_period(kind, day)
    return db.scalars(
        _note_query().where(BiasNote.kind == kind.value, BiasNote.period_date == period)
    ).one_or_none()


def list_notes(
    db: Session, date_from: date, date_to: date, kinds: Sequence[BiasKind]
) -> Sequence[BiasNote]:
    """Notes with period_date in [from, to], newest period first."""
    query = _note_query().where(BiasNote.period_date >= date_from, BiasNote.period_date <= date_to)
    if kinds:
        query = query.where(BiasNote.kind.in_([k.value for k in kinds]))
    kind_rank = case(_KIND_ORDER, value=BiasNote.kind, else_=len(_KIND_ORDER))
    return db.scalars(
        query.order_by(BiasNote.period_date.desc(), kind_rank, BiasNote.id.desc())
    ).all()


def _symbol_rank(config: BiasConfig) -> dict[str, int]:
    return {name: i for i, name in enumerate(config.symbol_names)}


def entry_out(entry: BiasEntry) -> BiasEntryOut:
    links = sorted(entry.chart_links, key=lambda link: link.id)
    return BiasEntryOut.model_validate(
        {
            "id": entry.id,
            "symbol": entry.symbol,
            "direction": entry.direction,
            "key_levels": entry.key_levels,
            "narrative": entry.narrative,
            "confidence": entry.confidence,
            "chart_links": [
                {"id": c.id, "url": c.url, "kind": c.kind, "preview_url": preview_url(c.url)}
                for c in links
            ],
            "was_correct": entry.was_correct,
            "was_correct_source": entry.was_correct_source,
            "ai_filled_fields": entry.ai_filled_fields,
        }
    )


def note_out(note: BiasNote, config: BiasConfig) -> BiasNoteOut:
    """Entries in bias.yaml order (symbols no longer in the file last, by name)."""
    rank = _symbol_rank(config)
    entries = sorted(note.entries, key=lambda e: (rank.get(e.symbol, len(rank)), e.symbol))
    audio = sorted(note.audio_notes, key=lambda n: (n.created_at, n.id))
    return BiasNoteOut(
        id=note.id,
        kind=note.kind,
        period_date=note.period_date,
        raw_text=note.raw_text,
        entries=[entry_out(e) for e in entries],
        audio_notes=[to_audio_out(a) for a in audio],
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


# --- write ---


def _validation_error(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "validation_error", "Request validation failed", {"fields": fields})


def validate_entries(entries: Sequence[BiasEntryInput], config: BiasConfig) -> None:
    """422 `entries.<i>.symbol` (unknown / repeated) and `entries.<i>.chart_links.<j>.url`."""
    allowed = config.symbol_names
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if entry.symbol not in allowed:
            errors[f"entries.{i}.symbol"] = f"must be one of {', '.join(allowed)} (bias.yaml)"
        elif entry.symbol in seen:
            errors[f"entries.{i}.symbol"] = f"{entry.symbol} is listed twice"
        seen.add(entry.symbol)
        for j in duplicate_link_indexes([link.url for link in entry.chart_links]):
            errors[f"entries.{i}.chart_links.{j}.url"] = "duplicate link (same snapshot or chart)"
    if errors:
        raise _validation_error(errors)


def _conflict(existing_id: int) -> ApiError:
    return ApiError(
        409,
        BIAS_NOTE_EXISTS,
        "A bias note for this kind and period already exists",
        {"id": existing_id},
    )


def _check_free(db: Session, kind: BiasKind, period: date, own_id: int | None) -> None:
    existing = db.scalar(
        select(BiasNote.id).where(BiasNote.kind == kind.value, BiasNote.period_date == period)
    )
    if existing is not None and existing != own_id:
        raise _conflict(existing)


def _ai_filled(entry: BiasEntryInput) -> list[str]:
    """Listed fields that hold a value, each once, in the given order."""
    values = {
        "direction": entry.direction,
        "key_levels": entry.key_levels,
        "narrative": entry.narrative,
        "confidence": entry.confidence,
    }
    return list(dict.fromkeys(f for f in entry.ai_filled_fields if values[f] is not None))


def _apply_entry(row: BiasEntry, data: BiasEntryInput) -> None:
    if row.direction is not None and row.direction != data.direction:
        # A mark for the old direction says nothing about the new one.
        row.was_correct = None
        row.was_correct_source = None
    row.direction = data.direction
    row.key_levels = data.key_levels
    row.narrative = data.narrative
    row.confidence = data.confidence
    row.ai_filled_fields = _ai_filled(data)
    # Full replacement like the journal links (ids change on every save).
    row.chart_links = [
        ChartLink(url=link.url, kind=ChartLinkKind.BIAS.value) for link in data.chart_links
    ]


def _replace_entries(note: BiasNote, entries: Sequence[BiasEntryInput]) -> None:
    """By symbol: kept symbols are updated in place (id stays; was_correct stays unless the
    direction changed), new ones added, missing ones deleted."""
    current = {e.symbol: e for e in note.entries}
    rows: list[BiasEntry] = []
    for data in entries:
        row = current.get(data.symbol) or BiasEntry(symbol=data.symbol)
        _apply_entry(row, data)
        rows.append(row)
    note.entries = rows


def _flush_unique(db: Session, kind: BiasKind, period: date) -> None:
    """Flush; a concurrent insert of the same kind + period becomes the usual 409."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if UNIQUE_NOTE_CONSTRAINT not in str(exc.orig):
            raise
        existing = db.scalar(
            select(BiasNote.id).where(BiasNote.kind == kind.value, BiasNote.period_date == period)
        )
        raise _conflict(existing or 0) from None


def create_note(
    db: Session, data: BiasNoteInput, config: BiasConfig, settings: AlignmentSettings
) -> BiasNote:
    validate_entries(data.entries, config)
    kind = BiasKind(data.kind)
    period = normalize_period(kind, data.period_date)
    _check_free(db, kind, period, None)
    note = BiasNote(kind=kind.value, period_date=period, raw_text=data.raw_text)
    _replace_entries(note, data.entries)
    db.add(note)
    _flush_unique(db, kind, period)
    recompute_for_scopes(db, [scope_of(note)], settings)
    logger.info("Bias note %s created: %s %s, %s entries", note.id, kind, period, len(data.entries))
    return note


def update_note(
    db: Session,
    note: BiasNote,
    data: BiasNoteInput,
    config: BiasConfig,
    settings: AlignmentSettings,
) -> None:
    validate_entries(data.entries, config)
    kind = BiasKind(data.kind)
    period = normalize_period(kind, data.period_date)
    _check_free(db, kind, period, note.id)
    before: NoteScope = scope_of(note)
    note.kind = kind.value
    note.period_date = period
    note.raw_text = data.raw_text
    _replace_entries(note, data.entries)
    _flush_unique(db, kind, period)
    recompute_for_scopes(db, [before, scope_of(note)], settings)
    logger.info("Bias note %s updated: %s %s, %s entries", note.id, kind, period, len(data.entries))


def delete_note(db: Session, note: BiasNote, settings: AlignmentSettings) -> None:
    """Entries, links and audio rows cascade; audio files stay on disk (like M3)."""
    before = scope_of(note)
    note_id = note.id
    db.delete(note)
    db.flush()
    recompute_for_scopes(db, [before], settings)
    logger.info("Bias note %s deleted (%s %s)", note_id, before.kind, before.period_date)


def set_result(db: Session, entry_id: int, was_correct: bool | None) -> BiasEntry:
    """Borys's mark: true/false with source manual; null clears both."""
    entry = db.scalars(
        select(BiasEntry)
        .where(BiasEntry.id == entry_id)
        .options(selectinload(BiasEntry.chart_links))
    ).one_or_none()
    if entry is None:
        raise ApiError(404, "not_found", "Bias entry not found", {"id": entry_id})
    entry.was_correct = was_correct
    entry.was_correct_source = None if was_correct is None else BiasCorrectSource.MANUAL.value
    db.flush()
    return entry
