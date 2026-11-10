"""Fixture files -> FixtureMt5Source -> adapter -> domain; expectations from README.md."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.domain.broker_time import BrokerTimeRule, choose_conversion, detect_offset
from app.domain.metrics import balance_at_open, planned_rr, r_multiple, risk_amount, risk_pct
from app.domain.sessions import Window, classify
from app.domain.trade_builder import (
    BuildResult,
    BuiltTrade,
    DealType,
    OrderStops,
    build_trades,
    next_status,
)
from app.models.enums import InitialSlSource, TradeStatus
from app.mt5.convert import digits_by_symbol, order_stops, position_snapshots, to_deals
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from app.mt5.source import connected
from tests.fixtures.mt5 import build_fixtures

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mt5"
NY = BrokerTimeRule.NY_CLOSE
PW = SecretStr("investor")
SERVER = "FundedNext-Server"
WINDOWS = [
    Window("london", time(8), time(11), True),
    Window("premarket", time(11), time(13), False),
    Window("ny", time(13), time(16), True),
]


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def source(name: str, step: int = 0) -> FixtureMt5Source:
    return FixtureMt5Source.from_file(FIXTURES / name, step=step)


class Synced:
    """What a sync cycle would compute from a fixture (mini version of the M1-08 service)."""

    def __init__(self, src: FixtureMt5Source, login: int, first_seen_sl: dict[int, Decimal]):
        with connected(src, "D:/MT5/x/terminal64.exe", login, PW, SERVER) as info:
            self.info = info
            tick = src.server_tick_epoch("EURUSD")
            assert tick is not None
            self.tick = tick
            specs = src.symbols_matching(["EURUSD", "GBPUSD", "XAUUSD", "GER40"])
            self.specs = {s.name: s for s in specs}
            digits = digits_by_symbol(specs)
            raw = src.deals(0, 2**31)
            positions = src.open_positions()
            pids = {d.position_id for d in raw if d.position_id} | {p.identifier for p in positions}
            for pid in pids:
                raw += src.deals_for_position(pid)
            self.deals = to_deals(raw, NY, digits)
            orders: dict[int, OrderStops] = {}
            for d in self.deals:
                if d.type in (DealType.BUY, DealType.SELL):
                    o = src.opening_order(d.order)
                    if o is not None:
                        orders[o.ticket] = order_stops(o, digits)
            self.positions = position_snapshots(positions, digits)
            seen = dict(first_seen_sl)
            for pid, snap in self.positions.items():
                if snap.sl:
                    seen.setdefault(pid, snap.sl)
            self.first_seen_sl = seen
            self.result: BuildResult = build_trades(self.deals, orders, self.positions, seen)
        self.trades = {t.position_id: t for t in self.result.trades}

    def risk(self, t: BuiltTrade) -> Decimal | None:
        spec = self.specs[t.symbol]
        return risk_amount(
            entry_price=t.entry_price,
            initial_sl=t.initial_sl,
            volume=t.volume,
            exit_price=t.exit_price,
            exit_volume=t.exit_volume,
            gross_pnl=t.gross_pnl,
            tick_size=spec.tick_size,
            tick_value=spec.tick_value,
        )

    def balance_open(self, t: BuiltTrade) -> Decimal | None:
        return balance_at_open(self.info.balance, t.open_time, self.deals)


# --- basic_week -------------------------------------------------------------------------

EXPECTED_WEEK: list[dict[str, Any]] = [
    # pid, open, close (UTC), session, entry, exit, gross, comm, net, sl, source, tp, risk, r
    {"pid": 2000101, "open": utc(2026, 10, 19, 7, 30), "close": utc(2026, 10, 19, 9, 30),
     "session": "london", "entry": "1.165", "exit": "1.1679", "gross": "290", "comm": "-6",
     "net": "284", "sl": "1.162", "src": InitialSlSource.DEAL, "tp": "1.17", "risk": "300.00",
     "r": "0.9467", "rr": "1.6667", "exits": 3, "status": TradeStatus.NEEDS_DESCRIPTION},
    {"pid": 2000201, "open": utc(2026, 10, 19, 12, 5), "close": utc(2026, 10, 19, 13, 10),
     "session": "ny", "entry": "1.3405", "exit": "1.337", "gross": "350", "comm": "-6",
     "net": "344", "sl": "1.344", "src": InitialSlSource.ORDER, "tp": "1.337", "risk": "350.00",
     "r": "0.9829", "rr": "1.0000", "exits": 1, "status": TradeStatus.NEEDS_DESCRIPTION},
    {"pid": 2000301, "open": utc(2026, 10, 20, 7, 10), "close": utc(2026, 10, 20, 7, 40),
     "session": "london", "entry": "4105.5", "exit": "4095.5", "gross": "-500", "comm": "-3",
     "net": "-503", "sl": "4095.5", "src": InitialSlSource.DEAL, "tp": "4125.5",
     "risk": "500.00", "r": "-1.0060", "rr": "2.0000", "exits": 1,
     "status": TradeStatus.NEEDS_DESCRIPTION},
    {"pid": 2000401, "open": utc(2026, 10, 20, 8, 5), "close": utc(2026, 10, 20, 8, 50),
     "session": "london", "entry": "4093", "exit": "4103", "gross": "500", "comm": "-3",
     "net": "497", "sl": "4086", "src": InitialSlSource.DEAL, "tp": "4110", "risk": "350.00",
     "r": "1.4200", "rr": "2.4286", "exits": 1, "status": TradeStatus.NEEDS_DESCRIPTION},
    {"pid": 2000501, "open": utc(2026, 10, 21, 9, 30), "close": utc(2026, 10, 21, 10, 40),
     "session": "premarket", "entry": "24150", "exit": "24110", "gross": "92.8", "comm": "0",
     "net": "92.8", "sl": None, "src": None, "tp": None, "risk": None, "r": None, "rr": None,
     "exits": 1, "status": TradeStatus.NEEDS_SL},
    {"pid": 2000601, "open": utc(2026, 10, 22, 12, 0), "close": utc(2026, 10, 22, 13, 20),
     "session": "ny", "entry": "24200", "exit": "24260", "gross": "348", "comm": "0",
     "net": "348", "sl": "24170", "src": InitialSlSource.ORDER, "tp": "24290",
     "risk": "174.00", "r": "2.0000", "rr": "3.0000", "exits": 1,
     "status": TradeStatus.NEEDS_DESCRIPTION},
    {"pid": 2000701, "open": utc(2026, 10, 23, 7, 45), "close": None, "session": "london",
     "entry": "1.163", "exit": None, "gross": "0", "comm": "-2.4", "net": "-2.4",
     "sl": "1.165", "src": InitialSlSource.POSITION, "tp": "1.159", "risk": "160.00",
     "r": None, "rr": "2.0000", "exits": 0, "status": TradeStatus.OPEN},
]  # fmt: skip


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


@pytest.mark.parametrize("exp", EXPECTED_WEEK, ids=lambda e: str(e["pid"]))
def test_basic_week_trades(exp: dict[str, Any]) -> None:
    sync = Synced(source("basic_week.json"), 51234567, {})
    t = sync.trades[exp["pid"]]
    assert t.open_time == exp["open"]
    assert t.close_time == exp["close"]
    assert classify(t.open_time, WINDOWS) == exp["session"]
    assert t.entry_price == Decimal(exp["entry"])
    assert t.exit_price == _dec(exp["exit"])
    assert t.gross_pnl == Decimal(exp["gross"])
    assert t.commission == Decimal(exp["comm"])
    assert t.net_pnl == Decimal(exp["net"])
    assert t.initial_sl == _dec(exp["sl"])
    assert t.initial_sl_source == exp["src"]
    assert t.tp == _dec(exp["tp"])
    assert len(t.exit_deals) == exp["exits"]
    risk = sync.risk(t)
    assert risk == _dec(exp["risk"])
    r = r_multiple(t.net_pnl, risk) if t.is_closed else None
    assert r == _dec(exp["r"])
    assert planned_rr(t.entry_price, t.initial_sl, t.tp) == _dec(exp["rr"])
    status = next_status(None, is_closed=t.is_closed, has_initial_sl=t.initial_sl is not None)
    assert status is exp["status"]


def test_basic_week_account_offset_and_balances() -> None:
    sync = Synced(source("basic_week.json"), 51234567, {})
    assert sync.result.skipped == []
    assert len(sync.trades) == 7
    assert sync.info.balance == Decimal("101060.40")
    assert sync.specs["GER40"].tick_value == Decimal("0.0116")
    now = utc(2026, 10, 23, 10, 0)
    offset = detect_offset(sync.tick, now)
    assert offset == 3
    choice = choose_conversion(offset, NY, now)
    assert choice.conversion is NY
    assert choice.verified
    assert not choice.mismatch
    t3, t6 = sync.trades[2000301], sync.trades[2000601]
    assert sync.balance_open(t3) == Decimal("100628.00")
    assert risk_pct(sync.risk(t3), sync.balance_open(t3)) == Decimal("0.4969")
    assert sync.balance_open(t6) == Decimal("100714.80")
    assert risk_pct(sync.risk(t6), sync.balance_open(t6)) == Decimal("0.1728")
    t1 = sync.trades[2000101]
    assert [e.volume for e in t1.exit_deals] == [Decimal("0.4"), Decimal("0.3"), Decimal("0.3")]
    assert t1.exit_deals[-1].time == utc(2026, 10, 19, 9, 30)
    t2 = sync.trades[2000201]
    assert t2.volume == Decimal("1")
    assert t2.exit_deals[0].reason == "tp"
    assert balance_deals_total(sync) == Decimal("100000")


def balance_deals_total(sync: Synced) -> Decimal:
    return sum((d.profit for d in sync.deals if d.type is DealType.BALANCE), Decimal(0))


def test_basic_week_step_1_closes_the_open_position() -> None:
    src = source("basic_week.json")
    first = Synced(src, 51234567, {})
    seen = {2000701: first.first_seen_sl[2000701]}
    src.advance()
    second = Synced(src, 51234567, seen)
    t7 = second.trades[2000701]
    assert second.positions == {}
    assert t7.close_time == utc(2026, 10, 23, 13, 30)
    assert t7.gross_pnl == Decimal("240")
    assert t7.net_pnl == Decimal("235.20")
    assert t7.initial_sl == Decimal("1.165")
    assert t7.initial_sl_source is InitialSlSource.POSITION
    risk = second.risk(t7)
    assert risk == Decimal("160.00")
    assert r_multiple(t7.net_pnl, risk) == Decimal("1.4700")
    assert second.info.balance == Decimal("101298.00")
    # Without the SL remembered from the open position the trade would need an SL.
    blind = Synced(source("basic_week.json", step=1), 51234567, {})
    assert blind.trades[2000701].initial_sl is None


# --- dst_switch ------------------------------------------------------------------------


def test_dst_switch_times() -> None:
    sync = Synced(source("dst_switch.json"), 51234568, {})
    d1, d2, d3, d4 = (sync.trades[p] for p in (4000101, 4000201, 4000301, 4000401))
    assert (d1.open_time, d1.close_time) == (utc(2026, 10, 23, 7, 30), utc(2026, 10, 23, 8, 30))
    assert classify(d1.open_time, WINDOWS) == "london"
    # Week after the EU switch: server is Brussels + 2 h, entry 14:30 server = 12:30 Brussels.
    assert d2.open_time == utc(2026, 10, 26, 11, 30)
    assert classify(d2.open_time, WINDOWS) == "premarket"
    # Held across the US switch: Fri UTC+3 -> Mon UTC+2.
    assert d3.open_time == utc(2026, 10, 30, 19, 0)
    assert d3.close_time == utc(2026, 11, 2, 8, 30)
    assert d3.duration_seconds == 221_400
    assert d3.swap == Decimal("-15.40")
    assert d3.net_pnl == Decimal("178.60")
    assert classify(d3.open_time, WINDOWS) == "outside"
    assert d4.open_time == utc(2026, 11, 2, 8, 45)
    assert classify(d4.open_time, WINDOWS) == "london"
    withdrawal = next(d for d in sync.deals if d.ticket == 3000002)
    assert withdrawal.time == utc(2026, 11, 1, 5, 30)  # ambiguous hour, fold=0 -> UTC+3
    assert detect_offset(sync.tick, utc(2026, 11, 2, 10, 0)) == 2
    assert sync.info.balance == Decimal("49244.60")
    assert sync.balance_open(d4) == Decimal("49197.60")


# --- failures ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("fail_login.json", Mt5ErrorCode.LOGIN_FAILED),
        ("fail_terminal_not_found.json", Mt5ErrorCode.TERMINAL_NOT_FOUND),
        ("fail_then_recover.json", Mt5ErrorCode.TERMINAL_START_FAILED),
    ],
)
def test_connect_failures(name: str, code: Mt5ErrorCode) -> None:
    src = source(name)
    with pytest.raises(Mt5Error) as err, connected(src, "x", 51234569, PW, SERVER):
        pass
    assert err.value.code is code
    assert src.calls[-1] == "shutdown"


def test_timeout_mid_sync() -> None:
    src = source("fail_timeout_mid_sync.json")
    with connected(src, "x", 51234569, PW, SERVER):
        assert src.server_tick_epoch("EURUSD") is not None
        with pytest.raises(Mt5Error) as err:
            src.deals(0, 2**31)
    assert err.value.code is Mt5ErrorCode.TIMEOUT


def test_fail_then_recover() -> None:
    src = source("fail_then_recover.json")
    with pytest.raises(Mt5Error):
        src.connect("x", 51234569, PW, SERVER)
    src.advance()
    sync = Synced(src, 51234569, {})
    [trade] = sync.result.trades
    assert trade.net_pnl == Decimal("19.40")
    assert trade.close_time == utc(2026, 10, 27, 9, 0)  # server 12:00, UTC+3


def test_password_missing_and_wrong_account() -> None:
    src = source("basic_week.json")
    with pytest.raises(Mt5Error) as err:
        src.connect("x", 51234567, None, SERVER)
    assert err.value.code is Mt5ErrorCode.PASSWORD_MISSING
    with pytest.raises(Mt5Error) as err:
        src.connect("x", 11111111, PW, SERVER)
    assert err.value.code is Mt5ErrorCode.LOGIN_FAILED


# --- fixture source behaviour ---------------------------------------------------------


def test_reads_need_connection_and_programmatic_failures() -> None:
    src = source("basic_week.json")
    with pytest.raises(Mt5Error, match="not connected"):
        src.open_positions()
    src.connect("x", 51234567, PW, SERVER)
    src.fail("open_positions", Mt5Error(Mt5ErrorCode.MT5_ERROR, "boom"))
    with pytest.raises(Mt5Error, match="boom"):
        src.open_positions()
    src.fail("open_positions", None)
    assert len(src.open_positions()) == 1
    with pytest.raises(ValueError, match="unknown method"):
        src.fail("order_whatever", None)


def test_deals_window_is_inclusive_and_sorted() -> None:
    src = source("basic_week.json")
    src.connect("x", 51234567, PW, SERVER)
    t = build_fixtures.sv("2026-10-19 10:30:00")
    assert [d.ticket for d in src.deals(t, t)] == [1000101]
    assert src.symbol_spec("GER40") is not None
    assert src.symbol_spec("US30") is None
    assert src.opening_order(1) is None


def test_steps_bounds() -> None:
    src = source("basic_week.json")
    assert src.step_count == 2
    src.advance()
    with pytest.raises(IndexError):
        src.advance()


def test_invalid_fixture_content() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        FixtureMt5Source({"acount": {}})
    with pytest.raises(ValueError, match="format"):
        FixtureMt5Source({"format": 2})
    with pytest.raises(ValueError, match="unknown methods"):
        FixtureMt5Source({"failures": {"order_send": {"code": "mt5_error"}}})
    with pytest.raises(ValueError, match="unknown keys"):
        FixtureMt5Source({"steps": [{"add_positions": []}]})


@pytest.mark.parametrize("name", sorted(build_fixtures.FIXTURES))
def test_fixture_files_match_generator(name: str) -> None:
    on_disk = (FIXTURES / name).read_text(encoding="utf-8")
    assert on_disk == build_fixtures.render(build_fixtures.FIXTURES[name]()), (
        f"{name} is stale: run `uv run python -m tests.fixtures.mt5.build_fixtures`"
    )
    assert json.loads(on_disk)["format"] == 1


# --- funded_next_ger30.json (M5-08) ---------------------------------------------------------


def test_funded_next_ger30_has_ger30_and_no_ger40() -> None:
    src = source("funded_next_ger30.json")
    with connected(src, "D:/MT5/x/terminal64.exe", 51234571, PW, SERVER) as info:
        assert (info.balance, info.equity) == (Decimal("100034.80"), Decimal("100058.00"))
        names = [s.name for s in src.symbols_matching(["EURUSD", "GBPUSD", "XAUUSD", "GER"])]
        assert names == ["EURUSD", "GBPUSD", "XAUUSD", "GER30"]
        assert src.symbol_spec("GER40") is None
        ger30 = src.symbol_spec("GER30")
        assert ger30 is not None
        assert (ger30.point, ger30.tick_value_loss) == (Decimal("0.01"), Decimal("0.01161"))
        assert {d.symbol for d in src.deals(0, 2**31) if d.position_id} == {"GER30"}
        assert [p.symbol for p in src.open_positions()] == ["GER30"]
        assert src.calc_margin("buy", "GER30", Decimal("0.5"), Decimal("24000")) == Decimal(
            "2400.000"
        )
        with pytest.raises(Mt5Error):
            src.calc_margin("buy", "GER40", Decimal("0.5"), Decimal("24000"))
