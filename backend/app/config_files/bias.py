"""`config/bias.yaml`: bias symbols with spoken aliases and reminder windows (docs/api.md M4).

Strictly validated: at least one symbol; symbol names non-empty, without spaces, at most 50
characters, unique case-insensitively and none the prefix of another (kept from M4; since
M5-08 trades match a bias symbol exactly by canonical name and `check_config_files` requires
every bias symbol to be a symbols.yaml name); aliases non-empty and unique across the whole
file case-insensitively (also against symbol names of other symbols); reminders exactly
`pre_london` and `pre_ny`, each a quoted "HH:MM" `from` before `until`. No extra keys.
Reloaded when the file changes.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)
from app.config_files.rules import format_hhmm, parse_hhmm
from app.config_files.symbols import get_symbols_config
from app.models.enums import BiasKind

BIAS_FILE = "bias.yaml"
MAX_SYMBOL_LENGTH = 50  # bias_entries.symbol is VARCHAR(50)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BiasSymbol(_Strict):
    symbol: StrictStr
    aliases: tuple[StrictStr, ...]

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        if any(char.isspace() for char in text):
            raise ValueError(f"{text!r} must not contain spaces")
        if len(text) > MAX_SYMBOL_LENGTH:
            raise ValueError(f"{text!r} is longer than {MAX_SYMBOL_LENGTH} characters")
        return text

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        stripped = tuple(alias.strip() for alias in value)
        empty = [str(i) for i, alias in enumerate(stripped) if not alias]
        if empty:
            raise ValueError(f"alias [{', '.join(empty)}] must not be empty")
        return stripped


class ReminderWindow(_Strict):
    """Brussels local time window [from, until) on weekdays."""

    start: Annotated[time, Field(alias="from")]
    until: time

    _parse = field_validator("start", "until", mode="before")(parse_hhmm)

    @model_validator(mode="after")
    def _ordered(self) -> ReminderWindow:
        if self.start >= self.until:
            raise ValueError(
                f"from {format_hhmm(self.start)} must be before until {format_hhmm(self.until)}"
            )
        return self

    def contains(self, local_time: time) -> bool:
        return self.start <= local_time < self.until

    def to_api(self) -> dict[str, str]:
        return {"from": format_hhmm(self.start), "until": format_hhmm(self.until)}


class BiasReminders(_Strict):
    pre_london: ReminderWindow
    pre_ny: ReminderWindow


def _name_problems(symbols: tuple[BiasSymbol, ...]) -> list[str]:
    problems: list[str] = []
    names = [s.symbol.casefold() for s in symbols]
    for index, name in enumerate(names):
        if name in names[:index]:
            problems.append(f"symbols[{index}].symbol: {symbols[index].symbol!r} is listed twice")
            continue
        for other_index, other in enumerate(names):
            if other_index != index and other != name and other.startswith(name):
                problems.append(
                    f"symbols[{index}].symbol: {symbols[index].symbol!r} is the start of "
                    f"{symbols[other_index].symbol!r} (no symbol may be the start of another)"
                )
    return problems


def _alias_problems(symbols: tuple[BiasSymbol, ...]) -> list[str]:
    problems: list[str] = []
    # casefolded word -> symbol it belongs to; symbol names count as taken words.
    owner: dict[str, str] = {s.symbol.casefold(): s.symbol for s in symbols}
    seen_aliases: set[str] = set()
    for index, entry in enumerate(symbols):
        for pos, alias in enumerate(entry.aliases):
            key = alias.casefold()
            loc = f"symbols[{index}].aliases[{pos}]"
            # Another symbol's word first, so the message names that symbol.
            if owner.get(key, entry.symbol) != entry.symbol:
                problems.append(f"{loc}: {alias!r} already means {owner[key]!r}")
            elif key in seen_aliases:
                problems.append(f"{loc}: {alias!r} is listed twice")
            seen_aliases.add(key)
            owner.setdefault(key, entry.symbol)
    return problems


class BiasConfig(_Strict):
    symbols: Annotated[tuple[BiasSymbol, ...], Field(min_length=1)]
    reminders: BiasReminders

    @property
    def symbol_names(self) -> tuple[str, ...]:
        return tuple(s.symbol for s in self.symbols)

    def reminder(self, kind: BiasKind) -> ReminderWindow | None:
        """Reminder window of a daily kind; None for weekly/monthly."""
        if kind is BiasKind.PRE_LONDON:
            return self.reminders.pre_london
        if kind is BiasKind.PRE_NY:
            return self.reminders.pre_ny
        return None

    def to_api(self) -> dict[str, Any]:
        return {
            "symbols": [{"symbol": s.symbol, "aliases": list(s.aliases)} for s in self.symbols],
            "reminders": {
                "pre_london": self.reminders.pre_london.to_api(),
                "pre_ny": self.reminders.pre_ny.to_api(),
            },
            "kinds": [kind.value for kind in BiasKind],
        }


def bias_path() -> Path:
    return config_dir() / BIAS_FILE


def load_bias(path: Path | None = None) -> BiasConfig:
    """Parse and validate a bias file (uncached). Raises ConfigError."""
    path = path or bias_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with `symbols` and `reminders`"])
    try:
        parsed = BiasConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None
    problems = _name_problems(parsed.symbols) + _alias_problems(parsed.symbols)
    if problems:
        raise ConfigError(path, problems)
    return parsed


_cache: FileCache[BiasConfig] = FileCache(lambda: [bias_path()], load_bias)


def canonical_symbol_problems(config: BiasConfig) -> list[str]:
    """Bias symbols that are not canonical names of symbols.yaml (M5-08). An unreadable
    symbols.yaml is reported by its own loader, so the check is skipped then."""
    try:
        symbols = get_symbols_config()
    except ConfigError:
        return []
    known = set(symbols.names)
    return [
        f"symbols[{index}].symbol: {name!r} is not a symbol name in symbols.yaml "
        f"(known: {', '.join(symbols.names)})"
        for index, name in enumerate(config.symbol_names)
        if name not in known
    ]


def get_bias_config() -> BiasConfig:
    """Cached config; reloaded automatically when the file changes. Raises ConfigError, also
    when a bias symbol is not a symbols.yaml name (checked on every call: both files reload
    at runtime)."""
    config = _cache.get()
    problems = canonical_symbol_problems(config)
    if problems:
        raise ConfigError(bias_path(), problems)
    return config


def clear_bias_cache() -> None:
    _cache.clear()
