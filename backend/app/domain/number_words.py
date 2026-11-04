"""The `int` guard of the AI extraction: is the value said in its evidence? Pure.

A value counts when the evidence says it as a standalone number or as a number word from
`config/extraction.yaml` (`NumberWords`, built by the config loader and passed in), and the
evidence says no other number: "4 or 5", "four or five", "4 - 5" are ambiguous, so neither
value is kept (PRD 6.5: ambiguous -> left empty).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.domain.text_match import normalise_for_match

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


def normalise_number_word(word: str) -> str:
    """A configured word in the form it is matched in: normalise_for_match, edge apostrophes
    dropped (the evidence gets the same treatment)."""
    return _EDGE_APOSTROPHE.sub("", normalise_for_match(word)).strip()


@dataclass(frozen=True)
class NumberWords:
    """Normalised number word/phrase -> the number it means; the regex is compiled once."""

    words: Mapping[str, int]
    _pattern: re.Pattern[str] | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        frozen = MappingProxyType(dict(self.words))
        object.__setattr__(self, "words", frozen)
        # Longest first, so a phrase wins over a word it contains.
        alternatives = sorted(frozen, key=lambda w: (-len(w), w))
        pattern = (
            re.compile(r"(?<![\w'])(" + "|".join(map(re.escape, alternatives)) + r")(?![\w'])")
            if alternatives
            else None
        )
        object.__setattr__(self, "_pattern", pattern)

    def to_digits(self, normalised: str) -> str:
        """Every whole-word number word in an already normalised text replaced by its digits."""
        if self._pattern is None:
            return normalised
        return self._pattern.sub(lambda m: str(self.words[m.group(1)]), normalised)


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


def number_in_evidence(value: int, evidence: str, number_words: NumberWords) -> bool:
    """The int value is said in its evidence (a standalone number or a configured number
    word, whole words, case-insensitive) and no other standalone number is."""
    quote = number_words.to_digits(_EDGE_APOSTROPHE.sub("", normalise_for_match(evidence)))
    return set(_standalone_numbers(quote)) == {value}
