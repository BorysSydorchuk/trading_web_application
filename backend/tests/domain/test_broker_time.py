from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.broker_time import (
    BrokerTimeRule,
    FixedOffset,
    choose_conversion,
    detect_offset,
    ny_close_offset,
    server_epoch_to_wall,
    server_msc_to_wall,
    server_to_utc,
    utc_to_server,
)
from app.domain.sessions import brussels_weekday_hour, to_local

NY = BrokerTimeRule.NY_CLOSE


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def wall(*args: int) -> datetime:
    return utc(*args).replace(tzinfo=None)


def wall_epoch(*args: int) -> int:
    """Epoch as MT5 returns it: server wall time read as UTC."""
    return int(utc(*args).timestamp())


# --- rule offset --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (utc(2026, 1, 15, 12), 2),  # winter
        (utc(2026, 7, 15, 12), 3),  # US summer
        # US DST start 2026-03-08 02:00 EST = 07:00 UTC
        (utc(2026, 3, 8, 6, 59, 59), 2),
        (utc(2026, 3, 8, 7), 3),
        # US DST end 2026-11-01 02:00 EDT = 06:00 UTC
        (utc(2026, 11, 1, 5, 59, 59), 3),
        (utc(2026, 11, 1, 6), 2),
        # EU/US gap weeks: Brussels already/still on its other offset, broker is not
        (utc(2026, 3, 20, 9), 3),  # US summer, Brussels winter (+1)
        (utc(2026, 10, 28, 9), 3),  # US summer, Brussels winter again (+1)
        (utc(2026, 3, 30, 9), 3),  # both summer
        (utc(2026, 11, 2, 9), 2),  # both winter
    ],
)
def test_ny_close_offset(instant: datetime, expected: int) -> None:
    assert ny_close_offset(instant) == expected


def test_offset_requires_aware() -> None:
    with pytest.raises(ValueError, match="aware"):
        ny_close_offset(datetime(2026, 1, 1))  # noqa: DTZ001


# --- server -> UTC ------------------------------------------------------------------------


def test_epoch_helpers() -> None:
    assert server_epoch_to_wall(wall_epoch(2026, 3, 16, 10, 30)) == wall(2026, 3, 16, 10, 30)
    assert server_msc_to_wall(wall_epoch(2026, 3, 16, 10, 30) * 1000 + 250) == wall(
        2026, 3, 16, 10, 30
    ) + timedelta(milliseconds=250)


def test_gap_week_march_deal_lands_in_london_session() -> None:
    # Monday in the US-summer / EU-winter gap: broker +3, Brussels +1.
    t = server_to_utc(wall_epoch(2026, 3, 16, 10, 30), NY)
    assert t == utc(2026, 3, 16, 7, 30)
    assert to_local(t).hour == 8  # 08:30 Brussels = London; a fixed +2 would give 09:30
    assert server_to_utc(wall_epoch(2026, 3, 16, 10, 30), FixedOffset(2)) == utc(2026, 3, 16, 8, 30)


def test_gap_week_october() -> None:
    # Wed 2026-10-28: Brussels back on +1 since Oct 25, broker still +3 until Nov 1.
    t = server_to_utc(wall(2026, 10, 28, 16, 0), NY)
    assert t == utc(2026, 10, 28, 13, 0)
    assert brussels_weekday_hour(t) == (2, 14)


def test_normal_weeks() -> None:
    assert server_to_utc(wall(2026, 1, 14, 10, 0), NY) == utc(2026, 1, 14, 8, 0)
    assert server_to_utc(wall(2026, 6, 10, 10, 0), NY) == utc(2026, 6, 10, 7, 0)
    # EU summer + US summer: Brussels +2, broker +3 -> 1 h apart as usual
    assert to_local(server_to_utc(wall(2026, 6, 10, 10, 0), NY)).hour == 9


def test_deal_crossing_us_dst_end() -> None:
    # Opened Fri 2026-10-30 (broker +3), closed Mon 2026-11-02 (broker +2).
    opened = server_to_utc(wall(2026, 10, 30, 15, 0), NY)
    closed = server_to_utc(wall(2026, 11, 2, 10, 0), NY)
    assert opened == utc(2026, 10, 30, 12, 0)
    assert closed == utc(2026, 11, 2, 8, 0)
    assert closed - opened == timedelta(days=2, hours=20)  # wall diff would say 2d 19h


def test_deal_crossing_us_dst_start() -> None:
    opened = server_to_utc(wall(2026, 3, 6, 20, 0), NY)  # +2
    closed = server_to_utc(wall(2026, 3, 9, 10, 0), NY)  # +3
    assert opened == utc(2026, 3, 6, 18, 0)
    assert closed == utc(2026, 3, 9, 7, 0)


def test_ambiguous_hour_uses_pre_switch_offset() -> None:
    # Server 08:30 on 2026-11-01 = NY 01:30, which happens twice; fold=0 -> EDT (+3).
    assert server_to_utc(wall(2026, 11, 1, 8, 30), NY) == utc(2026, 11, 1, 5, 30)
    # Just outside the ambiguous hour
    assert server_to_utc(wall(2026, 11, 1, 7, 59), NY) == utc(2026, 11, 1, 4, 59)
    assert server_to_utc(wall(2026, 11, 1, 9, 0), NY) == utc(2026, 11, 1, 7, 0)


def test_nonexistent_hour_uses_pre_switch_offset() -> None:
    # Server 09:30 on 2026-03-08 = NY 02:30, skipped; pre-switch EST (+2) is used.
    assert server_to_utc(wall(2026, 3, 8, 9, 30), NY) == utc(2026, 3, 8, 7, 30)
    assert server_to_utc(wall(2026, 3, 8, 10, 0), NY) == utc(2026, 3, 8, 7, 0)


def test_round_trip_across_transitions() -> None:
    for start in (utc(2026, 3, 7), utc(2026, 3, 28), utc(2026, 10, 24), utc(2026, 10, 31)):
        for minutes in range(0, 3 * 24 * 60, 15):
            t = start + timedelta(minutes=minutes)
            server = utc_to_server(t, NY)
            back = server_to_utc(server, NY)
            in_second_ambiguous_hour = utc(2026, 11, 1, 6) <= t < utc(2026, 11, 1, 7)
            if in_second_ambiguous_hour:
                assert back == t - timedelta(hours=1)
            else:
                assert back == t


def test_fixed_offset_round_trip() -> None:
    t = utc(2026, 11, 1, 6, 30)
    assert utc_to_server(t, FixedOffset(2)) == wall(2026, 11, 1, 8, 30)
    assert server_to_utc(wall(2026, 11, 1, 8, 30), FixedOffset(2)) == t


def test_server_to_utc_rejects_aware() -> None:
    with pytest.raises(ValueError, match="naive"):
        server_to_utc(utc(2026, 1, 1), NY)


# --- detection ----------------------------------------------------------------------------


def test_detect_offset_fresh_tick() -> None:
    now = utc(2026, 11, 2, 9, 0, 0)
    assert detect_offset(now.timestamp() + 2 * 3600 - 3, now) == 2
    assert detect_offset(now.timestamp() + 3 * 3600 + 119, now) == 3
    assert detect_offset(now.timestamp() - 5 * 3600, now) == -5


def test_detect_offset_not_near_whole_hour() -> None:
    now = utc(2026, 11, 2, 9, 0, 0)
    assert detect_offset(now.timestamp() + 2 * 3600 - 121, now) is None
    assert detect_offset(now.timestamp() + 2 * 3600 + 1800, now) is None


def test_detect_offset_stale_weekend_tick() -> None:
    # Last tick Friday 23:59:59 server time, read on Sunday afternoon.
    tick = wall_epoch(2026, 10, 30, 23, 59, 59)
    now = utc(2026, 11, 1, 14, 0, 0)
    assert detect_offset(tick, now) is None


def test_detect_offset_range() -> None:
    now = utc(2026, 11, 2, 9)
    assert detect_offset(now.timestamp() + 14 * 3600, now) == 14
    assert detect_offset(now.timestamp() + 15 * 3600, now) is None
    assert detect_offset(now.timestamp() - 13 * 3600, now) is None


# --- choose_conversion --------------------------------------------------------------------


def test_choose_agrees_uses_rule() -> None:
    choice = choose_conversion(2, NY, utc(2026, 11, 2, 9))
    assert choice.conversion is NY
    assert not choice.mismatch
    assert choice.verified


def test_choose_agrees_in_summer() -> None:
    choice = choose_conversion(3, NY, utc(2026, 7, 1, 9))
    assert choice.conversion is NY
    assert not choice.mismatch


def test_choose_disagrees_uses_fixed_and_flags() -> None:
    choice = choose_conversion(3, NY, utc(2026, 11, 2, 9))
    assert choice.conversion == FixedOffset(3)
    assert choice.mismatch
    assert "UTC+3" in choice.message


def test_choose_without_detection() -> None:
    choice = choose_conversion(None, NY, utc(2026, 11, 1, 14))
    assert choice.conversion is NY
    assert not choice.verified
    assert not choice.mismatch


def test_choose_without_rule() -> None:
    assert choose_conversion(2, None, utc(2026, 11, 2)).conversion == FixedOffset(2)
    none = choose_conversion(None, None, utc(2026, 11, 2))
    assert none.conversion is None
