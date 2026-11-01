from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.config_files.rules import RulesConfig
from app.domain.rules import RuleExitDeal, RuleTradeInput, Violation, evaluate

D = Decimal

RAW: dict[str, Any] = {
    "timezone": "Europe/Brussels",
    "sessions": {
        "london": {"start": "08:00", "end": "11:00", "entries_allowed": True},
        "premarket": {"start": "11:00", "end": "13:00", "entries_allowed": False},
        "ny": {"start": "13:00", "end": "16:00", "entries_allowed": True},
    },
    "sync": {
        "trading_days": ["mon", "tue", "wed", "thu", "fri"],
        "trading_hours": {"start": "08:00", "end": "16:00"},
        "interval_trading_seconds": 60,
        "interval_idle_seconds": 900,
        "initial_history_days": 30,
        "overlap_days": 3,
        "watch_symbols": ["XAUUSD"],
    },
    "broker_time": "ny_close",
    "rules": {
        "max_risk_pct": {"value": "1.1", "enabled": True},
        "daily_stop_loss_pct": {"value": "-3.0", "enabled": True},
        "daily_stop_profit_pct": {"value": "5.0", "enabled": True},
        "weekly_stop_loss_pct": {"value": "-6.0", "enabled": True},
        "weekly_stop_profit_pct": {"value": "10.0", "enabled": True},
        "max_trades_per_week": {"value": 10, "enabled": True},
        "max_reentries_per_idea": {"value": 1, "enabled": True},
        "min_planned_rr": {"value": "1.5", "enabled": True},
        "entry_session": {"enabled": True},
        "qm_not_in_ny": {"enabled": True, "entry_model": "qm_m5", "session": "ny"},
        "no_breakeven": {"enabled": True},
    },
}


def rules(**changes: dict[str, Any]) -> RulesConfig:
    raw = copy.deepcopy(RAW)
    for key, update in changes.items():
        raw["rules"][key].update(update)
    return RulesConfig.model_validate(raw)


RULES = rules()


def utc(mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(2026, mo, d, h, mi, tzinfo=UTC)


def tr(
    key: int,
    open_time: datetime,
    close_time: datetime | None = None,
    pnl: str | None = None,
    *,
    balance: str | None = "100000",
    account_id: int = 1,
    symbol: str = "XAUUSD",
    direction: str = "buy",
    session: str | None = "london",
    **kw: Any,
) -> RuleTradeInput:
    return RuleTradeInput(
        key=key,
        account_id=account_id,
        symbol=symbol,
        direction=direction,
        open_time=open_time,
        close_time=close_time,
        session=session,
        net_pnl=D(pnl) if pnl is not None else None,
        balance_at_open=D(balance) if balance is not None else None,
        risk_pct=kw.pop("risk_pct", None),
        planned_rr=kw.pop("planned_rr", None),
        entry_price=kw.pop("entry_price", None),
        last_sl=kw.pop("last_sl", None),
        initial_sl=kw.pop("initial_sl", None),
        exit_deals=kw.pop("exit_deals", ()),
        entry_model=kw.pop("entry_model", None),
        is_reentry=kw.pop("is_reentry", False),
    )


def keys(
    trade: RuleTradeInput,
    context: list[RuleTradeInput] | None = None,
    cfg: RulesConfig = RULES,
    tick: Decimal | None = None,
) -> set[str]:
    return {v.rule_key for v in evaluate(trade, context or [], cfg, tick)}


# A clean trade: Mon 2026-11-02 09:00 Brussels (08:00 UTC), london, nothing wrong.
CLEAN = tr(1, utc(11, 2, 8), utc(11, 2, 9), "100", risk_pct=D("1.0"), planned_rr=D("2"))


def test_clean_trade_has_no_violations() -> None:
    assert evaluate(CLEAN, [CLEAN], RULES, D("0.01")) == []


# --- max_risk_pct -------------------------------------------------------------------------


@pytest.mark.parametrize(("risk", "hit"), [("1.1", False), ("1.1001", True), ("0.5", False)])
def test_max_risk_pct(risk: str, hit: bool) -> None:
    trade = tr(1, utc(11, 2, 8), risk_pct=D(risk))
    assert ("max_risk_pct" in keys(trade)) is hit


def test_max_risk_pct_disabled_and_missing() -> None:
    trade = tr(1, utc(11, 2, 8), risk_pct=D("2"))
    assert "max_risk_pct" not in keys(trade, cfg=rules(max_risk_pct={"enabled": False}))
    assert "max_risk_pct" not in keys(tr(1, utc(11, 2, 8)))


def test_max_risk_details() -> None:
    (v,) = evaluate(tr(1, utc(11, 2, 8), risk_pct=D("1.2560")), [], RULES, None)
    assert v == Violation("max_risk_pct", "risk 1.26% > limit 1.1%")


# --- daily / weekly stop ------------------------------------------------------------------


def _day_losses(a: str, b: str) -> list[RuleTradeInput]:
    return [
        tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), a, balance="100000"),
        tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 30), b),
    ]


def test_daily_stop_loss_boundary_hit() -> None:
    ctx = _day_losses("-1500.00", "-1500.00")
    trade = tr(1, utc(11, 2, 9), balance="97000")  # start of day 100000, P&L -3.00 %
    (v,) = [x for x in evaluate(trade, ctx, RULES, None) if x.rule_key == "daily_stop_loss_pct"]
    assert v.details == "day P&L reached -3.00% (-3000.00) before entry <= limit -3.0%"


def test_daily_stop_loss_just_above() -> None:
    ctx = _day_losses("-1500.00", "-1499.00")
    trade = tr(1, utc(11, 2, 9), balance="97001")
    assert "daily_stop_loss_pct" not in keys(trade, ctx)


def test_daily_stop_counts_only_trades_closed_before_entry() -> None:
    ctx = [
        tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "-2000"),
        tr(11, utc(11, 2, 7, 40), utc(11, 2, 9, 30), "-2000"),  # closes after entry
    ]
    trade = tr(1, utc(11, 2, 9), balance="98000")
    assert "daily_stop_loss_pct" not in keys(trade, ctx)


def test_daily_stop_other_account_ignored() -> None:
    ctx = [tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "-5000", account_id=2)]
    assert "daily_stop_loss_pct" not in keys(tr(1, utc(11, 2, 9)), ctx)


def test_daily_stop_profit() -> None:
    ctx = [tr(10, utc(11, 2, 7), utc(11, 2, 7, 30), "3000"), tr(11, utc(11, 2, 7), None, None)]
    ctx.append(tr(12, utc(11, 2, 7, 35), utc(11, 2, 8), "2000"))
    trade = tr(1, utc(11, 2, 9), balance="105000")
    assert keys(trade, ctx) >= {"daily_stop_profit_pct"}
    assert "daily_stop_profit_pct" not in keys(
        trade, ctx, rules(daily_stop_profit_pct={"enabled": False})
    )


def test_daily_stop_disabled_and_no_balance() -> None:
    ctx = _day_losses("-1500", "-1500")
    cfg = rules(daily_stop_loss_pct={"enabled": False})
    assert "daily_stop_loss_pct" not in keys(tr(1, utc(11, 2, 9), balance="97000"), ctx, cfg)
    assert "daily_stop_loss_pct" not in keys(tr(1, utc(11, 2, 9), balance=None), ctx)


def test_weekly_stop_loss_over_several_days() -> None:
    ctx = [
        tr(10, utc(11, 2, 8), utc(11, 2, 9), "-4000"),  # Mon
        tr(11, utc(11, 3, 8), utc(11, 3, 9), "-2000"),  # Tue
        tr(12, utc(10, 30, 8), utc(10, 30, 9), "-5000"),  # previous Friday: other week
    ]
    trade = tr(1, utc(11, 4, 8), balance="94000")  # Wed; week start balance 100000
    found = keys(trade, ctx)
    assert "weekly_stop_loss_pct" in found
    assert "daily_stop_loss_pct" not in found
    trade_ok = tr(1, utc(11, 4, 8), balance="94001")
    ctx_ok = [*ctx[:1], tr(11, utc(11, 3, 8), utc(11, 3, 9), "-1999")]
    assert "weekly_stop_loss_pct" not in keys(trade_ok, ctx_ok)


def test_weekly_stop_profit() -> None:
    ctx = [
        tr(10, utc(11, 2, 8), utc(11, 2, 9), "6000"),
        tr(11, utc(11, 3, 8), utc(11, 3, 9), "4000"),
    ]
    trade = tr(1, utc(11, 5, 8), balance="110000")
    assert "weekly_stop_profit_pct" in keys(trade, ctx)
    cfg = rules(weekly_stop_profit_pct={"enabled": False})
    assert "weekly_stop_profit_pct" not in keys(trade, ctx, cfg)


def test_brussels_day_boundary_sunday_vs_monday_winter() -> None:
    # Sun 2026-11-01 23:30 Brussels = 22:30 UTC: previous day AND previous week.
    sunday_loss = tr(10, utc(11, 1, 22), utc(11, 1, 22, 30), "-7000")
    # Mon 00:10 Brussels = Sun 23:10 UTC: same Brussels day/week as a Monday entry.
    monday_loss = tr(11, utc(11, 1, 23), utc(11, 1, 23, 10), "-3500")
    entry = utc(11, 1, 23, 30)  # Mon 00:30 Brussels
    assert keys(tr(1, entry, balance="93000", session=None), [sunday_loss]) == set()
    found = keys(tr(1, entry, balance="89500", session=None), [sunday_loss, monday_loss])
    assert {"daily_stop_loss_pct"} <= found
    assert "weekly_stop_loss_pct" not in found  # -3500 / 93000 = -3.76 % of the week


def test_brussels_day_boundary_across_eu_dst_end() -> None:
    # EU DST ends Sun 2026-10-25. Sun 23:30 Brussels (+1) = 22:30 UTC; Mon 00:30 = 23:30 UTC.
    sunday_loss = tr(10, utc(10, 25, 22), utc(10, 25, 22, 30), "-4000")
    monday = tr(1, utc(10, 25, 23, 30), balance="96000", session=None)
    assert keys(monday, [sunday_loss]) == set()
    # Summer week before: Mon 2026-10-19 00:30 Brussels (+2) = Sun 22:30 UTC.
    early_monday_loss = tr(11, utc(10, 18, 22, 10), utc(10, 18, 22, 20), "-4000")
    monday_summer = tr(2, utc(10, 18, 22, 30), balance="96000", session=None)
    assert "daily_stop_loss_pct" in keys(monday_summer, [early_monday_loss])


# --- max_trades_per_week ------------------------------------------------------------------


def _week_of(n: int, account_id: int = 1) -> list[RuleTradeInput]:
    start = utc(11, 2, 8)
    return [
        tr(100 + i + account_id * 1000, start + timedelta(hours=i * 9), account_id=account_id)
        for i in range(n)
    ]


def test_max_trades_per_week() -> None:
    week = _week_of(11)
    assert "max_trades_per_week" not in keys(week[9], week)
    (v,) = [x for x in evaluate(week[10], week, RULES, None) if x.rule_key == "max_trades_per_week"]
    assert v.details == "trade #11 of the week > limit 10"
    cfg = rules(max_trades_per_week={"enabled": False})
    assert "max_trades_per_week" not in keys(week[10], week, cfg)


def test_max_trades_per_week_is_per_account_and_week() -> None:
    other_account = _week_of(10, account_id=2)
    previous_week = [tr(50 + i, utc(10, 27, 8) + timedelta(hours=i)) for i in range(10)]
    own = _week_of(10)
    ctx = own + other_account + previous_week
    assert "max_trades_per_week" not in keys(own[9], ctx)


def test_max_trades_ties_ordered_by_key() -> None:
    same_time = [tr(k, utc(11, 2, 8)) for k in range(1, 12)]
    assert "max_trades_per_week" in keys(same_time[10], same_time)
    assert "max_trades_per_week" not in keys(same_time[0], same_time)


# --- max_reentries_per_idea ---------------------------------------------------------------


def _idea() -> list[RuleTradeInput]:
    return [
        tr(1, utc(11, 2, 7, 10), utc(11, 2, 7, 30), "-200"),
        tr(2, utc(11, 2, 7, 40), utc(11, 2, 8), "-200", is_reentry=True),
        tr(3, utc(11, 2, 8, 10), utc(11, 2, 8, 30), "50", is_reentry=True),
    ]


def test_max_reentries_per_idea() -> None:
    idea = _idea()
    assert "max_reentries_per_idea" not in keys(idea[1], idea)
    assert "max_reentries_per_idea" in keys(idea[2], idea)
    assert "max_reentries_per_idea" not in keys(idea[0], idea)
    cfg = rules(max_reentries_per_idea={"enabled": False})
    assert "max_reentries_per_idea" not in keys(idea[2], idea, cfg)


def test_reentries_of_other_ideas_not_counted() -> None:
    idea = _idea()
    ctx = [
        idea[0],
        tr(2, utc(11, 2, 7, 40), None, None, is_reentry=True, direction="sell"),
        tr(4, utc(11, 2, 12, 40), None, None, is_reentry=True, session="ny"),
        tr(5, utc(11, 1, 9), None, None, is_reentry=True),  # previous day
        idea[2],
    ]
    assert "max_reentries_per_idea" not in keys(idea[2], ctx)


# --- min_planned_rr -----------------------------------------------------------------------


@pytest.mark.parametrize(("rr", "hit"), [("1.4999", True), ("1.5", False), ("3", False)])
def test_min_planned_rr(rr: str, hit: bool) -> None:
    assert ("min_planned_rr" in keys(tr(1, utc(11, 2, 8), planned_rr=D(rr)))) is hit


def test_min_planned_rr_missing_tp_and_disabled() -> None:
    assert "min_planned_rr" not in keys(tr(1, utc(11, 2, 8), planned_rr=None))
    cfg = rules(min_planned_rr={"enabled": False})
    assert "min_planned_rr" not in keys(tr(1, utc(11, 2, 8), planned_rr=D("1")), cfg=cfg)


# --- entry_session ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("session", "hit"),
    [
        ("london", False),
        ("ny", False),
        ("premarket", True),
        ("outside", True),
        (None, False),
        ("asia", False),  # not in the config -> no violation
    ],
)
def test_entry_session(session: str | None, hit: bool) -> None:
    assert ("entry_session" in keys(tr(1, utc(11, 2, 8), session=session))) is hit


def test_entry_session_disabled() -> None:
    cfg = rules(entry_session={"enabled": False})
    assert "entry_session" not in keys(tr(1, utc(11, 2, 8), session="outside"), cfg=cfg)


# --- qm_not_in_ny -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "session", "hit"),
    [
        ("qm_m5", "ny", True),
        ("qm_m5", "london", False),
        ("ifvg_m5", "ny", False),
        (None, "ny", False),
    ],
)
def test_qm_not_in_ny(model: str | None, session: str, hit: bool) -> None:
    trade = tr(1, utc(11, 2, 13), session=session, entry_model=model)
    assert ("qm_not_in_ny" in keys(trade)) is hit


def test_qm_not_in_ny_disabled() -> None:
    trade = tr(1, utc(11, 2, 13), session="ny", entry_model="qm_m5")
    assert "qm_not_in_ny" not in keys(trade, cfg=rules(qm_not_in_ny={"enabled": False}))


# --- no_breakeven -------------------------------------------------------------------------


def _be(**kw: Any) -> RuleTradeInput:
    base: dict[str, Any] = {"entry_price": D("2650.00"), "initial_sl": D("2645.00")}
    return tr(1, utc(11, 2, 8), **(base | kw))


@pytest.mark.parametrize(
    ("last_sl", "tick", "hit"),
    [
        ("2650.00", D("0.01"), True),
        ("2650.01", D("0.01"), True),  # within 1 tick
        ("2650.02", D("0.01"), False),
        ("2650.01", None, False),  # no spec: exact equality only
        ("2650.00", None, True),
        ("2648.00", D("0.01"), False),  # trailed, not to entry
        ("2645.00", D("0.01"), False),  # never moved
    ],
)
def test_no_breakeven_last_sl(last_sl: str, tick: Decimal | None, hit: bool) -> None:
    assert ("no_breakeven" in keys(_be(last_sl=D(last_sl)), tick=tick)) is hit


def test_no_breakeven_from_exit_deal() -> None:
    stopped_at_entry = (RuleExitDeal(D("2650.01"), "sl"),)
    assert "no_breakeven" in keys(_be(exit_deals=stopped_at_entry), tick=D("0.01"))
    manual_at_entry = (RuleExitDeal(D("2650.00"), "client"),)
    assert "no_breakeven" not in keys(_be(exit_deals=manual_at_entry), tick=D("0.01"))
    stopped_at_initial = (RuleExitDeal(D("2645.00"), "sl"),)
    assert "no_breakeven" not in keys(_be(exit_deals=stopped_at_initial), tick=D("0.01"))


def test_no_breakeven_needs_initial_sl_elsewhere() -> None:
    assert "no_breakeven" not in keys(_be(initial_sl=None, last_sl=D("2650")))
    assert "no_breakeven" not in keys(_be(initial_sl=D("2650.00"), last_sl=D("2650.00")))
    cfg = rules(no_breakeven={"enabled": False})
    assert "no_breakeven" not in keys(_be(last_sl=D("2650.00")), cfg=cfg)


def test_details_mention_numbers() -> None:
    (v,) = evaluate(_be(last_sl=D("2650.00")), [], RULES, D("0.01"))
    assert v.details == "SL moved from 2645.00 to 2650.00 (entry 2650.00)"


def test_daily_stop_loss_is_sticky_after_recovery() -> None:
    ctx = [
        tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), "-3200.00"),  # -3.20 %
        tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 20), "1000.00"),  # back to -2.20 %
    ]
    trade = tr(1, utc(11, 2, 9), balance="97800")  # day start 100000
    (v,) = [x for x in evaluate(trade, ctx, RULES, None) if x.rule_key == "daily_stop_loss_pct"]
    assert v.details == "day P&L reached -3.20% (-3200.00) before entry <= limit -3.0%"


def test_daily_stop_profit_is_sticky_after_giveback() -> None:
    ctx = [
        tr(11, utc(11, 2, 7, 40), utc(11, 2, 8, 20), "-2000.00"),  # closes second
        tr(10, utc(11, 2, 7, 5), utc(11, 2, 7, 30), "5500.00"),  # +5.50 % first
    ]
    trade = tr(1, utc(11, 2, 9), balance="103500")  # day start 100000, now +3.50 %
    (v,) = [x for x in evaluate(trade, ctx, RULES, None) if x.rule_key == "daily_stop_profit_pct"]
    assert v.details == "day P&L reached 5.50% (5500.00) before entry >= limit 5.0%"
    assert "daily_stop_loss_pct" not in keys(trade, ctx)


def test_weekly_stop_loss_is_sticky() -> None:
    ctx = [
        tr(10, utc(11, 2, 8), utc(11, 2, 9), "-6500"),  # Mon: -6.50 %
        tr(11, utc(11, 3, 8), utc(11, 3, 9), "2000"),  # Tue: back to -4.50 %
    ]
    assert "weekly_stop_loss_pct" in keys(tr(1, utc(11, 4, 8), balance="95500"), ctx)
