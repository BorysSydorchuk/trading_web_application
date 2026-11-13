"""`config/rules.yaml`: session windows, sync cadence, broker time and trading rules (PRD 6.3, 6.9).

Use `get_rules()`; the domain consumes `RulesConfig.sessions` (sorted `SessionWindow`s in
`RulesConfig.tz` local time, start inclusive, end exclusive) and `RulesConfig.rules`.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
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
from app.models.enums import TradingSession

RULES_FILE = "rules.yaml"

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# Session names are stored in trades.session (CHECK constraint); "outside" is implicit.
SESSION_NAMES = frozenset(s.value for s in TradingSession if s is not TradingSession.OUTSIDE)


def parse_hhmm(value: Any) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, int):
        # Unquoted 08:00 is a base-60 integer in YAML 1.1.
        raise ValueError(f'expected a quoted "HH:MM" string, got the number {value}')
    if not isinstance(value, str) or not _HHMM.match(value):
        raise ValueError(f'expected time as "HH:MM" (00:00-23:59), got {value!r}')
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def format_hhmm(value: time) -> str:
    return value.strftime("%H:%M")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeRange(_Strict):
    start: time
    end: time

    _parse = field_validator("start", "end", mode="before")(parse_hhmm)

    @field_serializer("start", "end")
    def _ser(self, value: time) -> str:
        return format_hhmm(value)

    @model_validator(mode="after")
    def _ordered(self) -> TimeRange:
        if self.start >= self.end:
            raise ValueError(
                f"start {format_hhmm(self.start)} must be before end {format_hhmm(self.end)} "
                "(ranges crossing midnight are not supported)"
            )
        return self


class _SessionSpec(TimeRange):
    entries_allowed: bool


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """One named session in local (config timezone) time: [start, end)."""

    name: str
    start: time
    end: time
    entries_allowed: bool

    def contains(self, local_time: time) -> bool:
        return self.start <= local_time < self.end


class SyncConfig(_Strict):
    trading_days: tuple[Weekday, ...] = Field(min_length=1)
    trading_hours: TimeRange
    interval_trading_seconds: int = Field(ge=5)
    interval_idle_seconds: int = Field(ge=5)
    initial_history_days: int = Field(ge=1)
    overlap_days: int = Field(ge=0)
    # Watched symbols moved to config/symbols.yaml (M5-08).

    @field_validator("trading_days")
    @classmethod
    def _unique_days(cls, value: tuple[Weekday, ...]) -> tuple[Weekday, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate weekday")
        return value


class Rule(_Strict):
    enabled: bool


class DecimalRule(Rule):
    value: Decimal


class PositiveDecimalRule(DecimalRule):
    value: Decimal = Field(gt=0)


class NegativeDecimalRule(DecimalRule):
    value: Decimal = Field(lt=0)


class CountRule(Rule):
    value: int = Field(ge=0)


class PositiveCountRule(Rule):
    value: int = Field(ge=1)


class QmNotInNyRule(Rule):
    # Option value of the journal `entry_model` field (checked against journal_fields.yaml).
    entry_model: str = Field(min_length=1)
    session: str


class RulesSet(_Strict):
    """All rules are required; switch one off with `enabled: false`."""

    max_risk_pct: PositiveDecimalRule
    daily_stop_loss_pct: NegativeDecimalRule
    daily_stop_profit_pct: PositiveDecimalRule
    weekly_stop_loss_pct: NegativeDecimalRule
    weekly_stop_profit_pct: PositiveDecimalRule
    max_trades_per_week: PositiveCountRule
    max_reentries_per_idea: CountRule
    min_planned_rr: PositiveDecimalRule
    entry_session: Rule
    qm_not_in_ny: QmNotInNyRule
    no_breakeven: Rule


RULE_KEYS: tuple[str, ...] = tuple(RulesSet.model_fields)


class DigestConfig(_Strict):
    """Digest settings (docs/api.md "Norm and deviation"); the whole section is optional."""

    # Highlight a digest metric beyond mean +- k x population SD of its norm periods.
    deviation_sigma: Decimal = Field(default=Decimal("1.0"), gt=0)


class RulesConfig(_Strict):
    timezone: str
    sessions: tuple[SessionWindow, ...]
    sync: SyncConfig
    broker_time: Literal["ny_close"]
    rules: RulesSet
    digest: DigestConfig = DigestConfig()

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r} (use an IANA name)") from None
        return value

    @field_validator("sessions", mode="before")
    @classmethod
    def _sessions(cls, value: Any) -> tuple[SessionWindow, ...]:
        if not isinstance(value, dict) or not value:
            raise ValueError("expected a mapping of session name -> {start, end, entries_allowed}")
        windows: list[SessionWindow] = []
        problems: list[str] = []
        for name, spec in value.items():
            if name not in SESSION_NAMES:
                allowed = ", ".join(sorted(SESSION_NAMES))
                problems.append(f"{name}: unknown session name (allowed: {allowed})")
                continue
            try:
                parsed = _SessionSpec.model_validate(spec)
            except ValidationError as exc:
                problems.extend(f"{name}.{p}" for p in validation_problems(exc))
                continue
            windows.append(SessionWindow(name, parsed.start, parsed.end, parsed.entries_allowed))
        windows.sort(key=lambda w: w.start)
        for prev, cur in itertools.pairwise(windows):
            if cur.start < prev.end:
                problems.append(
                    f"{cur.name} ({format_hhmm(cur.start)}-{format_hhmm(cur.end)}) overlaps "
                    f"{prev.name} ({format_hhmm(prev.start)}-{format_hhmm(prev.end)})"
                )
        if problems:
            raise ValueError("\n".join(problems))  # one problem per line
        return tuple(windows)

    @model_validator(mode="after")
    def _qm_session(self) -> RulesConfig:
        session = self.rules.qm_not_in_ny.session
        if session not in {w.name for w in self.sessions}:
            raise ValueError(f"rules.qm_not_in_ny.session: {session!r} is not a configured session")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def session(self, name: str) -> SessionWindow | None:
        return next((w for w in self.sessions if w.name == name), None)

    def to_api(self) -> dict[str, Any]:
        """JSON-ready dict for GET /api/rules (times "HH:MM", decimals as strings)."""
        data = self.model_dump(mode="json", exclude={"sessions"})
        data["sessions"] = [
            {
                "name": w.name,
                "start": format_hhmm(w.start),
                "end": format_hhmm(w.end),
                "entries_allowed": w.entries_allowed,
            }
            for w in self.sessions
        ]
        return data


def rules_path() -> Path:
    return config_dir() / RULES_FILE


def load_rules(path: Path | None = None) -> RulesConfig:
    """Parse and validate a rules file (uncached). Raises ConfigError."""
    path = path or rules_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping"])
    try:
        return RulesConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, validation_problems(exc)) from None


_cache: FileCache[RulesConfig] = FileCache(lambda: [rules_path()], load_rules)


def get_rules() -> RulesConfig:
    """Cached rules; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_rules_cache() -> None:
    _cache.clear()
