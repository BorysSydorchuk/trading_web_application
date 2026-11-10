"""`config/symbols.yaml`: canonical symbol names and their broker names (docs/api.md M5-08).

The canonical names are used everywhere in the app (journal, analytics, bias, rules,
calculator); broker names only in MT5 calls. Each symbol lists other names brokers use for
it (`broker_names`); `firms` optionally replaces the candidates for one firm (account.firm).

Strictly validated: at least one symbol; names non-empty, printable, without spaces, at
most 50 characters; every name, broker name and firm override name belongs to exactly one symbol
(case-insensitive) and none of one symbol is the start of another symbol's (broker suffixes
match by prefix); firm overrides name known symbols, each at most once per firm, with a
non-empty list; firm names unique case-insensitively. No extra keys. Reloaded when the file changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

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

SYMBOLS_FILE = "symbols.yaml"
MAX_SYMBOL_LENGTH = 50  # trades.symbol / symbol_specs.symbol are VARCHAR(50)


def _clean_name(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("must not be empty")
    if not text.replace(" ", "").isprintable():  # control/format chars, NBSP, ZWSP
        raise ValueError(f"{text!r} must contain only printable characters")
    if any(char.isspace() for char in text):
        raise ValueError(f"{text!r} must not contain spaces")
    if len(text) > MAX_SYMBOL_LENGTH:
        raise ValueError(f"{text!r} is longer than {MAX_SYMBOL_LENGTH} characters")
    return text


def _clean_names(values: tuple[str, ...]) -> tuple[str, ...]:
    problems: list[str] = []
    cleaned: list[str] = []
    for index, value in enumerate(values):
        try:
            cleaned.append(_clean_name(value))
        except ValueError as exc:
            problems.append(f"[{index}] {exc}")
    if problems:
        raise ValueError("\n".join(problems))
    return tuple(cleaned)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalSymbol(_Strict):
    name: StrictStr
    broker_names: tuple[StrictStr, ...] = ()

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("broker_names")
    @classmethod
    def _brokers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_names(value)


FirmOverride = dict[StrictStr, Annotated[tuple[StrictStr, ...], Field(min_length=1)]]


def _owner_problems(config: SymbolsConfig) -> list[str]:
    """Every name belongs to one symbol; within a symbol a name is listed once (overrides
    may repeat their own symbol's names)."""
    problems: list[str] = []
    owner: dict[str, str] = {}
    for index, entry in enumerate(config.symbols):
        seen: set[str] = set()
        for pos, word in enumerate((entry.name, *entry.broker_names)):
            key = word.casefold()
            loc = (
                f"symbols[{index}].name"
                if pos == 0
                else f"symbols[{index}].broker_names[{pos - 1}]"
            )
            if owner.get(key, entry.name) != entry.name:
                problems.append(f"{loc}: {word!r} already means {owner[key]!r}")
            elif key in seen:
                problems.append(f"{loc}: {word!r} is listed twice")
            seen.add(key)
            owner.setdefault(key, entry.name)
    for firm, overrides in config.firms.items():
        for name, words in overrides.items():
            for pos, word in enumerate(words):
                key = word.casefold()
                taken = owner.get(key, name)
                if taken.casefold() != name.casefold():
                    problems.append(f"firms.{firm}.{name}[{pos}]: {word!r} already means {taken!r}")
                owner.setdefault(key, name)
    return problems


def _prefix_problems(config: SymbolsConfig) -> list[str]:
    words: list[tuple[str, str]] = []  # (word, canonical name)
    for entry in config.symbols:
        words.extend((w, entry.name) for w in (entry.name, *entry.broker_names))
    for overrides in config.firms.values():
        for name, override in overrides.items():
            words.extend((w, name) for w in override)
    problems: list[str] = []
    reported: set[tuple[str, str]] = set()
    for word, symbol in words:
        for other, other_symbol in words:
            pair = (word.casefold(), other.casefold())
            if (
                other_symbol.casefold() != symbol.casefold()
                and pair[1] != pair[0]
                and pair[1].startswith(pair[0])
                and pair not in reported
            ):
                reported.add(pair)
                problems.append(
                    f"{word!r} ({symbol}) is the start of {other!r} ({other_symbol}); "
                    "broker symbols match by prefix"
                )
    return problems


def _firm_problems(config: SymbolsConfig) -> list[str]:
    problems: list[str] = []
    known = {s.name.casefold() for s in config.symbols}
    seen: set[str] = set()
    for firm, overrides in config.firms.items():
        folded = firm.strip().casefold()
        if not folded:
            problems.append("firms: a firm name must not be empty")
        elif folded in seen:
            problems.append(f"firms.{firm}: {firm!r} is listed twice")
        seen.add(folded)
        for name in overrides:
            if name.casefold() not in known:
                problems.append(f"firms.{firm}.{name}: {name!r} is not a symbol in symbols")
    return problems


class SymbolsConfig(_Strict):
    symbols: Annotated[tuple[CanonicalSymbol, ...], Field(min_length=1)]
    firms: dict[StrictStr, FirmOverride] = Field(default_factory=dict)

    @field_validator("firms")
    @classmethod
    def _override_names(cls, value: dict[str, FirmOverride]) -> dict[str, FirmOverride]:
        problems: list[str] = []
        cleaned: dict[str, FirmOverride] = {}
        for firm, overrides in value.items():
            cleaned[firm] = {}
            seen: set[str] = set()
            for name, words in overrides.items():
                key = name.strip().casefold()
                if key in seen:  # before stripping collapses the two keys
                    problems.append(f"{firm}.{name}: {name.strip()!r} is listed twice")
                    continue
                seen.add(key)
                try:
                    cleaned[firm][name.strip()] = _clean_names(words)
                except ValueError as exc:
                    problems.extend(f"{firm}.{name}{line}" for line in str(exc).splitlines())
        if problems:
            raise ValueError("\n".join(problems))
        return cleaned

    @model_validator(mode="after")
    def _cross_checks(self) -> SymbolsConfig:
        problems = _firm_problems(self)
        if not problems:  # owner/prefix checks need known override symbols
            problems = _owner_problems(self) + _prefix_problems(self)
        if problems:
            raise ValueError("\n".join(problems))
        return self

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.symbols)

    def symbol(self, name: str) -> CanonicalSymbol | None:
        """The symbol called name (case-insensitive, names are unique that way)."""
        folded = name.casefold()
        return next((s for s in self.symbols if s.name.casefold() == folded), None)

    def firm_override(self, firm: str | None) -> FirmOverride | None:
        """The override of ``firm`` (case-insensitive, stripped), or None."""
        if firm is None:
            return None
        folded = firm.strip().casefold()
        return next((o for f, o in self.firms.items() if f.strip().casefold() == folded), None)


def symbols_path() -> Path:
    return config_dir() / SYMBOLS_FILE


def load_symbols(path: Path | None = None) -> SymbolsConfig:
    """Parse and validate a symbols file (uncached). Raises ConfigError."""
    path = path or symbols_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with `symbols` (and `firms`)"])
    try:
        return SymbolsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None


_cache: FileCache[SymbolsConfig] = FileCache(lambda: [symbols_path()], load_symbols)


def get_symbols_config() -> SymbolsConfig:
    """Cached config; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_symbols_cache() -> None:
    _cache.clear()
