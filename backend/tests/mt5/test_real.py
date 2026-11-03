"""RealMt5Source against a fake ``MetaTrader5`` module object (no terminal involved)."""

from __future__ import annotations

import importlib
import logging
import threading
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.real import ALLOWED_FUNCTIONS, RealMt5Source
from app.mt5.source import resolve_terminal

PASSWORD = "S3cr3t-Inv!"  # noqa: S105 - fake test password
LOGIN = 51234567
SERVER = "FundedNext-Server"


class FakeMt5:
    """Mimics the MetaTrader5 module: functions return None and set last_error on failure.

    The last error is kept PER THREAD (like a thread-local errno): ``error`` is what the next
    failing call records, and ``last_error()`` only sees errors recorded in its own thread.
    """

    def __init__(self) -> None:
        self.error: tuple[int, str] = (1, "Success")
        self._local = threading.local()
        self.init_calls = 0
        self.init_result = True
        self.init_kwargs: dict[str, Any] = {}
        self.init_path: str | None = None
        self.account = SimpleNamespace(
            login=LOGIN, server=SERVER, balance=100512.3, equity=100498.1, currency="USD"
        )
        self.deal_results: list[Any] = []
        self.tick_results: list[Any] = []
        self.symbols: tuple[Any, ...] = ()
        self.orders: tuple[Any, ...] | None = ()
        self.positions: tuple[Any, ...] | None = ()
        self.shutdown_calls = 0
        self.select_calls: list[str] = []
        self.deals_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.hang: threading.Event | None = None

    def initialize(self, path: str, **kwargs: Any) -> bool:
        self.init_calls += 1
        self.init_path = path
        self.init_kwargs = kwargs
        return self._result(self.init_result if self.init_result else None) is not None

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def _result(self, value: Any) -> Any:
        """Record ``error`` in the calling thread when the call fails (returns None)."""
        self._local.error = self.error if value is None else (1, "Success")
        return value

    def last_error(self) -> tuple[int, str]:
        error: tuple[int, str] = getattr(self._local, "error", (1, "Success"))
        return error

    def account_info(self) -> Any:
        return self.account

    def symbol_info(self, symbol: str) -> Any:
        return self._result(next((s for s in self.symbols if s.name == symbol), None))

    def symbol_info_tick(self, symbol: str) -> Any:
        return self._result(self.tick_results.pop(0) if self.tick_results else None)

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        self.select_calls.append(symbol)
        return True

    def symbols_get(self, *args: Any, **kwargs: Any) -> Any:
        return self.symbols

    def history_deals_get(self, *args: Any, **kwargs: Any) -> Any:
        self.deals_calls.append((args, kwargs))
        if self.hang is not None:
            self.hang.wait(5)
        result = self.deal_results.pop(0) if self.deal_results else ()
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
            self.error = result
            return self._result(None)
        return self._result(result)

    def history_orders_get(self, *args: Any, **kwargs: Any) -> Any:
        return self._result(self.orders)

    def positions_get(self, *args: Any, **kwargs: Any) -> Any:
        return self._result(self.positions)


class GuardedModule:
    """Proxy that fails on any attribute outside the read-only allow-list."""

    def __init__(self, inner: FakeMt5) -> None:
        self._inner = inner
        self.accessed: set[str] = set()

    def __getattr__(self, name: str) -> Any:
        self.accessed.add(name)
        if name not in ALLOWED_FUNCTIONS:
            raise AssertionError(f"RealMt5Source touched forbidden MT5 attribute {name!r}")
        return getattr(self._inner, name)


@pytest.fixture
def terminal(tmp_path: Path) -> Path:
    exe = tmp_path / "terminal64.exe"
    exe.write_bytes(b"")
    return exe


@pytest.fixture
def fake() -> FakeMt5:
    return FakeMt5()


def make_source(fake: FakeMt5, **kwargs: Any) -> tuple[RealMt5Source, GuardedModule]:
    guarded = GuardedModule(fake)
    kwargs.setdefault("retry_delay_s", 0)
    return RealMt5Source(guarded, **kwargs), guarded


def connect(src: RealMt5Source, terminal: Path, password: str | None = PASSWORD) -> Any:
    secret = SecretStr(password) if password is not None else None
    return src.connect(str(terminal), LOGIN, secret, SERVER, timeout_s=30)


def deal_obj(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "ticket": 1,
        "order": 10,
        "time": 1_792_000_000,
        "time_msc": 1_792_000_000_123,
        "type": 0,
        "entry": 0,
        "magic": 0,
        "position_id": 10,
        "reason": 0,
        "volume": 0.1,
        "price": 1.0850000000000002,
        "commission": -0.3,
        "swap": 0.0,
        "profit": 0.0,
        "fee": 0.0,
        "symbol": "EURUSD",
        "comment": "",
        "external_id": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_connect_passes_portable_and_timeout_and_converts_account(
    fake: FakeMt5, terminal: Path
) -> None:
    src, guarded = make_source(fake)
    info = connect(src, terminal)
    assert fake.init_path == str(terminal)
    assert fake.init_kwargs == {
        "login": LOGIN,
        "password": PASSWORD,
        "server": SERVER,
        "timeout": 30_000,
        "portable": True,
    }
    assert info.balance == Decimal("100512.3")
    assert info.equity == Decimal("100498.1")
    assert (info.login, info.server, info.currency) == (LOGIN, SERVER, "USD")
    assert guarded.accessed <= ALLOWED_FUNCTIONS


def test_connect_accepts_terminal_folder(fake: FakeMt5, terminal: Path) -> None:
    src, _ = make_source(fake)
    src.connect(str(terminal.parent), LOGIN, SecretStr(PASSWORD), SERVER)
    assert fake.init_path == str(terminal)


@pytest.mark.parametrize("password", [None, "", "   "])
def test_password_missing(fake: FakeMt5, terminal: Path, password: str | None) -> None:
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        connect(src, terminal, password)
    assert err.value.code is Mt5ErrorCode.PASSWORD_MISSING
    assert f"MT5_PASSWORD_{LOGIN}" in err.value.message
    assert fake.init_path is None


def test_terminal_not_found(fake: FakeMt5, tmp_path: Path) -> None:
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        connect(src, tmp_path / "nope" / "terminal64.exe")
    assert err.value.code is Mt5ErrorCode.TERMINAL_NOT_FOUND
    assert fake.init_path is None


@pytest.mark.parametrize(
    ("last_error", "code"),
    [
        ((-6, "Terminal: Authorization failed"), Mt5ErrorCode.LOGIN_FAILED),
        ((-10003, "IPC initialize failed, MetaTrader 5 x64 not found"), "terminal_not_found"),
        ((-10004, "IPC initialize failed, no IPC connection"), "terminal_start_failed"),
        ((-10003, "IPC initialize failed"), "terminal_start_failed"),
        ((-10005, "IPC timeout"), Mt5ErrorCode.TIMEOUT),
        ((-2, "Invalid params"), Mt5ErrorCode.MT5_ERROR),
    ],
)
def test_initialize_failure_mapping(
    fake: FakeMt5, terminal: Path, last_error: tuple[int, str], code: str
) -> None:
    fake.init_result = False
    fake.error = last_error
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        connect(src, terminal)
    assert err.value.code == code
    assert err.value.mt5_code == last_error[0]
    assert fake.shutdown_calls == 1


def test_wrong_account_in_terminal_is_login_failed(fake: FakeMt5, terminal: Path) -> None:
    fake.account = SimpleNamespace(
        login=99999, server=SERVER, balance=1.0, equity=1.0, currency="USD"
    )
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        connect(src, terminal)
    assert err.value.code is Mt5ErrorCode.LOGIN_FAILED
    assert fake.shutdown_calls == 1


def test_password_is_masked_in_errors_and_logs(
    fake: FakeMt5, terminal: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake.init_result = False
    fake.error = (-6, f"Authorization failed for password {PASSWORD}")
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        connect(src, terminal)
    assert PASSWORD not in str(err.value)
    assert PASSWORD not in repr(err.value)
    assert "***" in err.value.message
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__
    assert PASSWORD not in caplog.text


def test_password_masked_when_module_raises(fake: FakeMt5, terminal: Path) -> None:
    def boom(path: str, **kwargs: Any) -> bool:
        raise RuntimeError(f"bad args {kwargs}")

    fake.initialize = boom  # type: ignore[method-assign]
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        connect(src, terminal)
    assert err.value.code is Mt5ErrorCode.MT5_ERROR
    assert PASSWORD not in str(err.value)
    assert err.value.__suppress_context__


def test_reads_require_connection(fake: FakeMt5) -> None:
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        src.deals(0, 1)
    assert err.value.code is Mt5ErrorCode.MT5_ERROR


def test_deals_raw_conversion_and_sorting(fake: FakeMt5, terminal: Path) -> None:
    fake.deal_results = [
        (
            deal_obj(ticket=2, time=1_792_000_100, profit=12.5),
            deal_obj(ticket=1, sl=1.08, tp=1.09),
        )
    ]
    src, _ = make_source(fake)
    connect(src, terminal)
    deals = src.deals(1_791_000_000, 1_793_000_000)
    assert fake.deals_calls[-1] == ((1_791_000_000, 1_793_000_000), {})
    assert [d.ticket for d in deals] == [1, 2]
    first = deals[0]
    assert first.time == 1_792_000_000  # raw server epoch, not converted
    assert first.time_msc == 1_792_000_000_123
    assert first.price == Decimal("1.0850000000000002")  # raw; adapter rounds to digits
    assert first.volume == Decimal("0.1")
    assert first.commission == Decimal("-0.3")
    assert (first.sl, first.tp) == (Decimal("1.08"), Decimal("1.09"))
    assert deals[1].sl is None  # terminal build without DEAL_SL
    assert deals[1].profit == Decimal("12.5")


def test_deals_for_position_uses_position_filter(fake: FakeMt5, terminal: Path) -> None:
    fake.deal_results = [(deal_obj(),)]
    src, _ = make_source(fake)
    connect(src, terminal)
    assert len(src.deals_for_position(10)) == 1
    assert fake.deals_calls[-1] == ((), {"position": 10})


def test_none_with_success_code_is_empty(fake: FakeMt5, terminal: Path) -> None:
    fake.deal_results = [(1, "Success")]
    src, _ = make_source(fake)
    connect(src, terminal)
    assert src.deals(0, 1) == []


def test_transient_ipc_error_is_retried_once(fake: FakeMt5, terminal: Path) -> None:
    fake.deal_results = [(-10001, "IPC send failed"), (deal_obj(),)]
    src, _ = make_source(fake)
    connect(src, terminal)
    assert len(src.deals(0, 1)) == 1
    assert len(fake.deals_calls) == 2


def test_persistent_ipc_error_raises(fake: FakeMt5, terminal: Path) -> None:
    fake.deal_results = [(-10002, "IPC recv failed"), (-10002, "IPC recv failed")]
    src, _ = make_source(fake)
    connect(src, terminal)
    with pytest.raises(Mt5Error) as err:
        src.deals(0, 1)
    assert err.value.code is Mt5ErrorCode.MT5_ERROR
    assert err.value.mt5_code == -10002


def test_read_failure_maps_timeout_code(fake: FakeMt5, terminal: Path) -> None:
    fake.deal_results = [(-10005, "IPC timeout")]
    src, _ = make_source(fake)
    connect(src, terminal)
    with pytest.raises(Mt5Error) as err:
        src.deals(0, 1)
    assert err.value.code is Mt5ErrorCode.TIMEOUT


def test_hanging_call_times_out_and_poisons_source(fake: FakeMt5, terminal: Path) -> None:
    src, _ = make_source(fake, call_timeout_s=0.05)
    connect(src, terminal)
    fake.hang = threading.Event()
    try:
        with pytest.raises(Mt5Error) as err:
            src.deals(0, 1)
        assert err.value.code is Mt5ErrorCode.TIMEOUT
        with pytest.raises(Mt5Error) as again:
            src.open_positions()
        assert again.value.code is Mt5ErrorCode.TIMEOUT
    finally:
        fake.hang.set()
    fake.hang = None
    _wait_idle(src)
    connect(src, terminal)  # a new connect clears the broken state once the thread ended
    assert src.open_positions() == []


def _wait_idle(src: RealMt5Source) -> None:
    thread = src._thread
    if thread is not None:
        thread.join(5)
        assert not thread.is_alive()


def test_no_module_access_while_timed_out_call_still_runs(fake: FakeMt5, terminal: Path) -> None:
    src, _ = make_source(fake, call_timeout_s=0.05)
    connect(src, terminal)
    assert fake.init_calls == 1
    shutdowns = fake.shutdown_calls
    fake.hang = threading.Event()
    try:
        with pytest.raises(Mt5Error):
            src.deals(0, 1)
        # Hang NOT released: reconnect must refuse without entering the module.
        with pytest.raises(Mt5Error) as err:
            connect(src, terminal)
        assert err.value.code is Mt5ErrorCode.TIMEOUT
        assert "still running" in err.value.message
        assert fake.init_calls == 1
        src.shutdown()  # never raises, and skips the module too
        assert fake.shutdown_calls == shutdowns
        with pytest.raises(Mt5Error, match="still running"):
            connect(src, terminal)
    finally:
        fake.hang.set()
    fake.hang = None
    _wait_idle(src)
    connect(src, terminal)
    assert fake.init_calls == 2


def test_last_error_is_read_in_the_failing_thread(fake: FakeMt5, terminal: Path) -> None:
    """With a per-thread last error, a failed read must not look like "no deals"."""
    src, _ = make_source(fake)
    connect(src, terminal)
    fake.deal_results = [(-2, "Terminal: Invalid params")]
    with pytest.raises(Mt5Error) as err:
        src.deals(0, 1)
    assert err.value.mt5_code == -2
    # Main thread never saw that error: reading it here would have returned "Success".
    assert fake.last_error() == (1, "Success")


def test_tick_selects_symbol_when_missing(fake: FakeMt5, terminal: Path) -> None:
    fake.tick_results = [None, SimpleNamespace(time=1_792_003_600, bid=1.1, ask=1.1)]
    src, _ = make_source(fake)
    connect(src, terminal)
    assert src.server_tick_epoch("GER40") == 1_792_003_600
    assert fake.select_calls == ["GER40"]


def test_tick_unavailable_returns_none(fake: FakeMt5, terminal: Path) -> None:
    src, _ = make_source(fake)
    connect(src, terminal)
    assert src.server_tick_epoch("NOPE") is None


def spec_obj(name: str, **kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "name": name,
        "digits": 2,
        "trade_contract_size": 1.0,
        "trade_tick_size": 0.01,
        "trade_tick_value": 0.0116,
        "volume_min": 0.1,
        "volume_step": 0.1,
        "volume_max": 100.0,
        "currency_profit": "EUR",
        "currency_margin": "EUR",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_symbol_specs(fake: FakeMt5, terminal: Path) -> None:
    fake.symbols = (spec_obj("GER40.cash"), spec_obj("EURUSD", digits=5), spec_obj("US30"))
    src, _ = make_source(fake)
    connect(src, terminal)
    matched = src.symbols_matching(["GER40", "eurusd"])
    assert [s.name for s in matched] == ["GER40.cash", "EURUSD"]
    ger = matched[0]
    assert ger.tick_value == Decimal("0.0116")
    assert ger.contract_size == Decimal("1.0")
    assert src.symbol_spec("US30") is not None
    assert src.symbol_spec("XAUUSD") is None


def test_orders_and_positions(fake: FakeMt5, terminal: Path) -> None:
    fake.orders = (
        SimpleNamespace(
            ticket=10,
            position_id=10,
            time_setup=1,
            time_setup_msc=1000,
            type=0,
            state=4,
            volume_initial=0.1,
            price_open=1.085,
            sl=1.08,
            tp=0.0,
            symbol="EURUSD",
        ),
    )
    fake.positions = (
        SimpleNamespace(
            ticket=11,
            identifier=10,
            time=1,
            time_msc=1000,
            type=1,
            volume=0.1,
            price_open=1.085,
            sl=1.09,
            tp=1.07,
            price_current=1.084,
            profit=10.0,
            swap=-0.5,
            symbol="EURUSD",
        ),
    )
    src, _ = make_source(fake)
    connect(src, terminal)
    order = src.opening_order(10)
    assert order is not None
    assert (order.sl, order.tp) == (Decimal("1.08"), Decimal("0.0"))
    [pos] = src.open_positions()
    assert (pos.identifier, pos.sl, pos.swap) == (10, Decimal("1.09"), Decimal("-0.5"))
    fake.orders = None
    fake.error = (1, "Success")
    assert src.opening_order(10) is None


def test_shutdown_never_raises(fake: FakeMt5, terminal: Path) -> None:
    def boom() -> None:
        raise RuntimeError("x")

    fake.shutdown = boom  # type: ignore[method-assign]
    src, _ = make_source(fake)
    src.shutdown()


def test_missing_package_is_typed_error(monkeypatch: pytest.MonkeyPatch, terminal: Path) -> None:
    def no_module(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", no_module)
    src = RealMt5Source()
    with pytest.raises(Mt5Error) as err:
        connect(src, terminal)
    assert err.value.code is Mt5ErrorCode.MT5_ERROR
    assert "MetaTrader5" in err.value.message


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Program Files\\FundedNext MT5 Terminal\\terminal64.exe",
        "C:/PROGRAM FILES (X86)/MT5",
        '"%ProgramFiles%\\MT5\\terminal64.exe"',
    ],
)
def test_terminal_in_program_files_refused(
    fake: FakeMt5, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Defence in depth for accounts saved before the API check existed."""
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    src, _ = make_source(fake)
    with pytest.raises(Mt5Error) as err:
        src.connect(path, LOGIN, SecretStr(PASSWORD), SERVER, timeout_s=30)
    assert err.value.code is Mt5ErrorCode.TERMINAL_IN_PROGRAM_FILES
    assert "docs/MT5_SETUP.md step 1" in err.value.message
    assert fake.init_path is None


def test_resolve_terminal_guard_uses_env_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "MT5" / "terminal64.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert resolve_terminal(str(exe)) == exe
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    with pytest.raises(Mt5Error) as err:
        resolve_terminal(str(exe))
    assert err.value.code is Mt5ErrorCode.TERMINAL_IN_PROGRAM_FILES
