"""`config/extraction.yaml`: the number words accepted for `int` values by the AI extraction.

Strictly validated: keys are non-negative integers, each a non-empty list of words; words
are normalised like the texts they are matched against (casefold, yo -> ie, apostrophe
variants -> ', whitespace collapsed, edge apostrophes dropped), and a word may not mean two
different numbers. The compiled matcher (`NumberWords`) is cached until the file changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)
from app.domain.number_words import NumberWords, normalise_number_word

EXTRACTION_FILE = "extraction.yaml"

_Word = Annotated[StrictStr, Field(min_length=1)]


class _ExtractionFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number_words: dict[
        Annotated[StrictInt, Field(ge=0)], Annotated[list[_Word], Field(min_length=1)]
    ]


def extraction_path() -> Path:
    return config_dir() / EXTRACTION_FILE


def _word_map(number_words: dict[int, list[str]]) -> tuple[dict[str, int], list[str]]:
    """(normalised word -> number, problems)."""
    words: dict[str, int] = {}
    problems: list[str] = []
    for number, raw_words in number_words.items():
        for raw in raw_words:
            word = normalise_number_word(raw)
            if not any(char.isalpha() for char in word):
                problems.append(f"number_words[{number}]: {raw!r} has no letters")
                continue
            other = words.setdefault(word, number)
            if other != number:
                problems.append(
                    f"number_words[{number}]: {raw!r} already means {other} "
                    "(a word may not mean two different numbers)"
                )
    return words, problems


def load_number_words(path: Path | None = None) -> NumberWords:
    """Parse and validate an extraction file (uncached). Raises ConfigError."""
    path = path or extraction_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `number_words` mapping"])
    try:
        parsed = _ExtractionFile.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None
    words, problems = _word_map(parsed.number_words)
    if problems:
        raise ConfigError(path, problems)
    return NumberWords(words)


_cache: FileCache[NumberWords] = FileCache(lambda: [extraction_path()], load_number_words)


def get_number_words() -> NumberWords:
    """Cached number words; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_extraction_cache() -> None:
    _cache.clear()
