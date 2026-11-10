"""FixtureMt5Source.calc_margin (M5-04d): margins from the fixture's ``margins`` key.

Format (tests/fixtures/mt5/README.md, "Margins"): ``"margins": {"<symbol>": {"buy": "<margin
per 1.0 lot>", "sell": "..."}}``, decimals as strings in account currency. The result is
``per_lot * volume`` (exact Decimal); the price is accepted and ignored. Steps may replace
``margins`` like the other keys. All values here are SYNTHETIC.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source

D = Decimal
PW = SecretStr("investor")
LOGIN = 51234567
SERVER = "FundedNext-Server"
UNKNOWN_DIRECTION: Any = "hold"
ACCOUNT = {
    "login": LOGIN,
    "server": SERVER,
    "balance": "10000.00",
    "equity": "10000.00",
    "currency": "USD",
}


def data(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "format": 1,
        "account": ACCOUNT,
        "margins": {
            "EURUSD": {"buy": "1100.00", "sell": "1099.50"},
            "GER40.cash": {"buy": "3820.1"},
        },
    }
    return base | changes


def connected(src: FixtureMt5Source) -> FixtureMt5Source:
    src.connect("D:/MT5/x/terminal64.exe", LOGIN, PW, SERVER)
    return src


def test_margin_is_per_lot_times_volume_for_each_direction() -> None:
    src = connected(FixtureMt5Source(data()))

    assert src.calc_margin("buy", "EURUSD", D("0.50"), D("1.10000")) == D("550.00")
    assert src.calc_margin("sell", "EURUSD", D("2"), D("1.10000")) == D("2199.00")
    assert src.calc_margin("buy", "GER40.cash", D("0.10"), D("19000")) == D("382.01")


def test_price_is_accepted_and_ignored() -> None:
    src = connected(FixtureMt5Source(data()))

    assert src.calc_margin("buy", "EURUSD", D("1"), D("1.2")) == src.calc_margin(
        "buy", "EURUSD", D("1"), D("0.9")
    )


def test_calc_margin_is_recorded_in_calls() -> None:
    src = connected(FixtureMt5Source(data()))
    src.calc_margin("buy", "EURUSD", D("1"), D("1.1"))
    src.shutdown()

    assert src.calls == ["connect", "calc_margin", "shutdown"]


def test_calc_margin_requires_a_connection() -> None:
    src = FixtureMt5Source(data())

    with pytest.raises(Mt5Error, match="not connected"):
        src.calc_margin("buy", "EURUSD", D("1"), D("1.1"))


@pytest.mark.parametrize(
    ("direction", "symbol"),
    [
        ("buy", "XAUUSD"),  # symbol without margin data
        ("sell", "GER40.cash"),  # symbol without data for that direction
        ("buy", "eurusd"),  # exact name only
    ],
)
def test_missing_margin_data_is_mt5_error(direction: Any, symbol: str) -> None:
    src = connected(FixtureMt5Source(data()))

    with pytest.raises(Mt5Error, match="no margin data") as err:
        src.calc_margin(direction, symbol, D("1"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_fixture_without_margins_key_has_no_margin_data() -> None:
    src = connected(FixtureMt5Source({"account": ACCOUNT}))

    with pytest.raises(Mt5Error, match="no margin data"):
        src.calc_margin("buy", "EURUSD", D("1"), D("1.1"))


def test_unknown_direction_is_value_error() -> None:
    src = connected(FixtureMt5Source(data()))

    with pytest.raises(ValueError, match="direction"):
        src.calc_margin(UNKNOWN_DIRECTION, "EURUSD", D("1"), D("1.1"))


def test_scripted_and_programmatic_calc_margin_failures() -> None:
    scripted = connected(
        FixtureMt5Source(data(failures={"calc_margin": {"last_error": [-10005, "IPC timeout"]}}))
    )
    with pytest.raises(Mt5Error) as err:
        scripted.calc_margin("buy", "EURUSD", D("1"), D("1.1"))
    assert err.value.code is Mt5ErrorCode.TIMEOUT

    src = connected(FixtureMt5Source(data()))
    src.fail("calc_margin", Mt5Error(Mt5ErrorCode.TERMINAL_START_FAILED, "boom"))
    with pytest.raises(Mt5Error, match="boom"):
        src.calc_margin("buy", "EURUSD", D("1"), D("1.1"))
    src.fail("calc_margin", None)
    assert src.calc_margin("buy", "EURUSD", D("1"), D("1.1")) == D("1100.00")


def test_steps_replace_margins() -> None:
    src = FixtureMt5Source(data(steps=[{"margins": {"EURUSD": {"buy": "1200"}}}]))
    connected(src)
    assert src.calc_margin("buy", "EURUSD", D("1"), D("1.1")) == D("1100.00")

    src.advance()

    assert src.calc_margin("buy", "EURUSD", D("1"), D("1.1")) == D("1200")
    with pytest.raises(Mt5Error, match="no margin data"):
        src.calc_margin("sell", "EURUSD", D("1"), D("1.1"))


@pytest.mark.parametrize(
    "margins",
    [
        {"EURUSD": {"buy": "abc"}},  # not a decimal
        {"EURUSD": {"buy": "-1"}},  # negative
        {"EURUSD": {"buy": "NaN"}},  # non-finite
        {"EURUSD": {"hold": "1"}},  # unknown direction
        {"EURUSD": "1100"},  # not a direction mapping
    ],
)
def test_invalid_margins_content_is_rejected_on_load(margins: Any) -> None:
    with pytest.raises(ValueError, match="EURUSD"):  # the error names the symbol
        FixtureMt5Source(data(margins=margins))
