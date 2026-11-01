from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from app.domain.sessions import (
    Window,
    brussels_weekday_hour,
    classify,
    entries_allowed,
    find_window,
    is_trading_time,
)

WINDOWS = (
    Window("london", time(8), time(11), True),
    Window("premarket", time(11), time(13), False),
    Window("ny", time(13), time(16), True),
)


def utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


# Brussels is UTC+1 in winter (2026-01-14) and UTC+2 in summer (2026-07-15).
WINTER = 1
SUMMER = 2


@pytest.mark.parametrize(("day", "shift"), [((2026, 1, 14), WINTER), ((2026, 7, 15), SUMMER)])
@pytest.mark.parametrize(
    ("local", "expected"),
    [
        ((7, 59, 59), "outside"),
        ((8, 0, 0), "london"),
        ((10, 59, 59), "london"),
        ((11, 0, 0), "premarket"),
        ((12, 59, 59), "premarket"),
        ((13, 0, 0), "ny"),
        ((15, 59, 59), "ny"),
        ((16, 0, 0), "outside"),
        ((0, 0, 0), "outside"),
    ],
)
def test_classify_boundaries(
    day: tuple[int, int, int], shift: int, local: tuple[int, int, int], expected: str
) -> None:
    h, m, s = local
    instant = utc(*day, (h - shift) % 24, m, s)
    if h - shift < 0:
        instant = instant.replace(day=day[2] - 1)
    assert classify(instant, WINDOWS) == expected


def test_entries_allowed() -> None:
    assert entries_allowed(utc(2026, 1, 14, 8), WINDOWS)  # 09:00 london
    assert not entries_allowed(utc(2026, 1, 14, 11), WINDOWS)  # 12:00 premarket
    assert not entries_allowed(utc(2026, 1, 14, 20), WINDOWS)  # outside


def test_eu_dst_switch_day() -> None:
    # 2026-03-29: Brussels switches to +2 at 01:00 UTC.
    assert classify(utc(2026, 3, 29, 6, 30), WINDOWS) == "london"
    assert classify(utc(2026, 3, 27, 6, 30), WINDOWS) == "outside"  # 07:30 local, winter


def test_find_window_returns_object() -> None:
    w = find_window(utc(2026, 7, 15, 11), WINDOWS)
    assert w is not None
    assert w.name == "ny"


def test_wrapping_window() -> None:
    night = (Window("asia", time(23), time(2), False),)
    assert classify(utc(2026, 1, 14, 23, 30), night) == "asia"  # 00:30 local
    assert classify(utc(2026, 1, 14, 21, 59), night) == "outside"  # 22:59 local


def test_naive_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        classify(datetime(2026, 1, 14, 9), WINDOWS)  # noqa: DTZ001


def test_brussels_weekday_hour() -> None:
    # Sunday 23:30 UTC in summer = Monday 01:30 Brussels
    assert brussels_weekday_hour(utc(2026, 7, 12, 23, 30)) == (0, 1)
    assert brussels_weekday_hour(utc(2026, 1, 14, 7, 59)) == (2, 8)


DAYS = ["mon", "tue", "wed", "thu", "fri"]


def test_is_trading_time() -> None:
    start, end = time(8), time(16)
    assert is_trading_time(utc(2026, 1, 14, 7), DAYS, start, end)  # Wed 08:00
    assert not is_trading_time(utc(2026, 1, 14, 6, 59, 59), DAYS, start, end)
    assert is_trading_time(utc(2026, 7, 15, 13, 59, 59), DAYS, start, end)  # 15:59:59
    assert not is_trading_time(utc(2026, 7, 15, 14), DAYS, start, end)  # 16:00
    assert not is_trading_time(utc(2026, 1, 17, 9), DAYS, start, end)  # Saturday
    assert is_trading_time(utc(2026, 1, 16, 9), [0, 1, 2, 3, 4], start, end)  # Friday, ints


def test_is_trading_time_bad_day() -> None:
    with pytest.raises(ValueError, match="weekday"):
        is_trading_time(utc(2026, 1, 14, 9), ["xyz"], time(8), time(16))
