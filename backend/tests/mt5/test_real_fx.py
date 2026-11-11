"""RealMt5Source.quote / calc_profit (M5-09) against a fake ``MetaTrader5`` module.

``quote`` reads ``symbol_info_tick`` (bid, ask, time; selecting the symbol once when the first
read is empty, like ``server_tick_epoch``). ``calc_profit`` calls
``order_calc_profit(action, symbol, volume, price_open, price_close)`` with the module's
ORDER_TYPE_* constant; a negative result (a loss) is valid, None -> `Mt5Error` from last_error.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import app.mt5.real as real
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.real import ALLOWED_FUNCTIONS, RealMt5Source
from app.mt5.types import RawQuote
from tests.mt5.test_real import FakeMt5, connect

D = Decimal
FAKE_BUY = 10
FAKE_SELL = 11


class ProfitFakeMt5(FakeMt5):
    ORDER_TYPE_BUY = FAKE_BUY
    ORDER_TYPE_SELL = FAKE_SELL

    def __init__(self) -> None:
        super().__init__()
        self.profit_results: list[Any] = []
        self.profit_calls: list[tuple[Any, ...]] = []

    def order_calc_profit(
        self, action: int, symbol: str, volume: float, price_open: float, price_close: float
    ) -> Any:
        self.profit_calls.append((action, symbol, volume, price_open, price_close))
        result = self.profit_results.pop(0) if self.profit_results else None
        if isinstance(result, tuple):
            self.error = result
            return self._result(None)
        return self._result(result)


class Guarded:
    def __init__(self, inner: ProfitFakeMt5) -> None:
        self._inner = inner
        self.accessed: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        self.accessed.add(name)
        if name not in ALLOWED_FUNCTIONS | real.ALLOWED_CONSTANTS:
            raise AssertionError(f"RealMt5Source touched forbidden MT5 attribute {name!r}")
        return getattr(self._inner, name)


@pytest.fixture
def terminal(tmp_path: Path) -> Path:
    exe = tmp_path / "terminal64.exe"
    exe.write_bytes(b"")
    return exe


@pytest.fixture
def fake() -> ProfitFakeMt5:
    return ProfitFakeMt5()


def connected_source(fake: ProfitFakeMt5, terminal: Path) -> tuple[RealMt5Source, Guarded]:
    guarded = Guarded(fake)
    src = RealMt5Source(guarded, retry_delay_s=0)
    connect(src, terminal)
    return src, guarded


def tick(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**({"time": 1_793_779_200, "bid": 1.10905, "ask": 1.1091} | kw))


# --- quote --------------------------------------------------------------------------------------


def test_quote_returns_decimal_bid_ask_and_server_time(fake: ProfitFakeMt5, terminal: Path) -> None:
    fake.tick_results = [tick()]
    src, guarded = connected_source(fake, terminal)

    quote = src.quote("EURUSD")

    assert quote == RawQuote(bid=D("1.10905"), ask=D("1.1091"), time=1_793_779_200)
    assert guarded.accessed <= ALLOWED_FUNCTIONS | real.ALLOWED_CONSTANTS


def test_quote_selects_the_symbol_when_the_first_read_is_empty(
    fake: ProfitFakeMt5, terminal: Path
) -> None:
    fake.tick_results = [None, tick(bid=24099.5, ask=24100.5)]
    src, _ = connected_source(fake, terminal)

    quote = src.quote("GER30")

    assert quote is not None
    assert (quote.bid, quote.ask) == (D("24099.5"), D("24100.5"))
    assert fake.select_calls == ["GER30"]


def test_quote_without_any_tick_is_none(fake: ProfitFakeMt5, terminal: Path) -> None:
    src, _ = connected_source(fake, terminal)

    assert src.quote("NOPE") is None


@pytest.mark.parametrize("bad", [{"bid": 0.0}, {"ask": 0.0}, {"time": 0}])
def test_quote_with_an_unusable_tick_is_none(
    fake: ProfitFakeMt5, terminal: Path, bad: dict[str, Any]
) -> None:
    """A tick without a price or a time cannot give a rate: treated as no quote."""
    fake.tick_results = [tick(**bad)]
    src, _ = connected_source(fake, terminal)

    assert src.quote("EURUSD") is None


# --- calc_profit --------------------------------------------------------------------------------


@pytest.mark.parametrize(("direction", "action"), [("buy", FAKE_BUY), ("sell", FAKE_SELL)])
def test_calc_profit_passes_the_module_order_type_and_floats(
    fake: ProfitFakeMt5, terminal: Path, direction: Any, action: int
) -> None:
    fake.profit_results = [-2929.67]
    src, guarded = connected_source(fake, terminal)

    result = src.calc_profit(direction, "GER30", D("1"), D("26478.80"), D("26214.012"))

    assert result == D("-2929.67")
    assert isinstance(result, Decimal)
    assert fake.profit_calls == [(action, "GER30", 1.0, 26478.8, 26214.012)]
    assert "order_calc_profit" in guarded.accessed
    assert guarded.accessed <= ALLOWED_FUNCTIONS | real.ALLOWED_CONSTANTS


def test_calc_profit_zero_is_a_valid_result(fake: ProfitFakeMt5, terminal: Path) -> None:
    fake.profit_results = [0.0]
    src, _ = connected_source(fake, terminal)

    assert src.calc_profit("buy", "GER30", D("1"), D("1"), D("1")) == 0


def test_calc_profit_none_raises_mt5_error_from_last_error(
    fake: ProfitFakeMt5, terminal: Path
) -> None:
    fake.profit_results = [(-2, "Terminal: Invalid params")]
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_profit("buy", "NOPE", D("1"), D("1"), D("1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR
    assert err.value.mt5_code == -2
    assert "order_calc_profit" in err.value.message


def test_calc_profit_rejects_an_unknown_direction(fake: ProfitFakeMt5, terminal: Path) -> None:
    src, _ = connected_source(fake, terminal)

    with pytest.raises(ValueError, match=r".+"):
        src.calc_profit("hold", "GER30", D("1"), D("1"), D("1"))  # type: ignore[arg-type]
    assert fake.profit_calls == []


def test_calc_profit_needs_a_connection(fake: ProfitFakeMt5) -> None:
    src = RealMt5Source(Guarded(fake), retry_delay_s=0)

    with pytest.raises(Mt5Error):
        src.calc_profit("buy", "GER30", D("1"), D("1"), D("1"))
