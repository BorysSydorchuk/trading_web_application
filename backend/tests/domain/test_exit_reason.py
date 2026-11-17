"""Exit reason prefill from MT5 closing deals (M8-09, docs/api.md M8-09)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.exit_reason import (
    ExitReasonSuggestion,
    final_deal,
    resolve_prefill,
    source_after_owner_save,
    suggest_exit_reason,
)
from app.domain.trade_builder import ExitDeal
from app.models.enums import ExitReasonSource

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
SL = Decimal("1.16200")
TP = Decimal("1.17000")
TICK = Decimal("0.00001")
MT5 = ExitReasonSource.MT5_REASON
PRICE = ExitReasonSource.PRICE_MATCH
OWNER = ExitReasonSource.OWNER


def deal(
    price: str, reason: str | None, *, ticket: int = 1, minutes: int = 0, volume: str = "1"
) -> ExitDeal:
    return ExitDeal(
        ticket=ticket,
        time=T0 + timedelta(minutes=minutes),
        price=Decimal(price),
        volume=Decimal(volume),
        profit=Decimal(0),
        commission=Decimal(0),
        swap=Decimal(0),
        reason=reason,
    )


def suggest(*deals: ExitDeal, tick: Decimal | None = TICK) -> ExitReasonSuggestion | None:
    return suggest_exit_reason(list(deals), initial_sl=SL, tp=TP, tick_size=tick)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [("sl", "sl"), ("tp", "tp"), ("so", "stop_out")],
)
def test_mt5_reason_maps_to_exit_reason(reason: str, expected: str) -> None:
    # The deal reason wins even when the price matches the other stop.
    assert suggest(deal("1.17000", reason)) == ExitReasonSuggestion(expected, MT5)


@pytest.mark.parametrize("reason", ["client", "mobile", "web", "expert"])
def test_manual_close_is_left_for_the_owner(reason: str) -> None:
    # Fractal update or point B target: only the owner knows. No price fallback either.
    assert suggest(deal("1.16200", reason)) is None


@pytest.mark.parametrize(
    "reason", [None, "unknown_42", "rollover", "vmargin", "split", "corporate_action"]
)
def test_missing_reason_falls_back_to_price_within_one_tick(reason: str | None) -> None:
    assert suggest(deal("1.16201", reason)) == ExitReasonSuggestion("sl", PRICE)
    assert suggest(deal("1.16199", reason)) == ExitReasonSuggestion("sl", PRICE)
    assert suggest(deal("1.16999", reason)) == ExitReasonSuggestion("tp", PRICE)
    assert suggest(deal("1.17000", reason)) == ExitReasonSuggestion("tp", PRICE)


def test_missing_reason_without_price_match_stays_empty() -> None:
    assert suggest(deal("1.16202", None)) is None  # 2 ticks away
    assert suggest(deal("1.16600", None)) is None


def test_price_fallback_needs_tick_size_and_stops() -> None:
    assert suggest(deal("1.16200", None), tick=None) is None
    no_stops = suggest_exit_reason(
        [deal("1.16200", None)], initial_sl=None, tp=None, tick_size=TICK
    )
    assert no_stops is None


def test_price_fallback_ignores_unset_zero_stops() -> None:
    # MT5 0 = "not set": a price near 0 is never an SL/TP hit.
    zero = suggest_exit_reason(
        [deal("0.00001", None)], initial_sl=Decimal(0), tp=Decimal(0), tick_size=TICK
    )
    assert zero is None


def test_price_matching_both_stops_is_ambiguous() -> None:
    both = suggest_exit_reason(
        [deal("1.16200", None)], initial_sl=SL, tp=Decimal("1.16201"), tick_size=TICK
    )
    assert both is None


def test_partial_close_uses_the_final_closing_deal() -> None:
    partial = deal("1.16800", "client", ticket=1, minutes=10, volume="0.5")
    final = deal("1.16200", "sl", ticket=2, minutes=40, volume="0.5")
    assert suggest(final, partial) == ExitReasonSuggestion("sl", MT5)
    # Partial TP then manual close of the rest: the final deal is manual -> owner decides.
    tp_part = deal("1.17000", "tp", ticket=3, minutes=5, volume="0.5")
    manual_rest = deal("1.16900", "client", ticket=4, minutes=50, volume="0.5")
    assert suggest(tp_part, manual_rest) is None


def test_final_deal_order_by_time_then_ticket() -> None:
    a = deal("1", "sl", ticket=5, minutes=1)
    b = deal("1", "tp", ticket=6, minutes=1)
    c = deal("1", "so", ticket=4, minutes=0)
    assert final_deal([b, a, c]) is b
    assert final_deal([]) is None
    assert suggest() is None


# --- resolve_prefill: what the sync may write ---


def test_empty_value_is_prefilled() -> None:
    assert resolve_prefill(None, None, ExitReasonSuggestion("sl", MT5)) == ("sl", "mt5_reason")


def test_empty_value_without_suggestion_is_left() -> None:
    assert resolve_prefill(None, None, None) is None


def test_existing_value_without_source_is_never_overwritten() -> None:
    # Entered before M8-09 (by the owner or AI): no source, kept as it is.
    assert resolve_prefill("fractal_update", None, ExitReasonSuggestion("sl", MT5)) is None


def test_owner_value_is_never_overwritten_even_when_cleared() -> None:
    assert resolve_prefill("point_b", "owner", ExitReasonSuggestion("tp", MT5)) is None
    assert resolve_prefill(None, "owner", ExitReasonSuggestion("tp", MT5)) is None


def test_prefilled_value_follows_the_deals() -> None:
    assert resolve_prefill("sl", "price_match", ExitReasonSuggestion("sl", MT5)) == (
        "sl",
        "mt5_reason",
    )
    assert resolve_prefill("sl", "mt5_reason", None) == (None, None)
    assert resolve_prefill("sl", "mt5_reason", ExitReasonSuggestion("sl", MT5)) == (
        "sl",
        "mt5_reason",
    )


# --- source_after_owner_save: what a journal save does ---


def test_owner_change_marks_owner() -> None:
    assert source_after_owner_save("sl", "fractal_update", "mt5_reason") == "owner"
    assert source_after_owner_save("sl", None, "mt5_reason") == "owner"  # cleared
    assert source_after_owner_save(None, "tp", None) == "owner"


def test_unchanged_value_keeps_its_source() -> None:
    assert source_after_owner_save("sl", "sl", "mt5_reason") == "mt5_reason"
    assert source_after_owner_save(None, None, None) is None
    assert source_after_owner_save("tp", "tp", "owner") == "owner"
