"""Pure cross-currency helpers (docs/api.md "M5-09 Cross-currency loss value").

Module under test: ``app.domain.fx`` (new). Names pinned here:

- ``STALE_AFTER`` (1 h), ``CHECK_TOLERANCE`` (Decimal 0.005)
- ``is_cross_currency(profit_currency, account_currency) -> bool``
- ``loss_per_tick_from_rate(tick_size, contract_size, rate) -> Decimal``
- ``ConversionPair(pair, inverted, side)`` frozen dataclass, ``pick_conversion_pair(
  profit_currency, account_currency, broker_symbols) -> ConversionPair | None``
- ``conversion_rate(pair, bid, ask) -> Decimal`` (ask, or 1 / bid when inverted)
- ``check_tick_count(price, tick_size) -> int`` and ``check_loss_per_tick(result, ticks)``
- ``choose_loss_per_tick(rate_value, mt5_value) -> tuple[Decimal, "rate" | "mt5_check"]``
- ``is_stale(rate_at, now) -> bool`` (strictly older than 1 h; exactly 1 h is not stale)
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import fx

D = Decimal


# --- cross-currency detection ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("profit", "account", "expected"),
    [
        ("EUR", "USD", True),
        ("USD", "USD", False),
        ("usd", "USD", False),
        ("USD", "usd", False),
        ("eur", "USD", True),
        ("JPY", "EUR", True),
    ],
)
def test_is_cross_currency_is_case_insensitive(profit: str, account: str, expected: bool) -> None:
    assert fx.is_cross_currency(profit, account) is expected


@pytest.mark.parametrize(("profit", "account"), [("", "USD"), ("EUR", ""), ("  ", "USD"), ("", "")])
def test_blank_currency_is_never_cross_currency(profit: str, account: str) -> None:
    assert fx.is_cross_currency(profit, account) is False


# --- loss per tick from the rate ----------------------------------------------------------------


def test_real_ger30_case_is_exact() -> None:
    # FundedNext GER30: tick 0.01, contract 10, EURUSD 1.1091 -> 0.11091 USD per tick per lot.
    result = fx.loss_per_tick_from_rate(D("0.01"), D("10"), D("1.1091"))

    assert result == D("0.11091")
    assert isinstance(result, Decimal)


def test_loss_per_tick_keeps_full_precision_no_float_noise() -> None:
    assert fx.loss_per_tick_from_rate(D("0.00001"), D("100000"), D("0.9123456")) == D("0.9123456")


@pytest.mark.parametrize("bad", [D("0"), D("-1.1")])
def test_loss_per_tick_rejects_non_positive_rate(bad: Decimal) -> None:
    with pytest.raises(ValueError, match=r".+"):
        fx.loss_per_tick_from_rate(D("0.01"), D("10"), bad)


# --- pair choice --------------------------------------------------------------------------------


def test_direct_pair_uses_ask() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["GBPUSD", "EURUSD", "XAUUSD"])

    assert pair == fx.ConversionPair(pair="EURUSD", inverted=False, side="ask")


def test_inverse_pair_uses_bid() -> None:
    pair = fx.pick_conversion_pair("CHF", "USD", ["EURUSD", "USDCHF"])

    assert pair == fx.ConversionPair(pair="USDCHF", inverted=True, side="bid")


def test_direct_pair_beats_inverse_when_both_exist() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["USDEUR", "EURUSD"])

    assert pair is not None
    assert (pair.pair, pair.inverted) == ("EURUSD", False)


def test_exact_name_is_case_insensitive_and_keeps_broker_spelling() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["eurusd"])

    assert pair is not None
    assert pair.pair == "eurusd"


def test_exact_name_beats_prefix_match() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["EURUSD.a", "EURUSD", "EURUSD.r"])

    assert pair is not None
    assert pair.pair == "EURUSD"


def test_prefix_match_finds_suffixed_symbol() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["GBPUSD.r", "EURUSD.r"])

    assert pair == fx.ConversionPair(pair="EURUSD.r", inverted=False, side="ask")


def test_several_prefix_matches_take_the_first_sorted_and_list_the_candidates() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["EURUSD.r", "EURUSD_x", "EURUSD#"])

    assert pair is not None
    assert pair.pair == "EURUSD#"  # '#' < '.' < '_'
    assert pair.candidates == ("EURUSD#", "EURUSD.r", "EURUSD_x")  # ambiguity: sync warns


def test_single_prefix_match_lists_only_itself() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["EURUSD.r"])

    assert pair is not None
    assert pair.candidates == ("EURUSD.r",)


def test_exact_match_has_no_prefix_candidates() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["EURUSD", "EURUSD.r"])

    assert pair is not None
    assert pair.candidates == ()


@pytest.mark.parametrize(
    "name", ["EURUSD.r", "EURUSD_x", "EURUSD#", "EURUSD-1", "EURUSD2", "eurusd.r"]
)
def test_prefix_match_accepts_a_non_letter_suffix(name: str) -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", [name])

    assert pair is not None
    assert pair.pair == name


@pytest.mark.parametrize("name", ["EURUSDT", "EURUSDm", "EURUSDX.r"])
def test_prefix_match_rejects_a_letter_right_after_the_pair(name: str) -> None:
    """EURUSDT (a crypto/other symbol) is not the EURUSD pair."""
    assert fx.pick_conversion_pair("EUR", "USD", [name]) is None


def test_letter_suffix_is_skipped_for_a_valid_suffix() -> None:
    pair = fx.pick_conversion_pair("EUR", "USD", ["EURUSDT", "EURUSD.r"])

    assert pair is not None
    assert (pair.pair, pair.candidates) == ("EURUSD.r", ("EURUSD.r",))


def test_inverse_prefix_match() -> None:
    pair = fx.pick_conversion_pair("CHF", "USD", ["USDCHF.r"])

    assert pair == fx.ConversionPair(pair="USDCHF.r", inverted=True, side="bid")


@pytest.mark.parametrize("names", [[], ["GBPUSD", "XAUUSD"], ["EUR", "USD"], ["AEURUSD"]])
def test_no_pair_returns_none(names: list[str]) -> None:
    assert fx.pick_conversion_pair("EUR", "USD", names) is None


def test_conversion_pair_is_frozen() -> None:
    pair = fx.ConversionPair(pair="EURUSD", inverted=False, side="ask")

    with pytest.raises(dataclasses.FrozenInstanceError):
        pair.pair = "X"  # type: ignore[misc]


# --- rate from a quote --------------------------------------------------------------------------


def test_direct_rate_is_the_ask() -> None:
    pair = fx.ConversionPair(pair="EURUSD", inverted=False, side="ask")

    assert fx.conversion_rate(pair, bid=D("1.10905"), ask=D("1.1091")) == D("1.1091")


def test_inverse_rate_is_one_over_bid() -> None:
    pair = fx.ConversionPair(pair="USDCHF", inverted=True, side="bid")

    assert fx.conversion_rate(pair, bid=D("0.8"), ask=D("0.9")) == D("1.25")


@pytest.mark.parametrize("bid", [D("0"), D("-1")])
def test_inverse_rate_rejects_non_positive_bid(bid: Decimal) -> None:
    pair = fx.ConversionPair(pair="USDCHF", inverted=True, side="bid")

    with pytest.raises(ValueError, match=r".+"):
        fx.conversion_rate(pair, bid=bid, ask=D("0.9"))


# --- choice between the rate value and the MT5 check ---------------------------------------------


def test_tolerance_constant_is_half_a_percent() -> None:
    assert D("0.005") == fx.CHECK_TOLERANCE


def test_missing_check_uses_the_rate_value() -> None:
    assert fx.choose_loss_per_tick(D("0.11091"), None) == (D("0.11091"), "rate")


def test_check_within_tolerance_keeps_the_rate_value() -> None:
    assert fx.choose_loss_per_tick(D("0.11091"), D("0.11120")) == (D("0.11091"), "rate")


def test_check_exactly_half_a_percent_away_keeps_the_rate_value() -> None:
    rate_value = D("0.2")
    check = rate_value * D("1.005")  # exactly 0.5 % above

    assert fx.choose_loss_per_tick(rate_value, check) == (rate_value, "rate")
    assert fx.choose_loss_per_tick(rate_value, rate_value * D("0.995")) == (rate_value, "rate")


def test_check_just_over_half_a_percent_wins() -> None:
    check = D("0.2") * D("1.0051")

    assert fx.choose_loss_per_tick(D("0.2"), check) == (check, "mt5_check")


def test_stale_real_case_check_wins_below_too() -> None:
    # The broker's own 0.12 against the real 0.11091 (+8 %).
    assert fx.choose_loss_per_tick(D("0.11091"), D("0.12")) == (D("0.12"), "mt5_check")
    assert fx.choose_loss_per_tick(D("0.2"), D("0.19")) == (D("0.19"), "mt5_check")


# --- MT5 check (order_calc_profit) ---------------------------------------------------------------


def test_check_tick_count_is_one_percent_of_price_in_ticks() -> None:
    # p = 26478.80, tick 0.01: 1 % = 264.788 -> 26478 ticks.
    assert fx.check_tick_count(D("26478.80"), D("0.01")) == 26478


def test_check_tick_count_floors() -> None:
    assert fx.check_tick_count(D("24100.50"), D("0.01")) == 24100
    assert fx.check_tick_count(D("1.1091"), D("0.00001")) == 1109


def test_check_loss_per_tick_is_abs_result_over_ticks() -> None:
    assert fx.check_loss_per_tick(D("-2929.67"), 26478) == D("-2929.67").copy_abs() / 26478
    assert fx.check_loss_per_tick(D("2929.67"), 26478) == D("2929.67") / 26478


def test_check_loss_per_tick_rejects_non_positive_tick_count() -> None:
    with pytest.raises(ValueError, match=r".+"):
        fx.check_loss_per_tick(D("-1"), 0)


# --- staleness ----------------------------------------------------------------------------------

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def test_rate_older_than_an_hour_is_stale() -> None:
    assert fx.is_stale(NOW - timedelta(hours=1, seconds=1), NOW) is True
    assert fx.is_stale(NOW - timedelta(hours=2), NOW) is True


def test_rate_exactly_one_hour_old_is_not_stale() -> None:
    assert fx.is_stale(NOW - timedelta(hours=1), NOW) is False


def test_fresh_rate_is_not_stale() -> None:
    assert fx.is_stale(NOW - timedelta(minutes=5), NOW) is False
    assert fx.is_stale(NOW, NOW) is False


def test_stale_after_is_one_hour() -> None:
    assert timedelta(hours=1) == fx.STALE_AFTER
