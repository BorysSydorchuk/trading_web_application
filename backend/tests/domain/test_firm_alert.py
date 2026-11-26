"""Firm alert and the «Ліміти» account pick (PM 2026-11-26): an account within 1 % of a firm
limit (daily or max loss) goes first; otherwise the closest to the personal daily stop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.domain import firm_rules as fr

D = Decimal
RESET = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)


def _day(room: str | None, *, breached: bool = False) -> fr.FirmDay:
    return fr.FirmDay(
        reset_at=RESET,
        start_balance=D("98000"),
        floor=D("94000"),
        loss_pct=D("-4"),
        pnl_pct=None if room is None else D(room) - D(4),
        room_pct=None if room is None else D(room),
        breached=breached,
        to_verify=(),
    )


def test_threshold_is_one_percent() -> None:
    assert D(1) == fr.FIRM_ALERT_ROOM_PCT


def test_no_alert_when_far_from_both_limits() -> None:
    assert fr.firm_alert(_day("3.5"), D("6.0")) is None
    assert fr.firm_alert(None, None) is None


def test_daily_alert_at_exactly_one_percent_room() -> None:
    assert fr.firm_alert(_day("1"), D("6")) == fr.FirmAlert("firm_day", D("1"))


def test_daily_alert_just_above_threshold_is_none() -> None:
    assert fr.firm_alert(_day("1.0001"), None) is None


def test_max_loss_alert_within_one_percent() -> None:
    assert fr.firm_alert(None, D("0.4")) == fr.FirmAlert("max_loss", D("0.4"))


def test_breached_day_with_unknown_room_alerts() -> None:
    assert fr.firm_alert(_day(None, breached=True), None) == fr.FirmAlert("firm_day", None)


def test_unknown_room_not_breached_is_no_alert() -> None:
    assert fr.firm_alert(_day(None), None) is None


def test_both_near_the_closer_limit_is_named() -> None:
    assert fr.firm_alert(_day("0.9"), D("0.3")) == fr.FirmAlert("max_loss", D("0.3"))
    assert fr.firm_alert(_day("0.2"), D("0.8")) == fr.FirmAlert("firm_day", D("0.2"))


def test_breached_unknown_room_beats_a_known_room() -> None:
    assert fr.firm_alert(_day(None, breached=True), D("0.5")) == fr.FirmAlert("firm_day", None)


def test_negative_room_alerts() -> None:
    assert fr.firm_alert(_day("-0.5", breached=True), None) == fr.FirmAlert("firm_day", D("-0.5"))


@dataclass(frozen=True)
class _Item:
    name: str
    stop_room: D | None
    alert: fr.FirmAlert | None


def _pick(*items: _Item) -> _Item | None:
    return fr.pick_limits_item(items, lambda i: i.stop_room, lambda i: i.alert)


def test_pick_without_alerts_is_closest_to_personal_stop() -> None:
    a, b = _Item("a", D("2.5"), None), _Item("b", D("1.0"), None)
    assert _pick(a, b) is b


def test_pick_alerted_account_first_even_if_far_from_personal_stop() -> None:
    near_stop = _Item("fn", D("0.2"), None)
    near_firm = _Item("kf", D("2.9"), fr.FirmAlert("firm_day", D("0.8")))
    assert _pick(near_stop, near_firm) is near_firm


def test_pick_among_alerts_the_smallest_room_unknown_first() -> None:
    a = _Item("a", D("1"), fr.FirmAlert("max_loss", D("0.6")))
    b = _Item("b", D("1"), fr.FirmAlert("firm_day", D("0.1")))
    c = _Item("c", D("1"), fr.FirmAlert("firm_day", None))
    assert _pick(a, b) is b
    assert _pick(a, b, c) is c


def test_pick_empty_is_none() -> None:
    assert _pick() is None
