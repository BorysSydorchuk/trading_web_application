"""Term normalization of voice-note transcripts (docs/api.md "Transcript normalization").

Deterministic replacements from `config/transcript_glossary.yaml`, e.g. "ФВГ" -> "FVG":
- case-insensitive;
- on word boundaries: no letter, digit or underscore (Cyrillic and Latin alike) right
  before or after the match, so "ФВГшка" or "АФВГ" are left alone;
- the longest `from` wins at a position;
- one pass: replaced text is never matched again (a `to` can't trigger another rule);
- `to` is inserted exactly as written.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GlossaryRule:
    to: str
    sources: tuple[str, ...]  # the `from` strings


def _compile(rules: tuple[GlossaryRule, ...]) -> tuple[re.Pattern[str] | None, tuple[str, ...]]:
    """One alternation, longest `from` first; group i+1 matches -> targets[i]."""
    pairs = sorted(
        ((source, rule.to) for rule in rules for source in rule.sources),
        key=lambda pair: -len(pair[0]),
    )
    if not pairs:
        return None, ()
    alternation = "|".join(f"({re.escape(source)})" for source, _ in pairs)
    # \w is Unicode-aware: Latin and Cyrillic letters, digits and `_` all count.
    pattern = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)
    return pattern, tuple(to for _, to in pairs)


@dataclass(frozen=True)
class TranscriptGlossary:
    """Validated replacement rules with their compiled matcher (built once)."""

    rules: tuple[GlossaryRule, ...]
    _pattern: re.Pattern[str] | None = field(init=False, repr=False, compare=False)
    _targets: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        pattern, targets = _compile(self.rules)
        object.__setattr__(self, "_pattern", pattern)
        object.__setattr__(self, "_targets", targets)

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, Iterable[str]]]) -> TranscriptGlossary:
        return cls(tuple(GlossaryRule(to, tuple(sources)) for to, sources in pairs))

    def apply(self, text: str) -> tuple[str, int]:
        """(normalized text, number of replacements)."""
        if self._pattern is None:
            return text, 0
        targets = self._targets

        def _target(match: re.Match[str]) -> str:
            index = match.lastindex
            return targets[index - 1] if index is not None else match.group(0)

        return self._pattern.subn(_target, text)


def normalize_transcript(text: str, glossary: TranscriptGlossary) -> str:
    """The transcript with every glossary term replaced (see module docstring)."""
    return glossary.apply(text)[0]
