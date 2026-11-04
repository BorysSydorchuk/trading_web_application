"""AI extraction, pure part (docs/api.md "AI extraction", PRD 6.5). No I/O.

Everything is generated from `config/journal_fields.yaml` via `ai_fillable_keys`:
- `build_extraction_schema`: the strict JSON schema the model must answer with;
- `render_field_catalogue`: the field/option list injected into the system prompt;
- `apply_guards`: the server-side anti-invention checks on the model's answer.

The model answers `{ "<key>": { "value": ..., "evidence": "<verbatim quote>" }, ... }` with
only the keys it could fill. There is no free-form message field, so it cannot ask
questions or comment; what is missing is computed by the server.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.journal import (
    OTHER_OPTION,
    InvalidJournalValue,
    IssueCode,
    JournalKey,
    ai_fillable_keys,
    missing_required,
    normalise_value,
)

VALUE_KEY = "value"
EVIDENCE_KEY = "evidence"

DropReason = Literal[
    "evidence_not_in_text",
    "invalid_option",
    "out_of_range",
    "parent_not_other",
    "question",
    "not_fillable",  # key not in the schema (auto, links, rule_violations, unknown)
]

# FieldIssue codes (app.domain.journal) that mean "value outside the allowed range".
_RANGE_ISSUES: frozenset[IssueCode] = frozenset({"out_of_range", "too_long"})

# Typographic variants folded before the evidence comparison (speech-to-text and phone
# keyboards mix them): apostrophes, quotes, dashes, non-breaking spaces.
_FOLD = str.maketrans(
    {
        **dict.fromkeys(map(chr, (0x2019, 0x2018, 0x02BC, 0x60)), "'"),
        **dict.fromkeys(map(chr, (0x201C, 0x201D, 0x00AB, 0x00BB)), '"'),
        **dict.fromkeys(map(chr, (0x2013, 0x2014)), "-"),
        chr(0x00A0): " ",
    }
)
_WHITESPACE = re.compile(r"\s+")
# Evidence must be at least this long after normalisation (1-2 letter quotes match anywhere).
MIN_EVIDENCE_CHARS = 3
# Besides letters and digits these belong to a word for the word-boundary check.
_WORD_EXTRA = frozenset("'_")


# --- schema ---


def _options(spec: JournalKey) -> list[str]:
    return spec.field.option_values(include_deprecated=False)


def _value_schema(spec: JournalKey) -> dict[str, Any]:
    match spec.type:
        case "enum":
            return {"type": "string", "enum": _options(spec)}
        case "multi_enum":
            return {"type": "array", "items": {"type": "string", "enum": _options(spec)}}
        case "bool":
            return {"type": "boolean"}
        case "int":
            # Numeric bounds are enforced by the guards (out_of_range), not the schema.
            return {"type": "integer", "description": _int_range(spec)}
        case _:
            return {"type": "string"}


def _int_range(spec: JournalKey) -> str:
    low, high = spec.field.min, spec.field.max
    if low is not None and high is not None:
        return f"integer from {low} to {high}"
    if low is not None:
        return f"integer >= {low}"
    if high is not None:
        return f"integer <= {high}"
    return "integer"


def _entry_schema(spec: JournalKey) -> dict[str, Any]:
    return {
        "type": "object",
        "description": spec.field.label if not spec.is_text_key else f"{spec.field.label}: текст",
        "properties": {
            VALUE_KEY: _value_schema(spec),
            EVIDENCE_KEY: {
                "type": "string",
                "description": "exact verbatim quote from the user's text that states the value",
            },
        },
        "required": [VALUE_KEY, EVIDENCE_KEY],
        "additionalProperties": False,
    }


def build_extraction_schema(config: JournalFieldsConfig) -> dict[str, Any]:
    """Strict JSON schema: one optional `{value, evidence}` property per AI-fillable key.

    Keys are optional (a field the text does not state is simply left out); no union
    types and no free-form text property, so the model can only fill fields.
    """
    return {
        "type": "object",
        "properties": {spec.key: _entry_schema(spec) for spec in ai_fillable_keys(config)},
        "additionalProperties": False,
    }


# --- prompt field catalogue ---


def _catalogue_lines(spec: JournalKey) -> list[str]:
    head = f"- `{spec.key}` ({spec.field.label})"
    if spec.other_only:
        return [f"{head}: free text, only when `{spec.field.key}` is `{OTHER_OPTION}`."]
    if spec.is_text_key:
        return [f"{head}: optional free-text note about `{spec.field.key}`."]
    match spec.type:
        case "enum" | "multi_enum":
            many = "one or more option values" if spec.type == "multi_enum" else "one option value"
            options = [
                f"  - `{o.value}`: {o.label}" for o in spec.field.options if not o.deprecated
            ]
            return [f"{head}: {many}:", *options]
        case "bool":
            return [f"{head}: true or false."]
        case "int":
            return [f"{head}: {_int_range(spec)}."]
        case _:
            return [f"{head}: free text."]


def render_field_catalogue(config: JournalFieldsConfig) -> str:
    """Markdown list of the fillable keys with their option values and labels (YAML order).
    Deterministic: the same YAML always gives the same text (prompt caching)."""
    lines: list[str] = []
    for spec in ai_fillable_keys(config):
        lines.extend(_catalogue_lines(spec))
    return "\n".join(lines)


# --- guards ---


@dataclass(frozen=True)
class Dropped:
    key: str
    reason: DropReason


@dataclass(frozen=True)
class GuardResult:
    fields: dict[str, Any]  # kept values, YAML order
    dropped: list[Dropped]

    @property
    def ai_filled_fields(self) -> list[str]:
        return list(self.fields)


def normalise_for_match(text: str) -> str:
    """Case-insensitive, whitespace-normalised form used to find evidence in the text."""
    return _WHITESPACE.sub(" ", text.translate(_FOLD).casefold()).strip()


def _word_char(char: str) -> bool:
    return char.isalnum() or char in _WORD_EXTRA


def contains_phrase(phrase: str, normalised_text: str) -> bool:
    """`phrase` (already normalised) occurs in the text starting and ending at word edges:
    no letter/digit/apostrophe/underscore right before a phrase that starts with one, or
    right after a phrase that ends with one ("лан" does not match inside "план")."""
    if not phrase:
        return False
    start = normalised_text.find(phrase)
    while start != -1:
        end = start + len(phrase)
        before_ok = (
            not _word_char(phrase[0]) or start == 0 or not _word_char(normalised_text[start - 1])
        )
        after_ok = (
            not _word_char(phrase[-1])
            or end == len(normalised_text)
            or not _word_char(normalised_text[end])
        )
        if before_ok and after_ok:
            return True
        start = normalised_text.find(phrase, start + 1)
    return False


def evidence_in_text(evidence: Any, normalised_text: str) -> bool:
    """The quote is at least MIN_EVIDENCE_CHARS (normalised) and occurs in the text on word
    boundaries (case-insensitive, whitespace-normalised)."""
    if not isinstance(evidence, str):
        return False
    quote = normalise_for_match(evidence)
    return len(quote) >= MIN_EVIDENCE_CHARS and contains_phrase(quote, normalised_text)


def _number_in(value: int, evidence: str) -> bool:
    return re.search(rf"(?<!\d){value}(?!\d)", evidence) is not None


def _issue_reason(code: IssueCode) -> DropReason:
    return "out_of_range" if code in _RANGE_ISSUES else "invalid_option"


def _check_entry(spec: JournalKey, entry: Any, text: str) -> tuple[Any, DropReason | None]:
    """(normalised value or None, drop reason or None). None/None = not filled."""
    if entry is None:
        return None, None
    if not isinstance(entry, Mapping):
        return None, "evidence_not_in_text"
    raw = entry.get(VALUE_KEY)
    if raw is None:
        return None, None
    evidence = entry.get(EVIDENCE_KEY)
    if not evidence_in_text(evidence, text):
        return None, "evidence_not_in_text"
    try:
        value = normalise_value(spec, raw)
    except InvalidJournalValue as exc:
        return None, _issue_reason(exc.issue.code)
    return value, _value_issue(spec, value, str(evidence), text)


def _value_issue(spec: JournalKey, value: Any, evidence: str, text: str) -> DropReason | None:
    """Ties the value to the text: an int must appear as digits in its evidence; a text
    value must be his own words (a word-boundary substring of the input text)."""
    if value is None:
        return None
    if spec.type == "int" and not _number_in(value, evidence):
        return "evidence_not_in_text"
    if spec.type == "text":
        if "?" in value and "?" not in evidence:
            return "question"
        if not contains_phrase(normalise_for_match(value), text):
            return "evidence_not_in_text"
    return None


def apply_guards(config: JournalFieldsConfig, output: Mapping[str, Any], text: str) -> GuardResult:
    """Drop every value the text does not support (docs/api.md "Guards").

    `output` is the parsed model answer (an object); `text` is the user's input.
    """
    specs = {spec.key: spec for spec in ai_fillable_keys(config)}
    order = {key: i for i, key in enumerate(specs)}
    normalised_text = normalise_for_match(text)
    kept: dict[str, Any] = {}
    dropped: list[Dropped] = []
    for key, entry in output.items():
        spec = specs.get(key)
        if spec is None:
            if entry is not None:
                dropped.append(Dropped(key, "not_fillable"))
            continue
        value, reason = _check_entry(spec, entry, normalised_text)
        if reason is not None:
            dropped.append(Dropped(key, reason))
        elif value is not None:
            kept[key] = value
    for key in list(kept):
        spec = specs[key]
        if spec.other_only and kept.get(spec.field.key) != OTHER_OPTION:
            del kept[key]
            dropped.append(Dropped(key, "parent_not_other"))
    ordered = {key: kept[key] for key in sorted(kept, key=order.__getitem__)}
    dropped.sort(key=lambda d: order.get(d.key, len(order)))
    return GuardResult(fields=ordered, dropped=dropped)


# --- completeness ---


def extraction_missing(config: JournalFieldsConfig, fields: Mapping[str, Any]) -> list[str]:
    """`missing_required` of an extraction result: same rule as the journal save. The
    extraction never returns chart links, so `chart_links` is listed when it is required."""
    return missing_required(config, fields, has_before_link=False)
