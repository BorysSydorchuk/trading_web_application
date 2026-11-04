"""Journal logic driven by `config/journal_fields.yaml` (PRD 6.4, docs/api.md M2). Pure.

No DB or HTTP here, so the journal save (PUT /api/trades/{id}/journal) and the AI
extraction (M2-04: schema + guards) share one implementation of keys, types and the
"what blocks complete" rule. Nothing in this module names a concrete journal field
except the two relation fields (`rule_violations`, `chart_links`) the YAML loader knows.

Terms (docs/api.md): a "YAML field" is a field `key`; a "YAML key" is a field `key` or a
`text_key`. Each YAML key is described by one `JournalKey`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.config_files.journal_fields import (
    RELATION_FIELDS,
    FieldType,
    JournalField,
    JournalFieldsConfig,
    Storage,
)

TEXT_MAX_LENGTH = 5000
OTHER_OPTION = "other"
RULE_VIOLATIONS_KEY = "rule_violations"
# Types the user never writes through `fields`: computed (auto) or saved separately (links).
NOT_WRITABLE_TYPES: frozenset[FieldType] = frozenset({"auto", "links"})

IssueCode = Literal[
    "unknown_key",
    "not_writable",
    "invalid_type",
    "invalid_option",
    "deprecated_option",
    "duplicate_option",
    "out_of_range",
    "too_long",
]


@dataclass(frozen=True)
class FieldIssue:
    """Why a value was rejected. `code` is stable (M2-04 maps it to guard reasons)."""

    code: IssueCode
    message: str


class InvalidJournalValue(ValueError):  # noqa: N818 - reads as "raise InvalidJournalValue"
    def __init__(self, issue: FieldIssue) -> None:
        super().__init__(issue.message)
        self.issue = issue


@dataclass(frozen=True)
class JournalKey:
    """One YAML key: a field itself, or the `text_key` companion of an option field."""

    key: str
    field: JournalField
    is_text_key: bool = False

    @property
    def type(self) -> FieldType:
        return "text" if self.is_text_key else self.field.type

    @property
    def storage(self) -> Storage:
        return self.field.storage

    @property
    def is_relation(self) -> bool:
        """Stored in a child table (rule_violations, chart_links), not a column or extra."""
        return not self.is_text_key and self.field.key in RELATION_FIELDS

    @property
    def other_only(self) -> bool:
        """Text that belongs to the parent's `other` option only (`allow_other_text`)."""
        return self.is_text_key and self.field.allow_other_text

    @property
    def writable(self) -> bool:
        return self.type not in NOT_WRITABLE_TYPES

    @property
    def ai_fillable(self) -> bool:
        return self.writable and self.key != RULE_VIOLATIONS_KEY


@dataclass(frozen=True)
class JournalValidation:
    values: dict[str, Any]  # every writable YAML key → normalised value or None
    errors: dict[str, FieldIssue]  # input key → issue


def journal_keys(config: JournalFieldsConfig) -> tuple[JournalKey, ...]:
    """Every YAML key in YAML order; a `text_key` follows its field."""
    keys: list[JournalKey] = []
    for field in config.fields:
        keys.append(JournalKey(field.key, field))
        if field.text_key is not None:
            keys.append(JournalKey(field.text_key, field, is_text_key=True))
    return tuple(keys)


def writable_keys(config: JournalFieldsConfig) -> tuple[JournalKey, ...]:
    """Keys accepted in `PUT .../journal` `fields` (all but `auto` and `links`)."""
    return tuple(k for k in journal_keys(config) if k.writable)


def ai_fillable_keys(config: JournalFieldsConfig) -> tuple[JournalKey, ...]:
    """Keys the AI extraction may fill (docs/api.md "AI extraction"): writable keys
    except `rule_violations`. Entry point for the M2-04 extraction schema builder."""
    return tuple(k for k in journal_keys(config) if k.ai_fillable)


# --- value normalisation ---


def _issue(code: IssueCode, message: str) -> InvalidJournalValue:
    return InvalidJournalValue(FieldIssue(code, message))


def _check_option(field: JournalField, value: Any, current: Iterable[Any]) -> str:
    if not isinstance(value, str):
        raise _issue("invalid_type", "must be an option value (string)")
    option = next((o for o in field.options if o.value == value), None)
    if option is None:
        allowed = ", ".join(field.option_values(include_deprecated=False))
        raise _issue("invalid_option", f"unknown option {value!r} (allowed: {allowed})")
    if option.deprecated and value not in current:
        raise _issue("deprecated_option", f"option {value!r} is deprecated")
    return value


def _norm_multi(field: JournalField, value: Any, current: Any) -> list[str] | None:
    if not isinstance(value, list):
        raise _issue("invalid_type", "must be an array of option values")
    stored = current if isinstance(current, list) else []
    items = [_check_option(field, item, stored) for item in value]
    if len(set(items)) != len(items):
        raise _issue("duplicate_option", "duplicate option values")
    return items or None


def _norm_int(field: JournalField, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _issue("invalid_type", "must be an integer")
    if (field.min is not None and value < field.min) or (
        field.max is not None and value > field.max
    ):
        raise _issue("out_of_range", f"must be between {field.min} and {field.max}")
    return value


def _norm_text(value: Any) -> str | None:
    if not isinstance(value, str):
        raise _issue("invalid_type", "must be a string")
    text = value.strip()
    if len(text) > TEXT_MAX_LENGTH:
        raise _issue("too_long", f"must be at most {TEXT_MAX_LENGTH} characters")
    return text or None


def normalise_value(spec: JournalKey, value: Any, current: Any = None) -> Any:
    """Validated, normalised value for one key; None clears it. Raises InvalidJournalValue.

    `current` is the value stored now: a deprecated option is accepted only if it is
    already stored (PRD 6.4: old trades keep their values).
    """
    if value is None:
        return None
    match spec.type:
        case "enum":
            return _check_option(spec.field, value, (current,))
        case "multi_enum":
            return _norm_multi(spec.field, value, current)
        case "bool":
            if not isinstance(value, bool):
                raise _issue("invalid_type", "must be true or false")
            return value
        case "int":
            return _norm_int(spec.field, value)
        case "text":
            return _norm_text(value)
    raise _issue("not_writable", f"{spec.type} fields are not written through `fields`")


def _key_issue(key: str, specs: Mapping[str, JournalKey]) -> FieldIssue | None:
    spec = specs.get(key)
    if spec is None:
        return FieldIssue("unknown_key", "unknown journal field")
    if spec.type == "links":
        return FieldIssue("not_writable", "chart links are saved in the top-level chart_links")
    if not spec.writable:
        return FieldIssue("not_writable", "computed by the app, not writable")
    return None


def validate_fields(
    config: JournalFieldsConfig, fields: Mapping[str, Any], current: Mapping[str, Any]
) -> JournalValidation:
    """Full replacement of the writable YAML keys: missing keys become None.

    An `other_only` text key is cleared (no error) unless its field's value is `other`.
    """
    specs = {k.key: k for k in journal_keys(config)}
    errors: dict[str, FieldIssue] = {}
    for key in fields:
        issue = _key_issue(key, specs)
        if issue is not None:
            errors[key] = issue
    values: dict[str, Any] = {}
    for spec in writable_keys(config):
        try:
            values[spec.key] = normalise_value(spec, fields.get(spec.key), current.get(spec.key))
        except InvalidJournalValue as exc:
            errors[spec.key] = exc.issue
            values[spec.key] = None
    for spec in writable_keys(config):
        if spec.other_only and values.get(spec.field.key) != OTHER_OPTION:
            values[spec.key] = None
    return JournalValidation(values=values, errors=errors)


# --- completeness ---


def required_field_keys(config: JournalFieldsConfig) -> tuple[str, ...]:
    """Keys of the fields with `required: true`, YAML order (text_keys are never listed)."""
    return tuple(field.key for field in config.fields if field.required)


@dataclass(frozen=True)
class RequirementScope:
    """When each required field became required (`journal_field_requirements`) and when
    the trade closed. A required field counts for the trade only when
    `close_time >= required_since` (docs/api.md "New required fields"). A field without a
    known date, or a trade without close_time, counts (the M2 rule)."""

    required_since: Mapping[str, datetime]
    close_time: datetime | None

    def applies(self, key: str) -> bool:
        since = self.required_since.get(key)
        return since is None or self.close_time is None or self.close_time >= since

    def is_new_for_trade(self, key: str) -> bool:
        """Made required after this (closed) trade closed."""
        since = self.required_since.get(key)
        return since is not None and self.close_time is not None and since > self.close_time


def _required_blank(spec: JournalKey, values: Mapping[str, Any], has_before_link: bool) -> bool:
    if spec.type == "links":
        return not has_before_link
    return _is_empty(values.get(spec.key))


def missing_required(
    config: JournalFieldsConfig,
    values: Mapping[str, Any],
    *,
    has_before_link: bool,
    scope: RequirementScope | None = None,
) -> list[str]:
    """What blocks `complete` (YAML order): required fields without a value, an
    `other_only` text when its field is `other`, `links` without a `before` link.

    With a `scope`, a required field is skipped for a trade that closed before the field
    became required (old complete trades stay complete). Without one, every field counts.
    """
    missing: list[str] = []
    for spec in journal_keys(config):
        if spec.other_only:
            blocked = values.get(spec.field.key) == OTHER_OPTION and values.get(spec.key) is None
        elif (
            spec.is_text_key
            or not spec.field.required
            or (scope is not None and not scope.applies(spec.key))
        ):
            blocked = False
        else:
            blocked = _required_blank(spec, values, has_before_link)
        if blocked:
            missing.append(spec.key)
    return missing


def missing_new_fields(
    config: JournalFieldsConfig,
    values: Mapping[str, Any],
    *,
    has_before_link: bool,
    scope: RequirementScope,
) -> list[str]:
    """TradeDetail.missing_new_fields (YAML order): required now, empty on the trade and
    made required after it closed. Informational, never blocks saving; [] for open trades."""
    return [
        spec.key
        for spec in journal_keys(config)
        if not spec.is_text_key
        and spec.field.required
        and scope.is_new_for_trade(spec.key)
        and _required_blank(spec, values, has_before_link)
    ]


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == ""


# --- storage ---


def split_storage(
    config: JournalFieldsConfig, values: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(trades columns, trades.extra keys) for the writable non-relation keys."""
    columns: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for spec in writable_keys(config):
        if spec.is_relation:
            continue
        target = columns if spec.storage == "column" else extra
        target[spec.key] = values.get(spec.key)
    return columns, extra


def merge_extra(
    config: JournalFieldsConfig, old: Mapping[str, Any], new: Mapping[str, Any]
) -> dict[str, Any]:
    """New `trades.extra`: keys not in the YAML kept as they are, YAML extra keys replaced,
    None dropped. Returns a new dict (JSONB change tracking needs a new object)."""
    yaml_extra = {k.key for k in journal_keys(config) if k.storage == "extra"}
    kept = {k: v for k, v in old.items() if k not in yaml_extra}
    return kept | {k: v for k, v in new.items() if v is not None}


def visible_journal(config: JournalFieldsConfig, stored: Mapping[str, Any]) -> dict[str, Any]:
    """TradeDetail.journal: every YAML key except `links` fields, None when empty."""
    return {
        spec.key: None if _is_empty(stored.get(spec.key)) else stored.get(spec.key)
        for spec in journal_keys(config)
        if spec.type != "links"
    }


def filter_ai_filled(keys: Sequence[str], values: Mapping[str, Any]) -> list[str]:
    """Keep AI-filled keys that have a non-null saved value; input order, no duplicates."""
    out: list[str] = []
    for key in keys:
        if key not in out and values.get(key) is not None:
            out.append(key)
    return out
