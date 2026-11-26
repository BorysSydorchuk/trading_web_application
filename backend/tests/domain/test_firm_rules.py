"""Pure firm rules: effective rules per account, firm day, static max loss
(docs/api.md "Firm rules from config: KeyFunding")."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.config_files.firms import FirmsConfig
from app.domain.firm_rules import (
    FirmDay,
    FirmRules,
    at_max_loss,
    day_rule,
    effective_rules,
    firm_day,
    max_loss_floor,
    reset_at,
)

D = Decimal

FIRMS = FirmsConfig.model_validate(
    {
        "firms": {
            "KeyFunding": {
                "daily_loss_pct": 4.0,
                "max_loss_pct": 8.0,
                "profit_target_pct": {"phase_1": 8.0, "phase_2": 4.0},
                "to_verify": ["daily_basis", "daily_reset"],
            }
        }
    }
)
NO_FIRMS = FirmsConfig.model_validate({"firms": {}})


def utc(d: int, h: int = 0, mi: int = 0, mo: int = 11) -> datetime:
    return datetime(2026, mo, d, h, mi, tzinfo=UTC)


def rules_for(firm: str | None = "KeyFunding", phase: str = "phase_1", **kw: Any) -> FirmRules:
    args: dict[str, Any] = {
        "account_firm": firm,
        "phase": phase,
        "account_daily_loss_pct": None,
        "account_max_drawdown_pct": None,
        "account_profit_target_pct": None,
        "firms": FIRMS,
        "fallback_max_loss_pct": None,
        "fallback_profit_target_pct": None,
    }
    args.update(kw)
    return effective_rules(**args)


# --- effective rules -------------------------------------------------------------------------


def test_firm_entry_gives_firm_values_and_phase_target() -> None:
    eff = rules_for("Key Funding", "phase_1")

    assert eff.source == "firm"
    assert eff.firm == "KeyFunding"
    assert (eff.daily_loss_pct, eff.max_loss_pct, eff.profit_target_pct) == (D(4), D(8), D(8))
    assert eff.max_loss_type == "static"
    assert eff.daily_basis == "balance"
    assert eff.daily_reset == "00:00"
    assert eff.reset_timezone == "server"
    assert eff.to_verify == ("daily_basis", "daily_reset")


def test_phase_2_target_and_funded_has_no_target() -> None:
    assert rules_for(phase="phase_2").profit_target_pct == D(4)
    assert rules_for(phase="funded").profit_target_pct is None
    assert rules_for(phase="funded").max_loss_pct == D(8)


def test_account_values_override_the_firm_per_field() -> None:
    eff = rules_for(
        account_daily_loss_pct=D("3"),
        account_max_drawdown_pct=D("6"),
        account_profit_target_pct=D("10"),
    )

    assert (eff.daily_loss_pct, eff.max_loss_pct, eff.profit_target_pct) == (D(3), D(6), D(10))
    assert eff.source == "firm"


def test_zero_or_missing_account_value_falls_back_to_the_firm() -> None:
    eff = rules_for(account_daily_loss_pct=D(0), account_max_drawdown_pct=None)

    assert (eff.daily_loss_pct, eff.max_loss_pct) == (D(4), D(8))


def test_account_target_on_funded_overrides_none() -> None:
    assert rules_for(phase="funded", account_profit_target_pct=D(5)).profit_target_pct == D(5)


def test_rules_yaml_fallback_is_ignored_for_a_firm_entry() -> None:
    eff = rules_for(fallback_max_loss_pct=D(-10), fallback_profit_target_pct=D(10))

    assert (eff.max_loss_pct, eff.profit_target_pct) == (D(8), D(8))


def test_fundednext_without_entry_uses_the_rules_yaml_fallback() -> None:
    eff = rules_for("FundedNext", fallback_max_loss_pct=D(-10), fallback_profit_target_pct=D(8))

    assert eff.source == "fallback"
    assert eff.firm is None
    assert (eff.max_loss_pct, eff.profit_target_pct) == (D(10), D(8))
    assert eff.daily_loss_pct is None
    assert eff.daily_reset is None
    assert eff.to_verify == ()
    assert eff.limits() == (D(-10), D(8))


def test_account_values_without_entry_win_over_the_fallback() -> None:
    eff = rules_for(
        "FundedNext",
        account_max_drawdown_pct=D(5),
        account_profit_target_pct=None,
        fallback_max_loss_pct=D(-10),
        fallback_profit_target_pct=D(8),
    )

    assert eff.source == "account"
    assert eff.limits() == (D(-5), None)  # no mixing of the fallback target (unchanged)
    assert eff.daily_loss_pct is None


def test_account_daily_loss_without_entry_is_shown_but_gives_no_firm_day() -> None:
    eff = rules_for("FundedNext", account_daily_loss_pct=D(5))

    assert eff.source == "account"
    assert eff.daily_loss_pct == D(5)
    assert day_rule(eff, None) is None


def test_nothing_set_is_source_none() -> None:
    eff = rules_for("FundedNext")

    assert eff.source == "none"
    assert eff.limits() == (None, None)


def test_no_firms_file_equals_fundednext_behaviour() -> None:
    eff = rules_for("KeyFunding", firms=NO_FIRMS, fallback_max_loss_pct=D(-10))

    assert eff.source == "fallback"
    assert eff.limits() == (D(-10), None)


def test_none_firm_name_is_handled() -> None:
    assert rules_for(None).source == "none"


def test_firm_limits_are_signed_like_rules_yaml() -> None:
    assert rules_for().limits() == (D(-8), D(8))


# --- reset_at --------------------------------------------------------------------------------


def test_reset_at_server_offset_zero_is_utc_midnight() -> None:
    assert reset_at(utc(12, 14, 0), time(0), "server", 0) == utc(12)


def test_reset_at_server_unknown_offset_is_utc() -> None:
    assert reset_at(utc(12, 14, 0), time(0), "server", None) == utc(12)


def test_reset_at_server_offset_plus_two() -> None:
    # server midnight = 22:00 UTC the evening before
    assert reset_at(utc(12, 14, 0), time(0), "server", 2) == utc(11, 22)
    assert reset_at(utc(12, 21, 59), time(0), "server", 2) == utc(11, 22)
    assert reset_at(utc(12, 22, 0), time(0), "server", 2) == utc(12, 22)


def test_reset_at_just_before_and_after_midnight() -> None:
    assert reset_at(utc(12, 23, 59), time(0), "server", 0) == utc(12)
    assert reset_at(utc(13, 0, 0), time(0), "server", 0) == utc(13)
    assert reset_at(utc(12, 0, 0), time(0), "server", 0) == utc(12)  # exactly at reset
    assert reset_at(utc(12, 0, 1), time(0), "server", 0) == utc(12)


def test_reset_at_negative_offset() -> None:
    assert reset_at(utc(12, 3, 0), time(0), "server", -5) == utc(11, 5)


def test_reset_at_non_midnight_wall_time() -> None:
    assert reset_at(utc(12, 6, 59), time(7, 0), "server", 0) == utc(11, 7)
    assert reset_at(utc(12, 7, 0), time(7, 0), "server", 0) == utc(12, 7)


def test_reset_at_iana_zone_follows_dst() -> None:
    # New York: EST (UTC-5) in November, EDT (UTC-4) in July
    assert reset_at(utc(12, 14), time(0), "America/New_York", 3) == utc(12, 5)
    july = datetime(2026, 7, 15, 14, tzinfo=UTC)
    assert reset_at(july, time(0), "America/New_York", None) == datetime(2026, 7, 15, 4, tzinfo=UTC)


def test_reset_at_across_dst_change_day() -> None:
    # 2026-11-01 the US falls back: local midnight is still EDT (UTC-4)
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)

    assert reset_at(now, time(0), "America/New_York", None) == datetime(2026, 11, 1, 4, tzinfo=UTC)


def test_reset_at_requires_an_aware_now() -> None:
    naive = datetime(2026, 11, 12, 14)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="timezone-aware"):
        reset_at(naive, time(0), "server", 0)


# --- firm day --------------------------------------------------------------------------------

RESET = utc(12)  # server offset 0


def day(**kw: Any) -> FirmDay:
    args: dict[str, Any] = {
        "size": D(10000),
        "daily_loss_pct": D(4),
        "reset_at": RESET,
        "closed": [],
        "open_booked": [],
        "fresh_balance": None,
        "floating": D(0),
        "to_verify": ("daily_basis",),
    }
    args.update(kw)
    return firm_day(**args)


def test_floor_is_start_balance_minus_four_percent_of_size() -> None:
    result = day(fresh_balance=D(10000))

    assert result.start_balance == D(10000)
    assert result.floor == D(9600)
    assert result.loss_pct == D(-4)
    assert result.reset_at == RESET
    assert result.to_verify == ("daily_basis",)


def test_start_balance_difference_moves_the_floor() -> None:
    result = day(fresh_balance=D(10500))

    assert result.floor == D(10100)  # 10500 - 400 (4 % of the size, not of the balance)


def test_fresh_balance_start_removes_todays_closed_pnl() -> None:
    closed = [(utc(12, 3), D(-150)), (utc(12, 8), D(50)), (utc(11, 20), D(999))]

    result = day(fresh_balance=D(9900), closed=closed)

    # 9900 - (-150 + 50) = 10000; the trade closed before the reset is not subtracted
    assert result.start_balance == D(10000)
    assert result.pnl_pct == D(-1)  # -100 / 10000 x 100
    assert result.room_pct == D(3)


def test_trade_closed_exactly_at_reset_belongs_to_the_new_day() -> None:
    result = day(fresh_balance=D(9900), closed=[(RESET, D(-100))])

    assert result.start_balance == D(10000)


def test_trades_only_start_without_a_fresh_balance() -> None:
    closed = [(utc(10, 9), D(300)), (utc(11, 23, 59), D(-100)), (utc(12, 4), D(-200))]

    result = day(fresh_balance=None, closed=closed)

    assert result.start_balance == D(10200)  # size + closed before the reset
    assert result.floor == D(9800)
    assert result.pnl_pct == D(-2)


def test_open_trade_cash_booked_after_reset_counts_in_the_day() -> None:
    result = day(fresh_balance=D(9993), open_booked=[(utc(12, 5), D(-7))])

    assert result.start_balance == D(10000)  # the entry commission is part of today
    assert result.pnl_pct == D("-0.07")


def test_open_trade_cash_booked_before_reset_is_start_balance_in_trades_mode() -> None:
    result = day(fresh_balance=None, open_booked=[(utc(11, 22), D(-7))])

    assert result.start_balance == D(9993)
    assert result.pnl_pct == D(0)


def test_open_trade_opened_before_reset_is_not_subtracted_from_a_fresh_balance() -> None:
    result = day(fresh_balance=D(9993), open_booked=[(utc(11, 22), D(-7))])

    assert result.start_balance == D(9993)


def test_floating_loss_counts_toward_room() -> None:
    result = day(fresh_balance=D(10000), floating=D(-250))

    assert result.pnl_pct == D("-2.5")
    assert result.room_pct == D("1.5")
    assert result.breached is False


def test_floating_unknown_gives_unknown_pct_and_room() -> None:
    result = day(fresh_balance=D(10000), floating=None)

    assert result.pnl_pct is None
    assert result.room_pct is None
    assert result.breached is False
    assert result.floor == D(9600)


def test_breached_at_exactly_room_zero() -> None:
    result = day(fresh_balance=D(10000), floating=D(-400))

    assert result.room_pct == D(0)
    assert result.breached is True


def test_not_breached_just_above_the_floor() -> None:
    assert day(fresh_balance=D(10000), floating=D("-399.99")).breached is False


def test_breached_below_zero_room() -> None:
    result = day(fresh_balance=D(10000), floating=D(-450))

    assert result.room_pct == D("-0.5")
    assert result.breached is True


def test_realized_loss_plus_floating_combine() -> None:
    result = day(
        fresh_balance=D(9700),
        closed=[(utc(12, 2), D(-300))],
        floating=D(-100),
    )

    assert result.start_balance == D(10000)
    assert result.pnl_pct == D(-4)
    assert result.breached is True


def test_profit_day_adds_room() -> None:
    result = day(fresh_balance=D(10300), closed=[(utc(12, 2), D(300))])

    assert result.pnl_pct == D(3)
    assert result.room_pct == D(7)


def test_pnl_is_measured_against_the_size_not_the_start_balance() -> None:
    result = day(size=D(20000), fresh_balance=D(21000), floating=D(-200))

    assert result.floor == D(20200)  # 21000 - 800
    assert result.pnl_pct == D(-1)


def test_decimal_precision_is_kept() -> None:
    result = day(size=D(10000), daily_loss_pct=D("4.5"), fresh_balance=D("10000.10"))

    assert result.floor == D("9550.10")


# --- static max loss -------------------------------------------------------------------------


def test_static_floor_is_size_times_one_minus_pct() -> None:
    assert max_loss_floor(D(10000), D(8)) == D(9200)


def test_static_floor_never_moves_after_profit() -> None:
    size = D(10000)

    assert max_loss_floor(size, D(8)) == D(9200)
    assert at_max_loss(D(9200), size, D(8)) is True
    # Equity has grown to 12 000 (a trailing floor would be higher): 9200 stays the floor.
    assert at_max_loss(D(12000), size, D(8)) is False
    assert at_max_loss(D(9200.01), size, D(8)) is False
    assert at_max_loss(D(9199), size, D(8)) is True


# --- rule day (rules engine) -----------------------------------------------------------------


def test_day_rule_only_for_firm_entries() -> None:
    rule = day_rule(rules_for(), 2)

    assert rule is not None
    assert rule.daily_loss_pct == D(4)
    assert rule.daily_reset == time(0)
    assert rule.reset_timezone == "server"
    assert rule.server_offset_hours == 2
    assert day_rule(rules_for("FundedNext"), 2) is None


def test_reset_for_rule_matches_reset_at() -> None:
    rule = day_rule(rules_for(), 2)
    assert rule is not None

    assert rule.reset_at(utc(12, 14)) == utc(11, 22)


def test_first_second_after_reset_is_a_new_day() -> None:
    rule = day_rule(rules_for(), 0)
    assert rule is not None
    start = utc(12)

    assert rule.reset_at(start + timedelta(seconds=1)) == start
    assert rule.reset_at(start - timedelta(seconds=1)) == start - timedelta(days=1)
