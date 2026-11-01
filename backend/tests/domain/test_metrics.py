from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.domain.metrics import (
    ReentryCandidate,
    balance_at_open,
    planned_rr,
    pnl_pct,
    r_multiple,
    reentry_flags,
    risk_amount,
    risk_pct,
)
from app.domain.trade_builder import Deal, DealEntry, DealType, build_trades

D = Decimal


def t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def test_xauusd_full_chain() -> None:
    # Example from docs/api.md: 0.5 lot XAUUSD, contract 100, tick 0.01 = 1 USD.
    entry, exit_, sl, tp = D("2650.12"), D("2661.40"), D("2645.00"), D("2668.00")
    risk = risk_amount(
        entry_price=entry,
        initial_sl=sl,
        volume=D("0.5"),
        exit_price=exit_,
        exit_volume=D("0.5"),
        gross_pnl=D("564.00"),
    )
    assert risk == D("256.00")
    assert risk_pct(risk, D("100000.00")) == D("0.2560")
    assert pnl_pct(D("560.50"), D("100000.00")) == D("0.5605")
    assert r_multiple(D("560.50"), risk) == D("2.1895")
    assert planned_rr(entry, sl, tp) == D("3.4922")


def test_ger40_realised_conversion_needs_no_fx() -> None:
    # GER40: 1 EUR per point per lot, USD account. 100 points won = 108.00 USD
    # (EURUSD 1.08 at close, never passed in). Risk 50 points -> 54.00 USD exactly.
    common = {"entry_price": D("19000.0"), "initial_sl": D("18950.0"), "volume": D("1")}
    realised = risk_amount(
        **common,
        exit_price=D("19100.0"),
        exit_volume=D("1"),
        gross_pnl=D("108.00"),
        tick_size=D("0.1"),
        tick_value=D("0.1084"),  # today's rate: ignored
    )
    assert realised == D("54.00")
    # Same for a 0.01 tick spec and a different lot size.
    realised_small = risk_amount(
        entry_price=D("19000.00"),
        initial_sl=D("18950.00"),
        volume=D("0.5"),
        exit_price=D("19100.00"),
        exit_volume=D("0.5"),
        gross_pnl=D("54.00"),
        tick_size=D("0.01"),
        tick_value=D("0.0108"),
    )
    assert realised_small == D("27.00")
    # The spec fallback would use today's conversion and differ.
    assert risk_amount(**common, tick_size=D("0.1"), tick_value=D("0.1084")) == D("54.20")


def test_partial_close_three_exits_risk() -> None:
    # Sell 1.0 @2700, SL 2705; exits 0.3@2690, 0.3@2685, 0.4@2695 -> VWAP 2690.5, gross 950.
    risk = risk_amount(
        entry_price=D("2700.00"),
        initial_sl=D("2705.00"),
        volume=D("1.0"),
        exit_price=D("2690.50"),
        exit_volume=D("1.0"),
        gross_pnl=D("950.00"),
    )
    assert risk == D("500.00")
    assert r_multiple(D("934.80"), risk) == D("1.8696")


def test_partially_closed_open_trade_scales_by_volume() -> None:
    # Only 0.3 of 1.0 closed so far: conversion from the 0.3, risk on the full 1.0.
    risk = risk_amount(
        entry_price=D("2700.00"),
        initial_sl=D("2705.00"),
        volume=D("1.0"),
        exit_price=D("2690.00"),
        exit_volume=D("0.3"),
        gross_pnl=D("300.00"),
    )
    assert risk == D("500.00")


def test_scale_in_eurusd() -> None:
    risk = risk_amount(
        entry_price=D("1.08400"),
        initial_sl=D("1.08200"),
        volume=D("1.0"),
        exit_price=D("1.08700"),
        exit_volume=D("1.0"),
        gross_pnl=D("300.00"),
    )
    assert risk == D("200.00")


def test_losing_gbpusd() -> None:
    risk = risk_amount(
        entry_price=D("1.27000"),
        initial_sl=D("1.27250"),
        volume=D("0.8"),
        exit_price=D("1.27250"),
        exit_volume=D("0.8"),
        gross_pnl=D("-200.00"),
    )
    assert risk == D("200.00")
    assert r_multiple(D("-205.60"), risk) == D("-1.0280")
    assert pnl_pct(D("-205.60"), D("50000")) == D("-0.4112")


def test_breakeven_uses_spec_fallback() -> None:
    args = {
        "entry_price": D("2650.00"),
        "initial_sl": D("2645.00"),
        "volume": D("0.5"),
        "exit_price": D("2650.00"),
        "exit_volume": D("0.5"),
        "gross_pnl": D("0.00"),
    }
    assert risk_amount(**args, tick_size=D("0.01"), tick_value=D("1")) == D("250.00")
    assert risk_amount(**args) is None  # no spec -> never invent
    assert r_multiple(D("-3.50"), D("250.00")) == D("-0.0140")


def test_missing_inputs_return_none() -> None:
    assert risk_amount(entry_price=D("1"), initial_sl=None, volume=D("1")) is None
    assert risk_amount(entry_price=None, initial_sl=D("1"), volume=D("1")) is None
    assert risk_pct(None, D("100000")) is None
    assert risk_pct(D("100"), None) is None
    assert risk_pct(D("100"), D("0")) is None
    assert pnl_pct(None, D("100000")) is None
    assert r_multiple(D("100"), None) is None
    assert r_multiple(None, D("100")) is None
    assert planned_rr(D("100"), D("99"), None) is None
    assert planned_rr(D("100"), None, D("103")) is None


def test_sl_at_entry() -> None:
    risk = risk_amount(entry_price=D("100"), initial_sl=D("100"), volume=D("1"))
    assert risk == D("0.00")
    assert r_multiple(D("10"), risk) is None
    assert planned_rr(D("100"), D("100"), D("103")) is None


def test_rounding_half_up() -> None:
    assert risk_pct(D("1.00005"), D("100")) == D("1.0001")  # 1.000050 % -> half up
    assert planned_rr(D("100"), D("97"), D("105")) == D("1.6667")


def _deal(ticket: int, when: datetime, type_: DealType, entry: DealEntry, **money: str) -> Deal:
    return Deal(
        ticket=ticket,
        order=ticket,
        position_id=ticket if type_ is not DealType.BALANCE else 0,
        time=when,
        type=type_,
        entry=entry,
        volume=D("0.5"),
        price=D("2650"),
        profit=D(money.get("profit", "0")),
        commission=D(money.get("commission", "0")),
        swap=D(money.get("swap", "0")),
        fee=D(money.get("fee", "0")),
        symbol="XAUUSD",
    )


def test_balance_at_open() -> None:
    deals = [
        _deal(1, t(1, 0), DealType.BALANCE, DealEntry.IN, profit="100000.00"),  # before open
        _deal(2, t(2, 8), DealType.BUY, DealEntry.IN, commission="-1.75"),  # at open
        _deal(3, t(2, 9), DealType.SELL, DealEntry.OUT, profit="564.00", commission="-1.75"),
        _deal(
            4, t(3, 9), DealType.SELL, DealEntry.OUT, profit="-120.00", swap="-2.00", fee="-0.50"
        ),
        _deal(5, t(4, 9), DealType.BALANCE, DealEntry.IN, profit="-1000.00"),  # withdrawal
    ]
    current = D("100000") - D("1.75") + D("564") - D("1.75") - D("120") - D("2.5") - D("1000")
    assert balance_at_open(current, t(2, 8), deals) == D("100000.00")
    assert balance_at_open(None, t(2, 8), deals) is None


def test_builder_feeds_metrics() -> None:
    built = build_trades(
        [
            Deal(
                1,
                1,
                1,
                t(2, 8),
                DealType.BUY,
                DealEntry.IN,
                D("0.5"),
                D("2650.12"),
                D("0"),
                "XAUUSD",
                commission=D("-1.75"),
                sl=D("2645.00"),
            ),
            Deal(
                2,
                2,
                1,
                t(2, 9),
                DealType.SELL,
                DealEntry.OUT,
                D("0.5"),
                D("2661.40"),
                D("564.00"),
                "XAUUSD",
                commission=D("-1.75"),
            ),
        ]
    ).trades[0]
    risk = risk_amount(
        entry_price=built.entry_price,
        initial_sl=built.initial_sl,
        volume=built.volume,
        exit_price=built.exit_price,
        exit_volume=built.exit_volume,
        gross_pnl=built.gross_pnl,
    )
    assert risk == D("256.00")
    assert r_multiple(built.net_pnl, risk) == D("2.1895")


# --- re-entry -----------------------------------------------------------------------------


def cand(
    key: int,
    open_: datetime,
    close: datetime | None,
    pnl: str | None,
    *,
    symbol: str = "XAUUSD",
    direction: str = "buy",
    session: str | None = "london",
    account_id: int = 1,
) -> ReentryCandidate:
    return ReentryCandidate(
        key, account_id, symbol, direction, session, open_, close, D(pnl) if pnl else None
    )


def test_reentry_after_loss_same_session() -> None:
    flags = reentry_flags(
        [
            cand(1, t(2, 8, 10), t(2, 8, 40), "-205.60"),  # 09:10 Brussels, loss
            cand(2, t(2, 9, 0), t(2, 9, 30), "300.00"),  # 10:00, same idea -> re-entry
            cand(3, t(2, 9, 45), None, None),  # still open, after the loss -> re-entry
        ]
    )
    assert flags == {1: False, 2: True, 3: True}


def test_not_reentry_other_session_or_day_or_idea() -> None:
    flags = reentry_flags(
        [
            cand(1, t(2, 8, 10), t(2, 8, 40), "-100"),
            cand(2, t(2, 13, 30), None, None, session="ny"),  # next session
            cand(3, t(3, 8, 10), None, None),  # next day
            cand(4, t(2, 9, 0), None, None, direction="sell"),  # other direction
            cand(5, t(2, 9, 0), None, None, symbol="GER40"),  # other symbol
            cand(6, t(2, 9, 0), None, None, account_id=2),  # other account
            cand(7, t(2, 8, 20), None, None),  # opened before the loss closed
            cand(8, t(2, 9, 0), None, None, session=None),  # unknown session
        ]
    )
    assert not any(flags.values())


def test_not_reentry_after_win() -> None:
    flags = reentry_flags(
        [
            cand(1, t(2, 8, 10), t(2, 8, 40), "250.00", symbol="EURUSD", direction="sell"),
            cand(2, t(2, 9, 0), None, None, symbol="EURUSD", direction="sell"),
            cand(3, t(2, 9, 5), t(2, 9, 10), "0.00", symbol="GBPUSD"),  # flat is not a loss
            cand(4, t(2, 9, 20), None, None, symbol="GBPUSD"),
        ]
    )
    assert flags == {1: False, 2: False, 3: False, 4: False}


def test_reentry_brussels_day_not_utc_day() -> None:
    # Nov 2 23:10 UTC = Nov 3 00:10 Brussels; Nov 2 22:30 UTC = Nov 2 23:30 Brussels.
    flags = reentry_flags(
        [
            cand(1, t(2, 22, 30), t(2, 22, 50), "-10", session="outside"),
            cand(2, t(2, 23, 10), None, None, session="outside"),
        ]
    )
    assert flags[2] is False


def test_tiny_move_switches_to_spec_fallback() -> None:
    # GER40 closed 2 ticks (0.2) from entry with a 50-point SL: profit 0.22 USD is rounded
    # to 2 dp, so the realised formula would be noisy (0.22 * 50 / 0.2 = 55.00).
    tiny = {
        "entry_price": D("19000.0"),
        "initial_sl": D("18950.0"),
        "volume": D("1"),
        "exit_price": D("19000.2"),
        "exit_volume": D("1"),
        "gross_pnl": D("0.22"),
    }
    assert risk_amount(**tiny, tick_size=D("0.1"), tick_value=D("0.1084")) == D("54.20")
    assert risk_amount(**tiny) == D("55.00")  # no spec: realised formula still used
    # At the threshold (move = 10 % of SL distance = 5 points) the realised formula is used.
    at_threshold = {**tiny, "exit_price": D("19005.0"), "gross_pnl": D("5.40")}
    assert risk_amount(**at_threshold, tick_size=D("0.1"), tick_value=D("0.1084")) == D("54.00")
