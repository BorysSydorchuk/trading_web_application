"""`config/firms.yaml`: prop-firm rules (docs/api.md "Firm rules from config: KeyFunding").

Per firm: daily loss % and static max loss % of the account size, profit targets per phase,
the daily basis and the daily reset (wall time in a zone), and the fields still to be verified
with the firm (`to_verify`). Accounts are matched by `accounts.firm`, case-insensitive with
spaces, `-` and `_` ignored ("Key Funding" = "KeyFunding").

Strictly validated: no extra keys, percents in (0, 100), `daily_reset` as HH:MM, a known
reset zone (`server` or an IANA name), `to_verify` from the known field names without
duplicates, firm names unique after the matching normalisation. A missing file means no firms;
a broken file is a ConfigError (never silently ignored). Reloaded when the file changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
)

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)

FIRMS_FILE = "firms.yaml"
SERVER_ZONE = "server"
_HH_MM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_NAME_NOISE = re.compile(r"[\s\-_]+")

Percent = Annotated[Decimal, Field(gt=0, lt=100, allow_inf_nan=False)]
VerifyField = Literal[
    "daily_loss_pct",
    "max_loss_pct",
    "max_loss_type",
    "profit_target_pct",
    "daily_basis",
    "daily_reset",
    "reset_timezone",
]


def normalize_firm(name: str) -> str:
    """Matching key of a firm name: case, spaces, `-` and `_` ignored."""
    return _NAME_NOISE.sub("", name).casefold()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProfitTargets(_Strict):
    phase_1: Percent | None = None
    phase_2: Percent | None = None

    def for_phase(self, phase: str) -> Decimal | None:
        """The target of ``phase`` (phase_1 / phase_2); a funded account has none."""
        return {"phase_1": self.phase_1, "phase_2": self.phase_2}.get(phase)


class FirmRule(_Strict):
    daily_loss_pct: Percent
    max_loss_pct: Percent
    max_loss_type: Literal["static"] = "static"
    profit_target_pct: ProfitTargets = ProfitTargets()
    daily_basis: Literal["balance"] = "balance"
    daily_reset: StrictStr = "00:00"
    reset_timezone: StrictStr = SERVER_ZONE
    to_verify: tuple[VerifyField, ...] = ()

    @field_validator("daily_reset")
    @classmethod
    def _reset(cls, value: str) -> str:
        if _HH_MM.fullmatch(value) is None:
            raise ValueError(f"{value!r} must be a wall time HH:MM (00:00 - 23:59)")
        return value

    @field_validator("reset_timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        if value == SERVER_ZONE:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError(f"{value!r} is not `server` or a known IANA time zone") from None
        return value

    @field_validator("to_verify")
    @classmethod
    def _verify(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        dupes = sorted({item for item in value if value.count(item) > 1})
        if dupes:
            raise ValueError(f"listed twice: {', '.join(dupes)}")
        return value

    @property
    def daily_reset_time(self) -> time:
        hours, minutes = self.daily_reset.split(":")
        return time(int(hours), int(minutes))


@dataclass(frozen=True)
class FirmEntry:
    name: str  # the key as written in firms.yaml
    rule: FirmRule


class FirmsConfig(_Strict):
    firms: dict[StrictStr, FirmRule] = Field(default_factory=dict)

    @field_validator("firms")
    @classmethod
    def _names(cls, value: dict[str, FirmRule]) -> dict[str, FirmRule]:
        problems: list[str] = []
        seen: dict[str, str] = {}
        for name in value:
            key = normalize_firm(name)
            if not key:
                problems.append(f"{name!r}: a firm name must not be empty")
            elif key in seen:
                problems.append(f"{name!r} is listed twice (same firm as {seen[key]!r})")
            seen.setdefault(key, name)
        if problems:
            raise ValueError("\n".join(problems))
        return value

    def match(self, firm: str | None) -> FirmEntry | None:
        """The entry of an account's ``firm`` text, or None."""
        if firm is None:
            return None
        key = normalize_firm(firm)
        if not key:
            return None
        return next(
            (
                FirmEntry(name, rule)
                for name, rule in self.firms.items()
                if normalize_firm(name) == key
            ),
            None,
        )


def firms_path() -> Path:
    return config_dir() / FIRMS_FILE


def load_firms(path: Path | None = None) -> FirmsConfig:
    """Parse and validate a firms file (uncached). A missing file is no firms.
    Raises ConfigError for anything else wrong."""
    path = path or firms_path()
    if not path.exists():
        return FirmsConfig()
    raw = read_yaml(path)
    if raw is None:
        return FirmsConfig()
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with `firms`"])
    try:
        return FirmsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None


_cache: FileCache[FirmsConfig] = FileCache(lambda: [firms_path()], load_firms)


def get_firms_config() -> FirmsConfig:
    """Cached config; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_firms_cache() -> None:
    _cache.clear()
