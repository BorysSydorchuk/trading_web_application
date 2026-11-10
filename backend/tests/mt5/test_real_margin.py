"""RealMt5Source.calc_margin (M5-04d) against a fake ``MetaTrader5`` module (no terminal).

``order_calc_margin(action, symbol, volume, price)`` only calculates: it never places or
checks an order. The fake uses non-standard ORDER_TYPE_* values so the tests prove the
source reads the constants from the module instead of hardcoding 0/1.
"""

from __future__ import annotations

import math
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import app.mt5.real as real
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.real import ALLOWED_FUNCTIONS, RealMt5Source
from tests.mt5.test_real import FakeMt5, connect

D = Decimal
FAKE_BUY = 10
FAKE_SELL = 11
UNKNOWN_DIRECTION: Any = "hold"


class MarginFakeMt5(FakeMt5):
    ORDER_TYPE_BUY = FAKE_BUY
    ORDER_TYPE_SELL = FAKE_SELL

    def __init__(self) -> None:
        super().__init__()
        # Each entry: a float result, None, or an (code, message) error tuple.
        self.margin_results: list[Any] = []
        self.margin_calls: list[tuple[Any, ...]] = []
        self.margin_hang: threading.Event | None = None

    def order_calc_margin(self, action: int, symbol: str, volume: float, price: float) -> Any:
        self.margin_calls.append((action, symbol, volume, price))
        if self.margin_hang is not None:
            self.margin_hang.wait(5)
        result = self.margin_results.pop(0) if self.margin_results else None
        if isinstance(result, tuple):
            self.error = result
            return self._result(None)
        return self._result(result)


class GuardedMarginModule:
    """Fails on any attribute outside the read-only allow-list (functions + constants)."""

    def __init__(self, inner: MarginFakeMt5) -> None:
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
def fake() -> MarginFakeMt5:
    return MarginFakeMt5()


def make_source(fake: MarginFakeMt5, **kwargs: Any) -> tuple[RealMt5Source, GuardedMarginModule]:
    guarded = GuardedMarginModule(fake)
    kwargs.setdefault("retry_delay_s", 0)
    return RealMt5Source(guarded, **kwargs), guarded


def connected_source(
    fake: MarginFakeMt5, terminal: Path, **kwargs: Any
) -> tuple[RealMt5Source, GuardedMarginModule]:
    src, guarded = make_source(fake, **kwargs)
    connect(src, terminal)
    return src, guarded


@pytest.mark.parametrize(("direction", "action"), [("buy", FAKE_BUY), ("sell", FAKE_SELL)])
def test_calc_margin_calls_order_calc_margin_with_the_module_order_type(
    fake: MarginFakeMt5, terminal: Path, direction: Any, action: int
) -> None:
    fake.margin_results = [1085.5]
    src, guarded = connected_source(fake, terminal)

    margin = src.calc_margin(direction, "EURUSD", D("0.50"), D("1.10000"))

    assert margin == D("1085.5")
    assert isinstance(margin, Decimal)
    assert fake.margin_calls == [(action, "EURUSD", 0.5, 1.1)]
    _, symbol, volume, price = fake.margin_calls[0]
    assert (type(symbol), type(volume), type(price)) == (str, float, float)
    assert "order_calc_margin" in guarded.accessed
    assert guarded.accessed <= ALLOWED_FUNCTIONS | real.ALLOWED_CONSTANTS


def test_calc_margin_converts_the_float_via_str(fake: MarginFakeMt5, terminal: Path) -> None:
    fake.margin_results = [0.1 + 0.2]  # 0.30000000000000004 as a double
    src, _ = connected_source(fake, terminal)

    assert src.calc_margin("buy", "EURUSD", D("0.01"), D("1.1")) == D("0.30000000000000004")


def test_zero_margin_is_a_valid_result(fake: MarginFakeMt5, terminal: Path) -> None:
    fake.margin_results = [0.0]
    src, _ = connected_source(fake, terminal)

    assert src.calc_margin("sell", "EURUSD", D("0.01"), D("1.1")) == 0


def test_none_result_raises_mt5_error_from_last_error(fake: MarginFakeMt5, terminal: Path) -> None:
    fake.margin_results = [(-2, "Terminal: Invalid params")]
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "NOPE", D("0.50"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR
    assert err.value.mt5_code == -2
    assert "order_calc_margin" in err.value.message


def test_none_with_success_code_is_still_an_error(fake: MarginFakeMt5, terminal: Path) -> None:
    """A margin is never optional: None never turns into "no margin" or zero."""
    fake.margin_results = [None]
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_timeout_code_maps_to_timeout(fake: MarginFakeMt5, terminal: Path) -> None:
    fake.margin_results = [(-10005, "IPC timeout")]
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.TIMEOUT


def test_transient_ipc_error_is_retried_once(fake: MarginFakeMt5, terminal: Path) -> None:
    fake.margin_results = [(-10001, "IPC send failed"), 550.0]
    src, _ = connected_source(fake, terminal)

    assert src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1")) == D("550.0")
    assert len(fake.margin_calls) == 2


def test_persistent_ipc_error_raises_after_one_retry(fake: MarginFakeMt5, terminal: Path) -> None:
    fake.margin_results = [(-10002, "IPC recv failed")] * 3
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))

    assert err.value.mt5_code == -10002
    assert len(fake.margin_calls) == 2


@pytest.mark.parametrize("bad", [-0.01, -1000.0, math.nan, math.inf, -math.inf])
def test_negative_or_non_finite_margin_is_mt5_error(
    fake: MarginFakeMt5, terminal: Path, bad: float
) -> None:
    fake.margin_results = [bad]
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_module_raising_is_mt5_error(fake: MarginFakeMt5, terminal: Path) -> None:
    def boom(*args: Any) -> Any:
        raise RuntimeError("bad args")

    fake.order_calc_margin = boom  # type: ignore[method-assign,assignment]
    src, _ = connected_source(fake, terminal)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_calc_margin_requires_a_connection(fake: MarginFakeMt5) -> None:
    src, _ = make_source(fake)

    with pytest.raises(Mt5Error) as err:
        src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))

    assert err.value.code is Mt5ErrorCode.MT5_ERROR
    assert fake.margin_calls == []


def test_unknown_direction_is_rejected_before_any_mt5_call(
    fake: MarginFakeMt5, terminal: Path
) -> None:
    src, _ = connected_source(fake, terminal)

    with pytest.raises(ValueError, match="direction"):
        src.calc_margin(UNKNOWN_DIRECTION, "EURUSD", D("0.50"), D("1.1"))

    assert fake.margin_calls == []


def test_hanging_calc_margin_times_out_and_poisons_source(
    fake: MarginFakeMt5, terminal: Path
) -> None:
    src, _ = connected_source(fake, terminal, call_timeout_s=0.05)
    fake.margin_hang = threading.Event()
    try:
        with pytest.raises(Mt5Error) as err:
            src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))
        assert err.value.code is Mt5ErrorCode.TIMEOUT
        with pytest.raises(Mt5Error) as again:
            src.calc_margin("buy", "EURUSD", D("0.50"), D("1.1"))
        assert again.value.code is Mt5ErrorCode.TIMEOUT
    finally:
        fake.margin_hang.set()
    thread = src._thread
    if thread is not None:
        thread.join(5)
