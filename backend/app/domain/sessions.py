"""Session classification and trading-time checks in Brussels time (PRD 6.3).

Windows come from config/rules.yaml via the config loader; anything with ``name``, ``start``,
``end`` and ``entries_allowed`` fits the ``SessionWindow`` protocol. Start is inclusive, end
exclusive. A window with start > end wraps past midnight.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Brussels"
OUTSIDE = "outside"
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class SessionWindow(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def start(self) -> time: ...
    @property
    def end(self) -> time: ...
    @property
    def entries_allowed(self) -> bool: ...


@dataclass(frozen=True)
class Window:
    """Minimal concrete SessionWindow (tests, defaults)."""

    name: str
    start: time
    end: time
    entries_allowed: bool


def to_local(utc_dt: datetime, tz: str = DEFAULT_TZ) -> datetime:
    if utc_dt.tzinfo is None or utc_dt.utcoffset() is None:
        raise ValueError("expected a timezone-aware datetime")
    return utc_dt.astimezone(ZoneInfo(tz))


def _in_window(t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # wraps midnight


def find_window[W: SessionWindow](
    utc_dt: datetime, windows: Iterable[W], tz: str = DEFAULT_TZ
) -> W | None:
    """First window containing the local wall time of ``utc_dt``, or None."""
    local = to_local(utc_dt, tz).time().replace(tzinfo=None)
    for window in windows:
        if _in_window(local, window.start, window.end):
            return window
    return None


def classify(utc_dt: datetime, windows: Iterable[SessionWindow], tz: str = DEFAULT_TZ) -> str:
    """Session name (london/premarket/ny/...) or ``"outside"``."""
    window = find_window(utc_dt, windows, tz)
    return window.name if window is not None else OUTSIDE


def entries_allowed(
    utc_dt: datetime, windows: Iterable[SessionWindow], tz: str = DEFAULT_TZ
) -> bool:
    window = find_window(utc_dt, windows, tz)
    return window is not None and window.entries_allowed


def brussels_weekday_hour(utc_dt: datetime, tz: str = DEFAULT_TZ) -> tuple[int, int]:
    """(weekday 0 = Monday, hour 0-23) in local time, as stored in trades.weekday/hour."""
    local = to_local(utc_dt, tz)
    return local.weekday(), local.hour


def _weekday_index(day: int | str) -> int:
    if isinstance(day, int):
        if not 0 <= day <= 6:
            raise ValueError(f"weekday out of range: {day}")
        return day
    key = day.strip().lower()[:3]
    if key not in WEEKDAY_KEYS:
        raise ValueError(f"unknown weekday: {day!r}")
    return WEEKDAY_KEYS.index(key)


def is_trading_time(
    utc_dt: datetime,
    days: Iterable[int | str],
    start: time,
    end: time,
    tz: str = DEFAULT_TZ,
) -> bool:
    """True on a trading day (0 = Monday or "mon".."sun") within [start, end) local time."""
    local = to_local(utc_dt, tz)
    allowed = {_weekday_index(d) for d in days}
    return local.weekday() in allowed and _in_window(local.time().replace(tzinfo=None), start, end)
