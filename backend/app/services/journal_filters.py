"""`GET /api/trades?journal=<key>:<value>` conditions (M8-04..08 merge B, docs/api.md
"Merge B exact shapes").

Same key = any of the values; different keys = all of them; `null` = empty (a show_if
field: shown and empty). Allowed keys:
non-legacy enum / multi_enum / bool fields of config/journal_fields.yaml. Multi fields match
when the array (or the violation rows, for `rule_violations`) contains the value. Every
condition is a parameterized SQLAlchemy expression.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, exists, false, func, or_, true

from app.config_files import JournalField, JournalFieldsConfig
from app.config_files.journal_fields import RULE_VIOLATIONS_FIELD
from app.models import RuleViolation, Trade
from app.services.journal_requirements import shown_sql

NULL_VALUE = "null"
_FILTER_TYPES = frozenset({"enum", "multi_enum", "bool"})
_BOOL_VALUES = {"true": True, "false": False}


class JournalFilterError(ValueError):
    """A `journal=` value that cannot be used; the message names the key / value."""


@dataclass(frozen=True)
class _Term:
    field: JournalField
    value: str  # option value, "true"/"false" for bool, or NULL_VALUE


def _parse(raw: str, config: JournalFieldsConfig) -> _Term:
    key, sep, value = raw.partition(":")
    if not sep or not key or not value:
        raise JournalFilterError(f"{raw!r}: expected <key>:<value>")
    field = config.get(key)
    if field is None or field.legacy or field.type not in _FILTER_TYPES:
        raise JournalFilterError(f"{key!r} is not a journal field that can be filtered")
    if value == NULL_VALUE:
        return _Term(field, value)
    allowed = _BOOL_VALUES.keys() if field.type == "bool" else field.option_values()
    if value not in allowed:
        raise JournalFilterError(f"{value!r} is not a value of {key!r}")
    return _Term(field, value)


def _violation_condition(value: str) -> ColumnElement[bool]:
    any_row = RuleViolation.trade_id == Trade.id
    if value == NULL_VALUE:
        return ~exists().where(any_row)
    return exists().where(any_row, RuleViolation.rule_key == value)


def _extra_condition(term: _Term) -> ColumnElement[bool]:
    """trades.extra JSONB: missing key / JSON null / `[]` = empty; multi = array contains."""
    item = Trade.extra[term.field.key]
    condition: ColumnElement[bool]
    if term.value == NULL_VALUE:
        condition = item.astext.is_(None)
        if term.field.type == "multi_enum":
            condition = or_(condition, item.astext == "[]")
    elif term.field.type == "multi_enum":
        condition = item.contains([term.value])
    else:
        condition = item.astext == term.value
    return condition


def _column_condition(term: _Term) -> ColumnElement[bool]:
    column = Trade.__table__.columns[term.field.key]
    if term.value == NULL_VALUE:
        if term.field.type == "multi_enum":
            return or_(column.is_(None), func.cardinality(column) == 0)
        return column.is_(None)
    if term.field.type == "multi_enum":
        return column.contains([term.value])
    if term.field.type == "bool":
        return column.is_(true()) if _BOOL_VALUES[term.value] else column.is_(false())
    return column == term.value


def _value_condition(term: _Term) -> ColumnElement[bool]:
    if term.field.key == RULE_VIOLATIONS_FIELD:
        return _violation_condition(term.value)
    if term.field.storage == "extra":
        return _extra_condition(term)
    return _column_condition(term)


def _condition(term: _Term, config: JournalFieldsConfig) -> ColumnElement[bool]:
    """`null` of a show_if field = shown (parent includes the option) and empty: a trade
    the field does not apply to is not «empty» (review 2026-11-19)."""
    condition = _value_condition(term)
    if term.value == NULL_VALUE and term.field.show_if is not None:
        return and_(shown_sql(config, term.field), condition)
    return condition


def journal_conditions(
    raw_values: Sequence[str], config: JournalFieldsConfig
) -> list[ColumnElement[bool]]:
    """One condition per key (OR of its values). Raises JournalFilterError."""
    by_key: dict[str, list[_Term]] = {}
    for raw in raw_values:
        term = _parse(raw, config)
        by_key.setdefault(term.field.key, []).append(term)
    return [or_(*(_condition(t, config) for t in terms)) for terms in by_key.values()]
