"""Broker server time <-> UTC (PRD 6.3, DECISIONS 2026-11-01).

MT5 reports times as epoch seconds that are really the server's *wall clock* read as if it
were UTC. FundedNext servers run on "New York close" time: server wall = New York wall + 7 h,
i.e. UTC+2 in winter and UTC+3 while America/New_York observes DST.

Ambiguous / non-existent server wall times (the hour at the US DST switch, always on a
Sunday when FX/CFD markets are closed) resolve deterministically with ``fold=0``: the offset
in effect *before* the switch is used. So the repeated hour maps to its first (DST) instant,
and a wall time inside the skipped hour is shifted forward by one hour.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
NY_CLOSE_SHIFT = timedelta(hours=7)
DETECT_TOLERANCE_SECONDS = 120
MIN_OFFSET_HOURS = -12
MAX_OFFSET_HOURS = 14


class BrokerTimeRule(enum.StrEnum):
    NY_CLOSE = "ny_close"


@dataclass(frozen=True)
class FixedOffset:
    """Server time = UTC + ``hours`` all year round."""

    hours: int


type Conversion = BrokerTimeRule | FixedOffset


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("expected a timezone-aware datetime")


def offset_hours(utc_dt: datetime, conversion: Conversion) -> int:
    """Server offset from UTC in whole hours at the given instant."""
    _require_aware(utc_dt)
    if isinstance(conversion, FixedOffset):
        return conversion.hours
    ny_offset = utc_dt.astimezone(NEW_YORK).utcoffset()
    if ny_offset is None:  # pragma: no cover - zoneinfo always yields an offset
        raise ValueError("no UTC offset for America/New_York")
    return int((ny_offset + NY_CLOSE_SHIFT).total_seconds()) // 3600


def ny_close_offset(utc_dt: datetime) -> int:
    """Offset of a "New York close" server at ``utc_dt``: +2 normally, +3 during US DST."""
    return offset_hours(utc_dt, BrokerTimeRule.NY_CLOSE)


def server_epoch_to_wall(server_seconds: int | float) -> datetime:
    """MT5 epoch (server wall time read as UTC) -> naive server wall datetime."""
    return datetime.fromtimestamp(server_seconds, UTC).replace(tzinfo=None)


def server_msc_to_wall(server_msc: int) -> datetime:
    """MT5 ``time_msc`` (milliseconds) -> naive server wall datetime, exact to the ms."""
    seconds, millis = divmod(server_msc, 1000)
    return server_epoch_to_wall(seconds) + timedelta(milliseconds=millis)


def server_to_utc(server_time: int | float | datetime, conversion: Conversion) -> datetime:
    """Convert an MT5 server time (epoch seconds or naive wall datetime) to aware UTC."""
    if isinstance(server_time, datetime):
        if server_time.tzinfo is not None:
            raise ValueError("server wall time must be naive (it is not UTC)")
        wall = server_time
    else:
        wall = server_epoch_to_wall(server_time)
    if isinstance(conversion, FixedOffset):
        return (wall - timedelta(hours=conversion.hours)).replace(tzinfo=UTC)
    # fold=0 (default): ambiguous/non-existent NY wall times use the pre-switch offset.
    ny_wall = (wall - NY_CLOSE_SHIFT).replace(tzinfo=NEW_YORK)
    return ny_wall.astimezone(UTC)


def utc_to_server(utc_dt: datetime, conversion: Conversion) -> datetime:
    """Aware UTC -> naive server wall datetime (e.g. for MT5 history query bounds)."""
    _require_aware(utc_dt)
    hours = offset_hours(utc_dt, conversion)
    return utc_dt.astimezone(UTC).replace(tzinfo=None) + timedelta(hours=hours)


def detect_offset(
    tick_epoch: int | float,
    utc_now: datetime,
    tolerance_seconds: int = DETECT_TOLERANCE_SECONDS,
) -> int | None:
    """Server offset in whole hours from a fresh tick, or None if it can't be trusted.

    None when the difference is not within ``tolerance_seconds`` of a whole hour (stale
    tick, clock skew) or the result is outside [-12, +14] (e.g. Friday's tick on a weekend).
    """
    _require_aware(utc_now)
    diff = float(tick_epoch) - utc_now.timestamp()
    hours = round(diff / 3600)
    if abs(diff - hours * 3600) > tolerance_seconds:
        return None
    if not MIN_OFFSET_HOURS <= hours <= MAX_OFFSET_HOURS:
        return None
    return hours


@dataclass(frozen=True)
class ConversionChoice:
    conversion: Conversion | None
    # True when the detected offset contradicts the configured rule (log a warning).
    mismatch: bool
    # True when a detected offset confirmed the choice for "now".
    verified: bool
    message: str


def choose_conversion(
    detected: int | None, rule: BrokerTimeRule | None, utc_now: datetime
) -> ConversionChoice:
    """Pick how to convert this account's times (DECISIONS 2026-11-01).

    Rule and detected offset agree for ``utc_now`` -> rule (correct across DST in history).
    They disagree -> fixed detected offset, ``mismatch=True``. No detection -> rule, unverified.
    """
    if rule is not None:
        expected = offset_hours(utc_now, rule)
        if detected is None:
            return ConversionChoice(
                rule, False, False, f"offset not detected; using rule {rule} (UTC{expected:+d})"
            )
        if detected == expected:
            return ConversionChoice(rule, False, True, f"rule {rule} confirmed (UTC{detected:+d})")
        return ConversionChoice(
            FixedOffset(detected),
            True,
            True,
            f"detected UTC{detected:+d} but rule {rule} expects UTC{expected:+d}; "
            f"using fixed UTC{detected:+d}",
        )
    if detected is not None:
        return ConversionChoice(
            FixedOffset(detected), False, True, f"no rule; using detected UTC{detected:+d}"
        )
    return ConversionChoice(None, False, False, "no rule and offset not detected")
