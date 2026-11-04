"""`config/transcription.yaml`: glossary of trading terms for Whisper's `initial_prompt`.

Strictly validated like the other config files (unknown keys, blank, too long or duplicate
terms are errors). Reloaded automatically when the file changes.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)

TRANSCRIPTION_FILE = "transcription.yaml"
MAX_TERMS = 100
MAX_TERM_LENGTH = 40
PROMPT_PREFIX = "Торговий журнал. Терміни: "


class TranscriptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    glossary: list[str] = Field(max_length=MAX_TERMS)

    @field_validator("glossary")
    @classmethod
    def _terms(cls, value: list[str]) -> list[str]:
        problems: list[str] = []
        seen: set[str] = set()
        for index, term in enumerate(value):
            text = term.strip()
            if not text:
                problems.append(f"[{index}] must not be empty")
            elif len(text) > MAX_TERM_LENGTH:
                problems.append(f"[{index}] {text!r} is longer than {MAX_TERM_LENGTH} characters")
            elif text.casefold() in seen:
                problems.append(f"[{index}] {text!r} is listed twice")
            seen.add(text.casefold())
        if problems:
            raise ValueError("\n".join(problems))
        return [term.strip() for term in value]

    def initial_prompt(self) -> str | None:
        """Hint for Whisper: "Торговий журнал. Терміни: FVG, IFVG, …." (None when empty)."""
        if not self.glossary:
            return None
        return PROMPT_PREFIX + ", ".join(self.glossary) + "."


def transcription_path() -> Path:
    return config_dir() / TRANSCRIPTION_FILE


def load_transcription(path: Path | None = None) -> TranscriptionConfig:
    """Parse and validate the transcription file (uncached). Raises ConfigError."""
    path = path or transcription_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `glossary` list"])
    try:
        return TranscriptionConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None


_cache: FileCache[TranscriptionConfig] = FileCache(
    lambda: [transcription_path()], load_transcription
)


def get_transcription() -> TranscriptionConfig:
    """Cached config; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_transcription_cache() -> None:
    _cache.clear()
