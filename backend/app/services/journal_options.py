"""Editable option lists of journal choice fields, layered over journal_fields.yaml.

`effective_journal_fields` is the config every reader uses: a managed field with DB rows gets
those options (hidden = `deprecated`, so old trades, filters and statistics keep the value and
new choices and the AI do not offer it). Reads never write: the YAML defaults are copied to
the DB on the first edit of a list. To manage another choice field, add its key to
MANAGED_FIELDS (docs/BACKLOG.md).
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config_files import ConfigError, get_journal_fields
from app.config_files.journal_fields import JournalField, JournalFieldsConfig, JournalOption
from app.errors import ApiError, config_error
from app.models import JournalFieldOption, Trade
from app.services.journal_requirements import option_sql

MANAGED_FIELDS: tuple[str, ...] = ("emotion_before", "emotion_after")


@dataclass(frozen=True)
class OptionView:
    value: str
    label: str
    hidden: bool
    synonyms: tuple[str, ...]
    used_count: int


def _rows(db: Session, field_key: str) -> list[JournalFieldOption]:
    query = (
        select(JournalFieldOption)
        .where(JournalFieldOption.field_key == field_key)
        .order_by(JournalFieldOption.position, JournalFieldOption.id)
    )
    return list(db.scalars(query))


def _to_option(row: JournalFieldOption) -> JournalOption:
    return JournalOption(
        value=row.value, label=row.label, deprecated=row.hidden, synonyms=tuple(row.synonyms)
    )


def effective_journal_fields(
    db: Session, config: JournalFieldsConfig | None = None
) -> JournalFieldsConfig:
    """The YAML config with the current DB lists of the managed fields."""
    base = config if config is not None else get_journal_fields()
    query = (
        select(JournalFieldOption)
        .where(JournalFieldOption.field_key.in_(MANAGED_FIELDS))
        .order_by(JournalFieldOption.position, JournalFieldOption.id)
    )
    by_field: dict[str, list[JournalOption]] = {}
    for row in db.scalars(query):
        by_field.setdefault(row.field_key, []).append(_to_option(row))
    if not by_field:
        return base
    fields = tuple(
        f.model_copy(update={"options": tuple(by_field[f.key])}) if f.key in by_field else f
        for f in base.fields
    )
    return base.model_copy(update={"fields": fields})


def _field(field_key: str) -> JournalField:
    if field_key not in MANAGED_FIELDS:
        raise ApiError(404, "not_found", "This field has no editable list", {"field": field_key})
    try:
        field = get_journal_fields().get(field_key)
    except ConfigError as exc:
        raise config_error(exc) from None
    if field is None:
        raise ApiError(404, "not_found", "Unknown journal field", {"field": field_key})
    return field


def _seeded_rows(db: Session, field: JournalField) -> list[JournalFieldOption]:
    """The field's rows; the first edit copies the YAML defaults into the DB. Every edit of a
    list holds its lock until commit/rollback, so concurrent edits cannot seed it twice."""
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"journal_options:{field.key}"))))
    rows = _rows(db, field.key)
    if rows:
        return rows
    rows = [
        JournalFieldOption(
            field_key=field.key,
            value=o.value,
            label=o.label,
            position=i,
            hidden=o.deprecated,
            synonyms=list(o.synonyms),
        )
        for i, o in enumerate(field.options)
    ]
    db.add_all(rows)
    db.flush()
    return rows


def _used_count(db: Session, field: JournalField, value: str) -> int:
    query = select(func.count()).select_from(Trade).where(option_sql(field, value))
    return db.scalar(query) or 0


def list_options(db: Session, field_key: str) -> list[OptionView]:
    field = _field(field_key)
    rows = _rows(db, field_key)
    options = [_to_option(r) for r in rows] if rows else list(field.options)
    return [
        OptionView(o.value, o.label, o.deprecated, o.synonyms, _used_count(db, field, o.value))
        for o in options
    ]


def _view(db: Session, field: JournalField, row: JournalFieldOption) -> OptionView:
    return OptionView(
        row.value, row.label, row.hidden, tuple(row.synonyms), _used_count(db, field, row.value)
    )


def _check_label_free(
    rows: Sequence[JournalFieldOption], label: str, own_value: str | None = None
) -> None:
    wanted = label.casefold()
    if any(r.value != own_value and r.label.casefold() == wanted for r in rows):
        raise ApiError(409, "duplicate_label", "This name is already in the list", {"label": label})


def _find(rows: Sequence[JournalFieldOption], value: str) -> JournalFieldOption:
    row = next((r for r in rows if r.value == value), None)
    if row is None:
        raise ApiError(404, "not_found", "Unknown option", {"value": value})
    return row


def add_option(db: Session, field_key: str, label: str, synonyms: Sequence[str]) -> OptionView:
    field = _field(field_key)
    rows = _seeded_rows(db, field)
    _check_label_free(rows, label)
    row = JournalFieldOption(
        field_key=field_key,
        value=f"opt_{secrets.token_hex(4)}",
        label=label,
        position=max((r.position for r in rows), default=-1) + 1,
        synonyms=list(synonyms),
    )
    db.add(row)
    db.commit()
    return _view(db, field, row)


def update_option(
    db: Session,
    field_key: str,
    value: str,
    *,
    label: str | None = None,
    hidden: bool | None = None,
    synonyms: Sequence[str] | None = None,
) -> OptionView:
    """Label, visibility and synonyms; the stored `value` never changes."""
    field = _field(field_key)
    rows = _seeded_rows(db, field)
    row = _find(rows, value)
    if label is not None:
        _check_label_free(rows, label, own_value=value)
        row.label = label
    hides_it = hidden is True and not row.hidden
    if hides_it and not any(not r.hidden for r in rows if r.value != value):
        db.rollback()
        raise ApiError(409, "last_visible_option", "At least one option must stay visible")
    if hidden is not None:
        row.hidden = hidden
    if synonyms is not None:
        row.synonyms = list(synonyms)
    db.commit()
    return _view(db, field, row)


def reorder_options(db: Session, field_key: str, values: Sequence[str]) -> list[OptionView]:
    field = _field(field_key)
    rows = _seeded_rows(db, field)
    if len(values) != len(rows) or {r.value for r in rows} != set(values):
        db.rollback()
        raise ApiError(422, "validation_error", "The order must list every option exactly once")
    position = {value: i for i, value in enumerate(values)}
    for row in rows:
        row.position = position[row.value]
    db.commit()
    return list_options(db, field_key)


def delete_option(db: Session, field_key: str, value: str) -> None:
    """Only an option no trade uses; a used one can be hidden instead."""
    field = _field(field_key)
    rows = _seeded_rows(db, field)
    row = _find(rows, value)
    used = _used_count(db, field, value)
    if used:
        db.rollback()
        raise ApiError(409, "option_in_use", "Used by trades: hide it instead", {"used": used})
    if not row.hidden and not any(not r.hidden for r in rows if r.value != value):
        db.rollback()
        raise ApiError(409, "last_visible_option", "At least one option must stay visible")
    db.delete(row)
    db.commit()
