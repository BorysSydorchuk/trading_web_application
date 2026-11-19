"""`config/journal_fields.yaml`: journal field definitions (PRD 6.4).

The describe form, AI extraction schema and digest breakdowns are generated from these
definitions. Validation checks every definition against the Trade model so a typo in the
YAML fails at startup instead of when a trade is saved.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.dialects.postgresql import ARRAY

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)
from app.config_files.rules import get_rules, rules_path
from app.config_files.violations import get_violations, violations_path
from app.models.enums import BiasAlignment, ChartLinkKind
from app.models.trade import Trade

logger = logging.getLogger(__name__)

JOURNAL_FIELDS_FILE = "journal_fields.yaml"

FieldType = Literal["enum", "multi_enum", "bool", "int", "text", "links", "auto"]
Storage = Literal["column", "extra"]
# M8-02: "after" fields describe the exit; they stay empty while the position is open.
Phase = Literal["before", "after"]

_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"
_OPTION_TYPES = frozenset({"enum", "multi_enum"})

# Journal fields backed by a child table instead of a trades column: key -> required type.
RELATION_FIELDS: dict[str, FieldType] = {"chart_links": "links", "rule_violations": "multi_enum"}
# Trade columns that are not journal fields (system state, raw input, bookkeeping).
RESERVED_KEYS = frozenset(
    {
        "id",
        "account_id",
        "position_id",
        "status",
        "extra",
        "ai_filled_fields",
        "raw_text",
        "transcript",
        "described_at",
        "created_at",
        "updated_at",
    }
)
# Columns with a DB CHECK on fixed values: their options must stay within these values.
SYSTEM_ENUM_COLUMNS: dict[str, frozenset[str]] = {
    "bias_alignment": frozenset(v.value for v in BiasAlignment),
    "chart_links": frozenset({ChartLinkKind.BEFORE.value, ChartLinkKind.AFTER.value}),
}
# Its options are injected from config/violations.yaml (M8-04), never written in this file.
RULE_VIOLATIONS_FIELD = "rule_violations"
# rules.yaml `qm_not_in_ny.entry_model` must be an option of this field.
QM_RULE_FIELD = "entry_model"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JournalOption(_Strict):
    value: str = Field(pattern=_KEY_PATTERN, max_length=50)
    label: str = Field(min_length=1)
    deprecated: bool = False


class ShowIf(_Strict):
    """Show (and require) the field only when the parent equals / contains `includes`."""

    field: str = Field(pattern=_KEY_PATTERN, max_length=63)
    includes: str = Field(pattern=_KEY_PATTERN, max_length=50)


class JournalField(_Strict):
    key: str = Field(pattern=_KEY_PATTERN, max_length=63)
    label: str = Field(min_length=1)
    type: FieldType
    options: tuple[JournalOption, ...] = ()
    required: bool
    analytics: bool
    storage: Storage
    # Free text kept next to an option field (column or extra key, same storage as the field).
    text_key: str | None = Field(default=None, pattern=_KEY_PATTERN, max_length=63)
    # true: the text belongs to the `other` option only; false: optional note for any value.
    allow_other_text: bool = False
    min: int | None = None
    max: int | None = None
    phase: Phase = "before"
    # M8-04..08: shown, required and AI-fillable only when the parent has the option.
    show_if: ShowIf | None = None
    # Read-only old field («Старе значення»): never written, required or analysed.
    legacy: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.legacy and (self.required or self.analytics):
            raise ValueError("legacy fields cannot be required or analytics")
        if self.type in _OPTION_TYPES:
            active = [o for o in self.options if not o.deprecated]
            if not active:
                raise ValueError(f"type {self.type} needs at least one non-deprecated option")
        elif self.options and self.type not in {"auto", "links"}:
            raise ValueError(f"type {self.type} does not take options")
        values = [o.value for o in self.options]
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            raise ValueError(f"duplicate option values: {', '.join(dupes)}")
        if self.text_key is not None and self.type not in _OPTION_TYPES:
            raise ValueError("text_key is only allowed for enum/multi_enum fields")
        if self.allow_other_text:
            if self.text_key is None:
                raise ValueError("allow_other_text needs text_key (where the text is stored)")
            if "other" not in values:
                raise ValueError("allow_other_text needs an option with value 'other'")
        if (self.min is not None or self.max is not None) and self.type != "int":
            raise ValueError("min/max are only allowed for int fields")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min {self.min} is greater than max {self.max}")
        if self.phase == "after" and self.type in {"auto", "links"}:
            raise ValueError(f"type {self.type} cannot have phase: after")
        if self.type == "auto" and self.storage != "column":
            raise ValueError("auto fields are computed by the app and need storage: column")
        return self

    def option_values(self, include_deprecated: bool = True) -> list[str]:
        return [o.value for o in self.options if include_deprecated or not o.deprecated]


def _show_if_problem(field: JournalField, earlier: dict[str, JournalField]) -> str | None:
    """Why `field.show_if` is invalid (None = valid). `earlier` = the fields above it."""
    cond = field.show_if
    if cond is None:
        return None
    where = f"field {field.key!r} show_if"
    if cond.field == field.key:
        return f"{where}: a field cannot depend on itself"
    parent = earlier.get(cond.field)
    if parent is None:
        return f"{where}: parent {cond.field!r} must be a field earlier in the file"
    if parent.type not in _OPTION_TYPES:
        return f"{where}: parent {cond.field!r} must be enum or multi_enum"
    if parent.show_if is not None or parent.legacy:
        return f"{where}: parent {cond.field!r} cannot have its own show_if or be legacy"
    if cond.includes not in parent.option_values():
        return f"{where}: {cond.includes!r} is not an option of {cond.field!r}"
    return None


class JournalFieldsConfig(_Strict):
    fields: tuple[JournalField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _show_if_parents(self) -> Self:
        earlier: dict[str, JournalField] = {}
        problems: list[str] = []
        for field in self.fields:
            problem = _show_if_problem(field, earlier)
            if problem is not None:
                problems.append(problem)
            earlier[field.key] = field
        if problems:
            raise ValueError("\n".join(problems))
        return self

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        seen: set[str] = set()
        for field in self.fields:
            for key in (field.key, field.text_key):
                if key is None:
                    continue
                if key in seen:
                    raise ValueError(f"key {key!r} is used twice (field keys and text_keys)")
                seen.add(key)
        return self

    def get(self, key: str) -> JournalField | None:
        return next((f for f in self.fields if f.key == key), None)

    def for_open_trade(self) -> JournalFieldsConfig:
        """Only the pre-entry fields (phase before): what an open position can carry (M8-02)."""
        return self.model_copy(
            update={"fields": tuple(f for f in self.fields if f.phase == "before")}
        )

    def after_fields(self) -> tuple[JournalField, ...]:
        """The after-trade fields (phase after): empty while the position is open."""
        return tuple(f for f in self.fields if f.phase == "after")

    def to_api(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _trade_columns() -> frozenset[str]:
    return frozenset(c.key for c in Trade.__table__.columns)


def model_problems(config: JournalFieldsConfig) -> list[str]:
    """Checks against the Trade model; one readable line per problem (`fields[i] key: ...`)."""
    columns = _trade_columns()
    problems: list[str] = []
    for i, field in enumerate(config.fields):
        where = f"fields[{i}] {field.key}"
        if field.key in RESERVED_KEYS or field.text_key in RESERVED_KEYS:
            problems.append(f"{where}: reserved trade column, not a journal field")
            continue
        if field.storage == "column":
            relation_type = RELATION_FIELDS.get(field.key)
            if relation_type is not None:
                if field.type != relation_type:
                    problems.append(f"{where}: must have type {relation_type}")
            elif field.key not in columns:
                problems.append(
                    f"{where}: storage is column but trades has no column {field.key!r} "
                    "(add a migration or use storage: extra)"
                )
            elif field.type == "links":
                problems.append(f"{where}: links fields must be a relation (chart_links)")
            if field.text_key is not None and field.text_key not in columns:
                problems.append(f"{where}: trades has no column {field.text_key!r} for text_key")
        else:
            for key in (field.key, field.text_key):
                if key is not None and (key in columns or key in RELATION_FIELDS):
                    problems.append(f"{where}: {key!r} is a real trade column, use storage: column")
            if field.type == "links":
                problems.append(f"{where}: links fields need storage: column (chart_links)")
        allowed = SYSTEM_ENUM_COLUMNS.get(field.key)
        if allowed is not None and field.storage == "column":
            unknown = sorted(set(field.option_values()) - allowed)
            if unknown:
                problems.append(
                    f"{where}: unknown option values {', '.join(unknown)} "
                    f"(allowed: {', '.join(sorted(allowed))})"
                )
        problems.extend(_array_problems(field, where))
    return problems


def _array_problems(field: JournalField, where: str) -> list[str]:
    """A multi_enum column is a VARCHAR[] trades column; a scalar field is not."""
    if field.storage != "column" or field.key in RELATION_FIELDS:
        return []
    column = Trade.__table__.columns.get(field.key)
    if column is None:
        return []
    is_array = isinstance(column.type, ARRAY)
    if field.type == "multi_enum" and not is_array:
        return [f"{where}: multi_enum with storage column needs an array column"]
    if field.type != "multi_enum" and is_array:
        return [f"{where}: column {field.key!r} is an array, the field must be multi_enum"]
    return []


def _rules_problems(config: JournalFieldsConfig) -> list[str]:
    """Cross-check with rules.yaml. Skipped when rules.yaml itself is broken (reported there)."""
    try:
        rules = get_rules()
    except ConfigError:
        logger.warning("Skipping journal_fields/rules cross-check: rules.yaml is invalid")
        return []
    model = rules.rules.qm_not_in_ny.entry_model
    field = config.get(QM_RULE_FIELD)
    if field is None or model not in field.option_values():
        return [
            f"rules.yaml qm_not_in_ny.entry_model {model!r} is not an option of "
            f"the {QM_RULE_FIELD} field"
        ]
    return []


def journal_fields_path() -> Path:
    return config_dir() / JOURNAL_FIELDS_FILE


def load_journal_fields(path: Path | None = None) -> JournalFieldsConfig:
    """Parse and validate a journal fields file (uncached). Raises ConfigError."""
    path = path or journal_fields_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `fields` list"])
    raw = _with_violation_options(path, raw)
    try:
        config = JournalFieldsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, _with_field_keys(raw, validation_problems(exc))) from None
    problems = model_problems(config) + _rules_problems(config)
    if problems:
        raise ConfigError(path, problems)
    return config


def _with_violation_options(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    """A copy of `raw` whose `rule_violations` field has the options of violations.yaml
    (labels; deprecated = status deprecated). Raises the violations.yaml ConfigError when
    that file is broken (the field cannot be built without it)."""
    fields = raw.get("fields")
    if not isinstance(fields, list):
        return raw
    out: list[Any] = []
    for item in fields:
        if isinstance(item, dict) and item.get("key") == RULE_VIOLATIONS_FIELD:
            if item.get("options"):
                message = f"options come from {violations_path().name}, remove them here"
                raise ConfigError(path, [f"{RULE_VIOLATIONS_FIELD}: {message}"])
            options = [
                {"value": v.key, "label": v.label, "deprecated": v.deprecated}
                for v in get_violations().violations
            ]
            item = item | {"options": options}
        out.append(item)
    return raw | {"fields": out}


def _with_field_keys(raw: dict[str, Any], problems: list[str]) -> list[str]:
    """`fields[3].options: ...` -> `fields[3] (entry_model).options: ...` for readability."""
    fields = raw.get("fields")
    if not isinstance(fields, list):
        return problems
    out = []
    for problem in problems:
        for i, item in enumerate(fields):
            prefix = f"fields[{i}]"
            if problem.startswith(prefix) and isinstance(item, dict) and "key" in item:
                problem = f"{prefix} ({item['key']}){problem[len(prefix) :]}"
                break
        out.append(problem)
    return out


_cache: FileCache[JournalFieldsConfig] = FileCache(
    lambda: [journal_fields_path(), rules_path(), violations_path()], load_journal_fields
)


def get_journal_fields() -> JournalFieldsConfig:
    """Cached definitions; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_journal_fields_cache() -> None:
    _cache.clear()
