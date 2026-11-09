"""Bias extraction, pure part (docs/api.md "Bias extraction", PRD 6.6). No I/O.

The model answers one flat list `{"entries": [{"symbol", "key", "value", "evidence"}]}` (the
same shape as the trade schema plus `symbol`, so the grammar stays as simple). The guards
reuse the trade extraction's checks (app.domain.extraction): evidence quoted from the text
on word boundaries, free text = his own words, no questions, ints said as the only number
of their quote. On top, the symbol must be mentioned in the text (its name or a bias.yaml
alias), else the value is dropped with `symbol_not_in_text`. `key_levels` may hold several
pieces of his text joined by "; " (in text order, no repeats); `narrative` is one piece.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.config_files.bias import BiasConfig
from app.domain.extraction import (
    CONFLICT,
    EVIDENCE_KEY,
    KEY_KEY,
    VALUE_KEY,
    DropReason,
    NumberWords,
    evidence_in_text,
    find_phrase,
    normalise_for_match,
    number_in_evidence,
    string_items,
    text_value_issue,
)
from app.models.enums import BiasDirection, BiasKind

ENTRIES_KEY = "entries"
SYMBOL_KEY = "symbol"

DIRECTION = "direction"
KEY_LEVELS = "key_levels"
NARRATIVE = "narrative"
CONFIDENCE = "confidence"
BIAS_FIELD_KEYS: tuple[str, ...] = (DIRECTION, KEY_LEVELS, NARRATIVE, CONFIDENCE)
TEXT_KEYS = frozenset({KEY_LEVELS, NARRATIVE})
DIRECTIONS: tuple[str, ...] = tuple(d.value for d in BiasDirection)
CONFIDENCE_MIN = 1
CONFIDENCE_MAX = 3
TEXT_MAX_LENGTH = 5000  # same limit as BiasEntryInput text fields
KEY_LEVELS_SEPARATOR = "; "  # several levels for one symbol, in the order he named them

BiasDropReason = Literal[DropReason, "symbol_not_in_text"]

# What each note kind is, for the prompt (the schema does not depend on the kind).
KIND_DESCRIPTIONS: Mapping[BiasKind, str] = {
    BiasKind.PRE_LONDON: (
        "`pre_london`: the daily bias for today, written before the London session "
        "(before 08:00 Brussels time)."
    ),
    BiasKind.PRE_NY: (
        "`pre_ny`: the daily bias for the rest of today, written during the pre-market "
        "(11:00-13:00 Brussels time) before the New York session."
    ),
    BiasKind.WEEKLY: "`weekly`: the bias for the whole trading week.",
    BiasKind.MONTHLY: "`monthly`: the bias for the whole month.",
}

_INT_TEXT = re.compile(r"[+-]?\d+")
# Cyrillic aliases are matched with Ukrainian/Russian case endings: "золото" also matches
# "золоту", "золота"; "дакс" also "даксу". The alias's last vowel / soft sign is the
# ending; the stem (>= MIN_STEM letters) may be followed by up to MAX_ENDING letters.
# Shorter stems (євро, евро) match the whole word only.
_CYRILLIC = "Ѐ-ӿ"
_ENDING_CHARS = frozenset("аеєиіїоуюяьйыэ")
MIN_STEM = 4  # a 3-letter stem (євр) would also match Європа/Европа
MAX_ENDING = 3


# --- schema and prompt ---


def build_bias_schema(config: BiasConfig) -> dict[str, Any]:
    """Strict JSON schema: `{"entries": [{"symbol", "key", "value", "evidence"}, ...]}`.

    Flat on purpose like the trade schema (every property required, no unions): the API
    compiles it into a grammar. No free-form property, so the model cannot ask anything.
    """
    item = {
        "type": "object",
        "properties": {
            SYMBOL_KEY: {"type": "string", "enum": list(config.symbol_names)},
            KEY_KEY: {"type": "string", "enum": list(BIAS_FIELD_KEYS)},
            VALUE_KEY: {"type": "string"},
            EVIDENCE_KEY: {"type": "string"},
        },
        "required": [SYMBOL_KEY, KEY_KEY, VALUE_KEY, EVIDENCE_KEY],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {ENTRIES_KEY: {"type": "array", "items": item}},
        "required": [ENTRIES_KEY],
        "additionalProperties": False,
    }


def render_symbol_catalogue(config: BiasConfig) -> str:
    """Markdown list of the symbols and their spoken aliases (bias.yaml order). Deterministic."""
    lines: list[str] = []
    for entry in config.symbols:
        aliases = ", ".join(entry.aliases)
        lines.append(f"- `{entry.symbol}`" + (f": also called {aliases}" if aliases else ""))
    return "\n".join(lines)


# --- symbol mentions ---


def _alias_pattern(name: str) -> str:
    word = normalise_for_match(name)
    if re.search(f"[{_CYRILLIC}]", word):
        stem = word[:-1] if word[-1] in _ENDING_CHARS else word
        if len(stem) >= MIN_STEM:
            return rf"(?<![\w']){re.escape(stem)}[{_CYRILLIC}]{{0,{MAX_ENDING}}}(?![\w'])"
    return rf"(?<![\w']){re.escape(word)}(?![\w'])"


def mentioned_symbols(config: BiasConfig, text: str) -> frozenset[str]:
    """Symbols whose name or an alias occurs in the text as a whole word (normalised like
    the evidence match; Cyrillic aliases also with a case ending)."""
    normalised = normalise_for_match(text)
    found: set[str] = set()
    for entry in config.symbols:
        names = (entry.symbol, *entry.aliases)
        if any(re.search(_alias_pattern(name), normalised) for name in names):
            found.add(entry.symbol)
    return frozenset(found)


# --- model answer -> per (symbol, key) values ---


def answer_values(answer: Mapping[str, Any]) -> dict[tuple[str, str], Any]:
    """`{(symbol, key): (value, evidence)}` in answer order; an empty value is skipped, a
    repeated identical value ignored, a different one is a conflict (invalid_option).
    Raises InvalidAnswer when the shape is wrong."""
    values: dict[tuple[str, str], Any] = {}
    keys = (SYMBOL_KEY, KEY_KEY, VALUE_KEY, EVIDENCE_KEY)
    for symbol, key, raw, evidence in string_items(answer, ENTRIES_KEY, keys):
        value = raw.strip()
        if not value:
            continue
        current = values.get((symbol, key))
        if current is None:
            values[(symbol, key)] = (value, evidence)
        elif current is not CONFLICT and current[0] != value:
            values[(symbol, key)] = CONFLICT
    return values


# --- guards ---


@dataclass(frozen=True)
class BiasDropped:
    symbol: str
    key: str
    reason: BiasDropReason


@dataclass(frozen=True)
class BiasEntryResult:
    symbol: str
    fields: dict[str, str | int]  # BIAS_FIELD_KEYS order
    evidence: dict[str, str]  # the model's quote per kept field


@dataclass(frozen=True)
class BiasGuardResult:
    entries: list[BiasEntryResult]  # bias.yaml order, only symbols with a kept value
    dropped: list[BiasDropped]


def _check_value(
    key: str, value: str, evidence: str, text: str, number_words: NumberWords
) -> tuple[str | int | None, BiasDropReason | None]:
    """(typed value, None) or (None, reason) for a value whose evidence is in the text."""
    if key == DIRECTION:
        return (value, None) if value in DIRECTIONS else (None, "invalid_option")
    if key == CONFIDENCE:
        if not _INT_TEXT.fullmatch(value):
            return None, "invalid_option"
        number = int(value)
        if not CONFIDENCE_MIN <= number <= CONFIDENCE_MAX:
            return None, "out_of_range"
        if not number_in_evidence(number, evidence, number_words):
            return None, "evidence_not_in_text"
        return number, None
    if len(value) > TEXT_MAX_LENGTH:
        return None, "out_of_range"
    if key == KEY_LEVELS:
        issue = key_levels_issue(value, evidence, text)
    else:
        issue = text_value_issue(value, evidence, text)
    return (None, issue) if issue is not None else (value, None)


def key_levels_issue(value: str, evidence: str, normalised_text: str) -> BiasDropReason | None:
    """`key_levels` = one or more pieces of his text joined by "; ". Each piece passes the
    free-text check (text_value_issue); the pieces are distinct and occur in the text in
    this order, each after the previous one (else `invalid_option`)."""
    parts = value.split(KEY_LEVELS_SEPARATOR)
    for part in parts:
        if not part.strip():
            return "invalid_option"
        issue = text_value_issue(part, evidence, normalised_text)
        if issue is not None:
            return issue
    phrases = [normalise_for_match(part) for part in parts]
    if len(set(phrases)) != len(phrases):
        return "invalid_option"
    position = 0
    for phrase in phrases:
        found = find_phrase(phrase, normalised_text, position)
        if found == -1:
            return "invalid_option"
        position = found + len(phrase)
    return None


def _guard_one(
    symbol: str,
    key: str,
    item: Any,
    mentioned: frozenset[str],
    text: str,
    number_words: NumberWords,
) -> tuple[str | int | None, BiasDropReason | None]:
    if key not in BIAS_FIELD_KEYS:
        return None, "not_fillable"
    if symbol not in mentioned:
        return None, "symbol_not_in_text"
    if item is CONFLICT:
        return None, "invalid_option"
    value, evidence = item
    if not evidence_in_text(evidence, text):
        return None, "evidence_not_in_text"
    return _check_value(key, value, evidence, text, number_words)


def apply_bias_guards(
    config: BiasConfig,
    values: Mapping[tuple[str, str], Any],
    text: str,
    number_words: NumberWords,
) -> BiasGuardResult:
    """Drop every value the text does not support (docs/api.md "Bias extraction")."""
    symbols = config.symbol_names
    mentioned = mentioned_symbols(config, text)
    normalised = normalise_for_match(text)
    kept: dict[str, dict[str, tuple[str | int, str]]] = {}
    dropped: list[BiasDropped] = []
    for (symbol, key), item in values.items():
        if symbol not in symbols:
            dropped.append(BiasDropped(symbol, key, "not_fillable"))
            continue
        value, reason = _guard_one(symbol, key, item, mentioned, normalised, number_words)
        if reason is not None:
            dropped.append(BiasDropped(symbol, key, reason))
        elif value is not None:
            kept.setdefault(symbol, {})[key] = (value, item[1])
    entries = [_entry(symbol, kept[symbol]) for symbol in symbols if symbol in kept]
    dropped.sort(key=lambda d: (_rank(symbols, d.symbol), _rank(BIAS_FIELD_KEYS, d.key)))
    return BiasGuardResult(entries=entries, dropped=dropped)


def _entry(symbol: str, values: Mapping[str, tuple[str | int, str]]) -> BiasEntryResult:
    keys = [key for key in BIAS_FIELD_KEYS if key in values]
    return BiasEntryResult(
        symbol=symbol,
        fields={key: values[key][0] for key in keys},
        evidence={key: values[key][1] for key in keys},
    )


def _rank(order: tuple[str, ...], item: str) -> int:
    return order.index(item) if item in order else len(order)
