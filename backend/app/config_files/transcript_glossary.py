"""`config/transcript_glossary.yaml`: term replacements applied to voice-note transcripts.

Strictly validated (docs/api.md "Transcript normalization"): a `replacements` list of at
most 200 rules, each with a non-empty `to` and a non-empty list of unique, non-empty `from`
strings that contain a letter or digit; the same `from` (case-insensitive) under two
different `to` is an error. Values are stripped. Reloaded automatically when the file changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)
from app.domain.transcript_glossary import TranscriptGlossary

TRANSCRIPT_GLOSSARY_FILE = "transcript_glossary.yaml"
MAX_RULES = 200


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    to: StrictStr
    sources: Annotated[list[StrictStr], Field(alias="from", min_length=1)]


class _GlossaryFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    replacements: Annotated[list[_Rule], Field(max_length=MAX_RULES)]


def transcript_glossary_path() -> Path:
    return config_dir() / TRANSCRIPT_GLOSSARY_FILE


def _source_problems(
    index: int, raw_sources: list[str], seen: dict[str, str], to: str
) -> tuple[list[str], list[str]]:
    """(stripped sources, problems) of one rule; `seen` maps casefolded from -> its `to`."""
    sources: list[str] = []
    problems: list[str] = []
    in_list: set[str] = set()
    for pos, raw in enumerate(raw_sources):
        source = raw.strip()
        loc = f"replacements[{index}].from[{pos}]"
        key = source.casefold()
        if not source:
            problems.append(f"{loc}: must not be empty")
        elif not any(char.isalnum() for char in source):
            problems.append(f"{loc}: {raw!r} has no letter or digit")
        elif source in in_list:
            problems.append(f"{loc}: {raw!r} is listed twice")
        elif key in seen and seen[key] != to:
            problems.append(f"{loc}: {raw!r} already maps to {seen[key]!r}")
        else:
            # A case variant under the same `to` (e.g. ФВГ, фвг) is allowed and harmless.
            in_list.add(source)
            seen[key] = to
            sources.append(source)
    return sources, problems


def _glossary(parsed: _GlossaryFile) -> tuple[TranscriptGlossary, list[str]]:
    problems: list[str] = []
    seen: dict[str, str] = {}
    pairs: list[tuple[str, list[str]]] = []
    for index, rule in enumerate(parsed.replacements):
        to = rule.to.strip()
        if not to:
            problems.append(f"replacements[{index}].to: must not be empty")
        sources, source_problems = _source_problems(index, rule.sources, seen, to)
        problems.extend(source_problems)
        pairs.append((to, sources))
    return TranscriptGlossary.from_pairs(pairs), problems


def load_transcript_glossary(path: Path | None = None) -> TranscriptGlossary:
    """Parse and validate a glossary file (uncached). Raises ConfigError."""
    path = path or transcript_glossary_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `replacements` list"])
    try:
        parsed = _GlossaryFile.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None
    glossary, problems = _glossary(parsed)
    if problems:
        raise ConfigError(path, problems)
    return glossary


_cache: FileCache[TranscriptGlossary] = FileCache(
    lambda: [transcript_glossary_path()], load_transcript_glossary
)


def get_transcript_glossary() -> TranscriptGlossary:
    """Cached glossary; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_transcript_glossary_cache() -> None:
    _cache.clear()
