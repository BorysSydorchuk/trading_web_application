"""Request and response shapes of /api/journal-options (docs/api.md)."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

MAX_TEXT = 60
MAX_SYNONYMS = 30


def _clean_text(value: str) -> str:
    """Labels and synonyms go into the AI prompt: one plain line, no markdown code quotes."""
    text = value.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValueError(f"must be 1 to {MAX_TEXT} characters")
    if "`" in text or any(not ch.isprintable() for ch in text):
        raise ValueError("must be one line without special characters")
    return text


def _clean_synonyms(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        seen.setdefault(value.casefold(), value)
    return list(seen.values())


OptionText = Annotated[str, AfterValidator(_clean_text)]
Synonyms = Annotated[
    list[OptionText], Field(max_length=MAX_SYNONYMS), AfterValidator(_clean_synonyms)
]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionCreate(_Input):
    label: OptionText
    synonyms: Synonyms = []


class OptionUpdate(_Input):
    label: OptionText | None = None
    hidden: bool | None = None
    synonyms: Synonyms | None = None


class OptionOrder(_Input):
    values: list[str] = Field(min_length=1, max_length=200)


class OptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: str
    label: str
    hidden: bool
    synonyms: list[str]
    used_count: int


class OptionList(BaseModel):
    field: str
    options: list[OptionOut]
