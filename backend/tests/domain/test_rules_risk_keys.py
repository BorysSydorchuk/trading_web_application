"""M8-04: the daily/weekly limits are reported as one `daily_risk` / `weekly_risk` violation;
the limit hit stays in `details` (`<old rule key>: ...`). docs/api.md "Violations"."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.rules import RuleTradeInput, Violation, evaluate
from tests.domain.test_rules import CLEAN, RULES, D, rules, tr, utc

OLD_KEYS = {
    "daily_stop_loss_pct",
    "daily_stop_profit_pct",
    "weekly_stop_loss_pct",
    "weekly_stop_profit_pct",
}


def found(trade: RuleTradeInput, ctx: list[RuleTradeInput], cfg: object = RULES) -> list[Violation]:
    return evaluate(trade, ctx, cfg, None)  # type: ignore[arg-type]


def of(violations: list[Violation], key: str) -> list[Violation]:
    return [v for v in violations if v.rule_key == key]


DAY_LOSS = [
    tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), "-1500.00"),
    tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 30), "-1500.00"),
]  # Mon 2026-11-02, -3.00 % before an entry at 09:00 UTC
DAY_PROFIT = [
    tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), "3000.00"),
    tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 30), "2000.00"),
]  # +5.00 %
DAY_BOTH = [
    tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), "-3500.00"),  # -3.50 %
    tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 30), "9000.00"),  # running +5.50 %
]
# Mon + Tue losses / profit, entry on Wed 2026-11-04 (a different day, same week).
WEEK_LOSS = [tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "-7000.00")]
WEEK_PROFIT = [tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "11000.00")]
WEEK_BOTH = [
    tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "-7000.00"),  # -7 %
    tr(11, utc(11, 2, 8), utc(11, 3, 8), "20000.00"),  # running +13 %
]
ENTRY_MONDAY = tr(1, utc(11, 2, 9))
ENTRY_WEDNESDAY = tr(1, utc(11, 4, 8))


def test_daily_loss_is_one_daily_risk_violation_with_the_limit_in_details() -> None:
    out = found(ENTRY_MONDAY, DAY_LOSS)

    (v,) = of(out, "daily_risk")
    assert v.details.startswith("daily_stop_loss_pct:")
    assert "-3.00%" in v.details
    assert "-3.0%" in v.details  # the limit


def test_daily_profit_is_one_daily_risk_violation_with_the_limit_in_details() -> None:
    out = found(ENTRY_MONDAY, DAY_PROFIT)

    (v,) = of(out, "daily_risk")
    assert v.details.startswith("daily_stop_profit_pct:")
    assert "5.00%" in v.details
    assert "daily_stop_loss_pct" not in v.details


def test_both_daily_limits_give_one_violation_with_parts_joined() -> None:
    out = found(ENTRY_MONDAY, DAY_BOTH)

    (v,) = of(out, "daily_risk")
    parts = v.details.split("; ")
    assert len(parts) == 2
    assert parts[0].startswith("daily_stop_loss_pct:")
    assert parts[1].startswith("daily_stop_profit_pct:")


def test_weekly_loss_is_weekly_risk() -> None:
    out = found(ENTRY_WEDNESDAY, WEEK_LOSS)

    (v,) = of(out, "weekly_risk")
    assert v.details.startswith("weekly_stop_loss_pct:")
    assert of(out, "daily_risk") == []


def test_weekly_profit_is_weekly_risk() -> None:
    out = found(ENTRY_WEDNESDAY, WEEK_PROFIT)

    (v,) = of(out, "weekly_risk")
    assert v.details.startswith("weekly_stop_profit_pct:")


def test_both_weekly_limits_give_one_violation_with_parts_joined() -> None:
    out = found(ENTRY_WEDNESDAY, WEEK_BOTH)

    (v,) = of(out, "weekly_risk")
    parts = v.details.split("; ")
    assert len(parts) == 2
    assert parts[0].startswith("weekly_stop_loss_pct:")
    assert parts[1].startswith("weekly_stop_profit_pct:")


def test_daily_and_weekly_limits_on_the_same_entry_are_two_violations() -> None:
    ctx = [tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "-7000.00")]

    out = found(ENTRY_MONDAY, ctx)

    assert len(of(out, "daily_risk")) == 1
    assert len(of(out, "weekly_risk")) == 1


@pytest.mark.parametrize(
    ("trade", "ctx"),
    [
        (ENTRY_MONDAY, DAY_LOSS),
        (ENTRY_MONDAY, DAY_PROFIT),
        (ENTRY_MONDAY, DAY_BOTH),
        (ENTRY_WEDNESDAY, WEEK_LOSS),
        (ENTRY_WEDNESDAY, WEEK_PROFIT),
        (ENTRY_WEDNESDAY, WEEK_BOTH),
    ],
)
def test_old_keys_are_never_emitted(trade: RuleTradeInput, ctx: list[RuleTradeInput]) -> None:
    assert {v.rule_key for v in found(trade, ctx)}.isdisjoint(OLD_KEYS)


def test_disabled_loss_limit_has_no_part() -> None:
    cfg = rules(daily_stop_loss_pct={"enabled": False})

    assert of(found(ENTRY_MONDAY, DAY_LOSS, cfg), "daily_risk") == []


def test_disabled_loss_limit_leaves_only_the_profit_part() -> None:
    cfg = rules(daily_stop_loss_pct={"enabled": False})

    (v,) = of(found(ENTRY_MONDAY, DAY_BOTH, cfg), "daily_risk")
    assert v.details.startswith("daily_stop_profit_pct:")
    assert "daily_stop_loss_pct" not in v.details
    assert "; " not in v.details


def test_disabled_profit_limit_leaves_only_the_loss_part() -> None:
    cfg = rules(weekly_stop_profit_pct={"enabled": False})

    (v,) = of(found(ENTRY_WEDNESDAY, WEEK_BOTH, cfg), "weekly_risk")
    assert v.details.startswith("weekly_stop_loss_pct:")
    assert "weekly_stop_profit_pct" not in v.details


def test_all_four_limits_disabled_give_no_risk_violation() -> None:
    cfg = rules(
        daily_stop_loss_pct={"enabled": False},
        daily_stop_profit_pct={"enabled": False},
        weekly_stop_loss_pct={"enabled": False},
        weekly_stop_profit_pct={"enabled": False},
    )

    out = found(ENTRY_MONDAY, [*DAY_BOTH, *WEEK_LOSS], cfg)

    assert of(out, "daily_risk") == []
    assert of(out, "weekly_risk") == []


def test_no_account_size_gives_no_risk_violation() -> None:
    out = found(tr(1, utc(11, 2, 9), size=None), DAY_LOSS)

    assert of(out, "daily_risk") == []
    assert of(out, "weekly_risk") == []


def test_limit_just_not_reached_gives_no_violation() -> None:
    ctx = [
        tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), "-1500.00"),
        tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 30), "-1499.00"),
    ]

    assert of(found(ENTRY_MONDAY, ctx), "daily_risk") == []


def test_other_rules_are_unchanged() -> None:
    risky = tr(1, utc(11, 2, 9), risk_pct=Decimal("2"), planned_rr=D("1"), session="premarket")

    keys = {v.rule_key for v in found(risky, DAY_LOSS)}

    assert keys == {"daily_risk", "max_risk_pct", "min_planned_rr", "entry_session"}


def test_clean_trade_still_has_no_violations() -> None:
    assert evaluate(CLEAN, [CLEAN], RULES, D("0.01")) == []
