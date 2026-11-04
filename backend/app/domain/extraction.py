"""AI extraction, pure part (docs/api.md "AI extraction", PRD 6.5). No I/O.

Everything is generated from `config/journal_fields.yaml` via `ai_fillable_keys`:
- `build_extraction_schema`: the strict JSON schema the model must answer with;
- `render_field_catalogue`: the field/option list injected into the system prompt;
- `apply_guards`: the server-side anti-invention checks on the model's answer.

The model answers `{"fields": [{"key", "value", "evidence": "<verbatim quote>"}, ...]}` with
only the keys it could fill; `answer_entries` turns that into per-key entries
`{"<key>": {"value": <typed>, "evidence": ...}}`, the shape the guards (and the
extraction fixtures' `model_output`) use. There is no free-form message field, so it cannot ask
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

FIELDS_KEY = "fields"
KEY_KEY = "key"
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
        chr(0x0451): chr(0x0435),  # Cyrillic yo -> ie (Russian texts mix them)
        chr(0x0401): chr(0x0415),
    }
)
_WHITESPACE = re.compile(r"\s+")
# Evidence needs at least this many letters/digits (1-2 letter quotes match anywhere;
# punctuation and spaces do not count).
MIN_EVIDENCE_CHARS = 3

# Number words accepted for an int value (closed list, 1-5 = quality_rating range), after
# normalise_for_match (casefold, apostrophes -> ', yo -> ie). Whole words only.
NUMBER_WORDS: dict[str, int] = {
    **dict.fromkeys(("один", "одна", "одиниця", "единица", "единичка", "one"), 1),
    **dict.fromkeys(("два", "дві", "двійка", "двойка", "two"), 2),
    **dict.fromkeys(("три", "трійка", "тройка", "three"), 3),
    **dict.fromkeys(("чотири", "четыре", "четвірка", "четверка", "four"), 4),
    **dict.fromkeys(("п'ять", "пять", "п'ятірка", "пятерка", "five"), 5),
}
_NUMBER_WORD = re.compile(r"(?<![\w'])(" + "|".join(map(re.escape, NUMBER_WORDS)) + r")(?![\w'])")
_NUMBER = re.compile(r"\d+")
# "N из/з/із/of/out of M" or "N/M" right before a number: that number is the denominator.
_DENOMINATOR_PREFIX = re.compile(r"\d\s*(?:/|(?<!\w)(?:из|з|із|of|out of)\s)\s*$")
# Part of a decimal (4.5, 4,5), a clock time (9:05, 14:30) or a range (4-5; en/em dashes are
# folded to "-"): the number is not a value on its own.
_JOINED_BEFORE = re.compile(r"\d[.,:-]$")
_JOINED_AFTER = re.compile(r"[.,:-]\d")
# Money or percent signs glued to the number ($5, 5€, 1%).
_UNIT_BEFORE = frozenset("$€£")
_UNIT_AFTER = frozenset("%$€£")
# An apostrophe at a word edge is a quote mark ('п'ять'), not part of the word.
_EDGE_APOSTROPHE = re.compile(r"(?<!\w)'|'(?!\w)")
# Besides letters and digits these belong to a word for the word-boundary check.
_WORD_EXTRA = frozenset("'_")


# --- schema ---


def _options(spec: JournalKey) -> list[str]:
    return spec.field.option_values(include_deprecated=False)


def _int_range(spec: JournalKey) -> str:
    low, high = spec.field.min, spec.field.max
    if low is not None and high is not None:
        return f"integer from {low} to {high}"
    if low is not None:
        return f"integer >= {low}"
    if high is not None:
        return f"integer <= {high}"
    return "integer"


def build_extraction_schema(config: JournalFieldsConfig) -> dict[str, Any]:
    """Strict JSON schema of the answer: `{"fields": [{"key", "value", "evidence"}, ...]}`.

    Deliberately flat (one item shape, every property required, no optional properties,
    no unions): the API compiles the schema into a grammar, and the earlier one-optional-
    object-per-key schema was rejected as "too complex" or took 40+ s. `value` is always a
    string; `answer_entries` types it from the YAML. No free-form text property, so the
    model can only fill fields.
    """
    keys = [spec.key for spec in ai_fillable_keys(config)]
    item = {
        "type": "object",
        "properties": {
            KEY_KEY: {"type": "string", "enum": keys},
            VALUE_KEY: {"type": "string"},
            EVIDENCE_KEY: {"type": "string"},
        },
        "required": [KEY_KEY, VALUE_KEY, EVIDENCE_KEY],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {FIELDS_KEY: {"type": "array", "items": item}},
        "required": [FIELDS_KEY],
        "additionalProperties": False,
    }


# --- model answer -> per-key entries ---


class InvalidAnswer(ValueError):  # noqa: N818 - reads as "raise InvalidAnswer"
    """The answer does not have the schema's shape (an `invalid_output`)."""


_INT_TEXT = re.compile(r"[+-]?\d+")
_BOOL_TEXT = {"true": True, "false": False}
# A single-value key answered twice with different values: dropped as invalid_option.
CONFLICT = object()


def _typed(spec: JournalKey | None, raw: str) -> Any:
    """String value from the answer -> the type of its YAML field (unchanged when it does
    not parse, so the guards report it as invalid_option)."""
    text = raw.strip()
    if spec is None or text == "":
        return text or None
    if spec.type == "int" and _INT_TEXT.fullmatch(text):
        return int(text)
    if spec.type == "bool":
        return _BOOL_TEXT.get(text.casefold(), raw)
    return raw


def _items(answer: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    items = answer.get(FIELDS_KEY)
    if not isinstance(items, list):
        raise InvalidAnswer(f"`{FIELDS_KEY}` is not an array")
    out: list[tuple[str, str, str]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise InvalidAnswer("an item is not an object")
        key, value, evidence = (item.get(k) for k in (KEY_KEY, VALUE_KEY, EVIDENCE_KEY))
        if not (isinstance(key, str) and isinstance(value, str) and isinstance(evidence, str)):
            raise InvalidAnswer("an item needs string key, value and evidence")
        out.append((key, value, evidence))
    return out


def answer_entries(config: JournalFieldsConfig, answer: Mapping[str, Any]) -> dict[str, Any]:
    """The schema answer as per-key entries `{key: {"value", "evidence"}}` for apply_guards.

    multi_enum: one item per option, merged into `{"value": [...], "evidence": [...]}`.
    Single-value keys: a repeated identical value is ignored, a different one is a
    conflict (dropped). Raises InvalidAnswer when the shape is wrong.
    """
    specs = {spec.key: spec for spec in ai_fillable_keys(config)}
    entries: dict[str, Any] = {}
    for key, raw, evidence in _items(answer):
        spec = specs.get(key)
        value = _typed(spec, raw)
        if value is None:
            continue
        current = entries.get(key)
        if spec is not None and spec.type == "multi_enum":
            merged = current or {VALUE_KEY: [], EVIDENCE_KEY: []}
            entries[key] = {
                VALUE_KEY: [*merged[VALUE_KEY], value],
                EVIDENCE_KEY: [*merged[EVIDENCE_KEY], evidence],
            }
        elif current is None:
            entries[key] = {VALUE_KEY: value, EVIDENCE_KEY: evidence}
        elif current is not CONFLICT and current[VALUE_KEY] != value:
            entries[key] = CONFLICT
    return entries


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
    letters_digits = sum(1 for char in quote if char.isalnum())
    return letters_digits >= MIN_EVIDENCE_CHARS and contains_phrase(quote, normalised_text)


def _standalone_numbers(text: str) -> list[int]:
    """Numbers in `text` that stand alone: no letter/digit glued on either side (M5, H4),
    not part of a decimal, time or range (4.5, 4,5, 9:05, 4-5), no money/percent sign glued
    on ($5, 5€, 1%) and not the denominator of "N из/з/із/of M", "N/M"."""
    numbers: list[int] = []
    for match in _NUMBER.finditer(text):
        before, after = text[: match.start()], text[match.end() :]
        if (before and before[-1].isalnum()) or (after and after[0].isalnum()):
            continue
        if _JOINED_BEFORE.search(before) or _JOINED_AFTER.match(after):
            continue
        if (before and before[-1] in _UNIT_BEFORE) or (after and after[0] in _UNIT_AFTER):
            continue
        if _DENOMINATOR_PREFIX.search(before):
            continue
        numbers.append(int(match.group()))
    return numbers


def number_in_evidence(value: int, evidence: str) -> bool:
    """The int value is said in its evidence: as a standalone number, or as one of the
    closed list of number words (NUMBER_WORDS, 1-5), whole words, case-insensitive."""
    quote = _EDGE_APOSTROPHE.sub("", normalise_for_match(evidence))
    quote = _NUMBER_WORD.sub(lambda m: str(NUMBER_WORDS[m.group(1)]), quote)
    return value in _standalone_numbers(quote)


def _issue_reason(code: IssueCode) -> DropReason:
    return "out_of_range" if code in _RANGE_ISSUES else "invalid_option"


def _check_entry(spec: JournalKey, entry: Any, text: str) -> tuple[Any, DropReason | None]:
    """(normalised value or None, drop reason or None). None/None = not filled."""
    if entry is None:
        return None, None
    if entry is CONFLICT:
        return None, "invalid_option"
    if not isinstance(entry, Mapping):
        return None, "evidence_not_in_text"
    raw = entry.get(VALUE_KEY)
    if raw is None:
        return None, None
    evidence = entry.get(EVIDENCE_KEY)
    quotes = evidence if isinstance(evidence, list) else [evidence]  # multi_enum: one per option
    if not quotes or not all(evidence_in_text(quote, text) for quote in quotes):
        return None, "evidence_not_in_text"
    try:
        value = normalise_value(spec, raw)
    except InvalidJournalValue as exc:
        return None, _issue_reason(exc.issue.code)
    return value, _value_issue(spec, value, str(evidence), text)


def _value_issue(spec: JournalKey, value: Any, evidence: str, text: str) -> DropReason | None:
    """Ties the value to the text: an int must be said in its evidence (number_in_evidence); a text
    value must be his own words (a word-boundary substring of the input text)."""
    if value is None:
        return None
    if spec.type == "int" and not number_in_evidence(value, evidence):
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
