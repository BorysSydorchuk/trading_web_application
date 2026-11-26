"""Rules engine `firm_daily_loss` (docs/api.md "Firm rules from config: KeyFunding").

An entry opened after the account's realized firm-day P&L reached <= -daily_loss_pct of the
size (trades closed before the entry, since that entry's firm day reset). Sticky within the
firm day, resets at the firm reset, only for accounts with a firm rule on the trade input.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from decimal import Decimal

from app.domain.firm_rules import FirmDayRule
from app.domain.rules import RuleTradeInput, evaluate
from tests.domain.test_rules import RULES, tr, utc

D = Decimal
FIRM = FirmDayRule(
    daily_loss_pct=D(4), daily_reset=time(0), reset_timezone="server", server_offset_hours=0
)


def with_firm(trade: RuleTradeInput, firm: FirmDayRule | None = FIRM) -> RuleTradeInput:
    return replace(trade, firm=firm)


def firm_violations(entry: RuleTradeInput, context: list[RuleTradeInput]) -> list[str]:
    return [
        v.details for v in evaluate(entry, context, RULES, None) if v.rule_key == "firm_daily_loss"
    ]


def loss(key: int, closed_at: tuple[int, int, int], pnl: str, **kw: object) -> RuleTradeInput:
    day, hour, minute = closed_at
    opened = utc(11, day, max(hour - 1, 0), minute)
    return with_firm(tr(key, opened, utc(11, day, hour, minute), pnl, size="10000", **kw))  # type: ignore[arg-type]


def entry(day: int, hour: int, minute: int = 0, firm: FirmDayRule | None = FIRM) -> RuleTradeInput:
    return with_firm(tr(99, utc(11, day, hour, minute), size="10000"), firm)


def test_entry_after_the_firm_daily_loss_is_flagged() -> None:
    details = firm_violations(entry(12, 8), [loss(1, (12, 3, 0), "-400")])

    assert details == [
        "firm day P&L reached -4.00% (-400.00) before entry <= firm limit -4%",
    ]


def test_loss_just_inside_the_limit_is_not_flagged() -> None:
    assert firm_violations(entry(12, 8), [loss(1, (12, 3, 0), "-399.99")]) == []


def test_sums_several_trades_of_the_firm_day() -> None:
    context = [loss(1, (12, 2, 0), "-250"), loss(2, (12, 4, 0), "-150")]

    assert len(firm_violations(entry(12, 8), context)) == 1


def test_sticky_after_the_pnl_recovered() -> None:
    context = [loss(1, (12, 2, 0), "-450"), loss(2, (12, 4, 0), "500")]

    assert len(firm_violations(entry(12, 8), context)) == 1


def test_only_entries_after_the_loss_closed_are_flagged() -> None:
    context = [loss(1, (12, 5, 0), "-450")]

    assert firm_violations(entry(12, 4, 30), context) == []  # the loss closed 05:00, later
    assert len(firm_violations(entry(12, 5, 1), context)) == 1


def test_a_loss_closed_exactly_at_the_entry_is_not_counted() -> None:
    assert firm_violations(entry(12, 5, 0), [loss(1, (12, 5, 0), "-450")]) == []


def test_new_firm_day_starts_clean() -> None:
    context = [loss(1, (12, 20, 0), "-450")]

    assert len(firm_violations(entry(12, 23, 59), context)) == 1
    assert firm_violations(entry(13, 0, 0), context) == []
    assert firm_violations(entry(13, 0, 1), context) == []


def test_a_loss_before_the_reset_does_not_count_for_an_entry_after_it() -> None:
    assert firm_violations(entry(12, 0, 5), [loss(1, (11, 23, 55), "-450")]) == []


def test_reset_moves_with_the_server_offset() -> None:
    plus_two = replace(FIRM, server_offset_hours=2)  # firm day starts 22:00 UTC
    closed_at_20 = [loss(1, (12, 20, 0), "-450")]

    assert len(firm_violations(entry(12, 21, 30, plus_two), closed_at_20)) == 1
    assert firm_violations(entry(12, 22, 30, plus_two), closed_at_20) == []


def test_brussels_day_and_firm_day_are_independent() -> None:
    # 23:30 UTC is already the next Brussels day (00:30) but still the same firm day (offset 0)
    context = [loss(1, (12, 20, 0), "-450")]

    assert len(firm_violations(entry(12, 23, 30), context)) == 1


def test_trade_without_a_firm_rule_is_never_flagged() -> None:
    context = [loss(1, (12, 3, 0), "-900")]

    assert firm_violations(entry(12, 8, firm=None), context) == []


def test_no_usable_size_is_no_violation() -> None:
    no_size = replace(entry(12, 8), account_size=None)
    zero_size = replace(entry(12, 8), account_size=D(0))
    context = [loss(1, (12, 3, 0), "-900")]

    assert firm_violations(no_size, context) == []
    assert firm_violations(zero_size, context) == []


def test_other_accounts_trades_are_ignored() -> None:
    context = [loss(1, (12, 3, 0), "-900", account_id=2)]

    assert firm_violations(entry(12, 8), context) == []


def test_open_trades_and_unknown_pnl_are_ignored() -> None:
    open_trade = with_firm(tr(1, utc(11, 12, 1), None, None, size="10000"))
    unknown = with_firm(tr(2, utc(11, 12, 1), utc(11, 12, 2), None, size="10000"))

    assert firm_violations(entry(12, 8), [open_trade, unknown]) == []


def test_the_entry_itself_in_the_context_is_ignored() -> None:
    entry_trade = entry(12, 8)

    assert firm_violations(entry_trade, [entry_trade]) == []


def test_firm_loss_is_independent_of_the_personal_daily_stop() -> None:
    # -3.5 %: the personal -3 % stop fires, the firm -4 % limit does not
    result = evaluate(entry(12, 8), [loss(1, (12, 3, 0), "-350")], RULES, None)

    assert {v.rule_key for v in result} >= {"daily_risk"}
    assert "firm_daily_loss" not in {v.rule_key for v in result}


def test_firm_violation_is_in_engine_keys() -> None:
    from app.config_files.rules import ENGINE_RULE_KEYS

    assert "firm_daily_loss" in ENGINE_RULE_KEYS
