"""FixtureMt5Source.quote / calc_profit (M5-09), the offline stand-ins for the real source.

New `Mt5Source` methods (also on `RealMt5Source`, see test_real_fx.py):

- ``quote(symbol) -> RawQuote | None``; ``RawQuote(bid, ask, time)`` is a frozen dataclass in
  ``app.mt5.types`` (Decimal bid/ask, ``time`` = server wall epoch like every MT5 time).
- ``calc_profit(direction, symbol, volume, price_open, price_close) -> Decimal``.

Fixture keys (top level and per step, a step replaces the previous value):

    "quotes":         {"EURUSD": {"bid": "1.10905", "ask": "1.1091", "time": <server epoch>}}
    "profit_per_tick": {"GER30": "0.011091"}   # account currency per tick per 1.0 lot

``calc_profit`` = ``(close - open) / tick_size * per_tick * volume`` for a buy, negated for a
sell, exact Decimal (no 2-dp rounding), tick size from the fixture's symbol spec. No entry for
the symbol (or no spec) -> `Mt5Error(mt5_error)`. Failure method names: ``quote``,
``calc_profit``. Needs ``connect`` like every read.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from app.mt5.types import RawQuote

D = Decimal
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mt5"
LOGIN = 51234571
SERVER = "FundedNext-Server"
QUOTE_TIME = 1_793_721_600  # 2026-11-03 16:00 server wall


def base() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "funded_next_ger30.json").read_text("utf-8"))
    return copy.deepcopy(data)


def with_fx(**extra: Any) -> dict[str, Any]:
    data = base()
    data["quotes"] = {
        "EURUSD": {"bid": "1.10905", "ask": "1.1091", "time": QUOTE_TIME},
        "GER30": {"bid": "24099.50", "ask": "24100.50", "time": QUOTE_TIME},
    }
    data["profit_per_tick"] = {"GER30": "0.011091"}
    return data | extra


def connected(data: dict[str, Any]) -> FixtureMt5Source:
    src = FixtureMt5Source(data)
    src.connect("D:\\MT5\\fn\\terminal64.exe", LOGIN, SecretStr("x"), SERVER)
    return src


# --- quote --------------------------------------------------------------------------------------


def test_quote_returns_bid_ask_and_server_time() -> None:
    quote = connected(with_fx()).quote("EURUSD")

    assert quote == RawQuote(bid=D("1.10905"), ask=D("1.1091"), time=QUOTE_TIME)
    assert isinstance(quote, RawQuote)
    assert isinstance(quote.bid, Decimal)


def test_quote_of_an_unknown_symbol_is_none() -> None:
    assert connected(with_fx()).quote("NOPE") is None


def test_quote_without_a_quotes_key_is_none() -> None:
    assert connected(base()).quote("EURUSD") is None


def test_quote_needs_a_connection() -> None:
    src = FixtureMt5Source(with_fx())

    with pytest.raises(Mt5Error) as err:
        src.quote("EURUSD")

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_quote_failure_can_be_scripted() -> None:
    src = connected(with_fx(failures={"quote": {"code": "timeout", "message": "slow"}}))

    with pytest.raises(Mt5Error) as err:
        src.quote("EURUSD")

    assert err.value.code is Mt5ErrorCode.TIMEOUT


def test_quotes_are_replaced_by_a_step() -> None:
    data = with_fx(
        steps=[{"quotes": {"EURUSD": {"bid": "1.2", "ask": "1.2001", "time": QUOTE_TIME + 60}}}]
    )
    src = FixtureMt5Source(data)
    src.connect("D:\\MT5\\fn\\terminal64.exe", LOGIN, SecretStr("x"), SERVER)
    assert src.quote("EURUSD") is not None
    src.advance()
    src.connect("D:\\MT5\\fn\\terminal64.exe", LOGIN, SecretStr("x"), SERVER)

    assert src.quote("EURUSD") == RawQuote(bid=D("1.2"), ask=D("1.2001"), time=QUOTE_TIME + 60)
    assert src.quote("GER30") is None  # replaced, not merged


@pytest.mark.parametrize(
    "bad",
    [
        {"EURUSD": {"bid": "x", "ask": "1.1", "time": 1}},
        {"EURUSD": {"bid": "1.1", "ask": "1.1"}},
        {"EURUSD": {"bid": "1.1", "ask": "1.1", "time": "soon"}},
        {"EURUSD": "1.1"},
    ],
)
def test_bad_quotes_fail_loading(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r".+"):
        FixtureMt5Source(with_fx(quotes=bad))


# --- calc_profit --------------------------------------------------------------------------------


def test_buy_with_a_lower_close_is_a_loss_of_ticks_times_per_tick() -> None:
    src = connected(with_fx())

    result = src.calc_profit("buy", "GER30", D("1"), D("24100.50"), D("24000.50"))

    assert result == D("-100") / D("0.01") * D("0.011091")  # 10000 ticks -> -110.91
    assert result == D("-110.91")


def test_sell_with_a_higher_close_is_a_loss() -> None:
    result = connected(with_fx()).calc_profit("sell", "GER30", D("1"), D("100"), D("101"))

    assert result == D("-1.1091")


def test_sell_with_a_lower_close_is_a_profit() -> None:
    result = connected(with_fx()).calc_profit("sell", "GER30", D("1"), D("100"), D("99"))

    assert result == D("1.1091")


def test_profit_is_linear_in_volume() -> None:
    src = connected(with_fx())

    one = src.calc_profit("buy", "GER30", D("1"), D("100"), D("99"))
    half = src.calc_profit("buy", "GER30", D("0.5"), D("100"), D("99"))

    assert half == one / 2


def test_calc_profit_without_data_for_the_symbol_is_an_mt5_error() -> None:
    src = connected(with_fx())

    with pytest.raises(Mt5Error) as err:
        src.calc_profit("buy", "EURUSD", D("1"), D("1.1"), D("1.09"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_calc_profit_without_the_key_is_an_mt5_error() -> None:
    src = connected(base())

    with pytest.raises(Mt5Error) as err:
        src.calc_profit("buy", "GER30", D("1"), D("100"), D("99"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_calc_profit_rejects_an_unknown_direction() -> None:
    with pytest.raises(ValueError, match=r".+"):
        connected(with_fx()).calc_profit("hold", "GER30", D("1"), D("100"), D("99"))  # type: ignore[arg-type]


def test_calc_profit_failure_can_be_scripted() -> None:
    src = connected(with_fx(failures={"calc_profit": {"code": "mt5_error", "message": "boom"}}))

    with pytest.raises(Mt5Error, match="boom"):
        src.calc_profit("buy", "GER30", D("1"), D("100"), D("99"))


def test_non_positive_profit_per_tick_fails_loading() -> None:
    with pytest.raises(ValueError, match=r".+"):
        FixtureMt5Source(with_fx(profit_per_tick={"GER30": "0"}))
    with pytest.raises(ValueError, match=r".+"):
        FixtureMt5Source(with_fx(profit_per_tick={"GER30": "abc"}))


def test_calc_profit_needs_a_connection() -> None:
    src = FixtureMt5Source(with_fx())

    with pytest.raises(Mt5Error):
        src.calc_profit("buy", "GER30", D("1"), D("100"), D("99"))
