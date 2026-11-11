"""Generate the hand-crafted MT5 fixtures in this folder (scenarios: see README.md).

    cd backend && uv run python -m tests.fixtures.mt5.build_fixtures

`tests/mt5/test_fixture_files.py` fails if the JSON files drift from this generator.
Times are written as server wall clock ("ny_close": UTC+3 until 2026-11-01, then UTC+2);
every deal also carries a ``_server_time`` comment for humans.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

LOGIN = 51234567
SERVER = "FundedNext-Server"

BUY, SELL, BALANCE = 0, 1, 2
IN, OUT = 0, 1
CLIENT, SL, TP = 0, 4, 5
FILLED = 4

SPECS: dict[str, dict[str, Any]] = {
    "EURUSD": {
        "name": "EURUSD",
        "digits": 5,
        "contract_size": "100000",
        "tick_size": "0.00001",
        "tick_value": "1",
        "volume_min": "0.01",
        "volume_step": "0.01",
        "volume_max": "50",
        "currency_profit": "USD",
        "currency_margin": "EUR",
    },
    "GBPUSD": {
        "name": "GBPUSD",
        "digits": 5,
        "contract_size": "100000",
        "tick_size": "0.00001",
        "tick_value": "1",
        "volume_min": "0.01",
        "volume_step": "0.01",
        "volume_max": "50",
        "currency_profit": "USD",
        "currency_margin": "GBP",
    },
    "XAUUSD": {
        "name": "XAUUSD",
        "digits": 2,
        "contract_size": "100",
        "tick_size": "0.01",
        "tick_value": "1",
        "volume_min": "0.01",
        "volume_step": "0.01",
        "volume_max": "20",
        "currency_profit": "USD",
        "currency_margin": "XAU",
    },
    # Index CFD quoted in EUR on a USD account: tick_value = 0.01 EUR in USD at EURUSD 1.16.
    "GER40": {
        "name": "GER40",
        "digits": 2,
        "contract_size": "1",
        "tick_size": "0.01",
        "tick_value": "0.0116",
        "volume_min": "0.1",
        "volume_step": "0.1",
        "volume_max": "100",
        "currency_profit": "EUR",
        "currency_margin": "EUR",
    },
}


def sv(wall: str) -> int:
    """Server wall clock 'YYYY-MM-DD HH:MM:SS' -> MT5 epoch (wall read as UTC)."""
    return int(datetime.fromisoformat(wall).replace(tzinfo=UTC).timestamp())


def deal(
    ticket: int,
    order: int,
    position: int,
    wall: str,
    typ: int,
    entry: int,
    volume: str,
    price: str,
    profit: str,
    symbol: str,
    *,
    commission: str = "0",
    swap: str = "0",
    reason: int = CLIENT,
    sl: str = "0",
    tp: str = "0",
) -> dict[str, Any]:
    t = sv(wall)
    return {
        "_server_time": wall,
        "ticket": ticket,
        "order": order,
        "position_id": position,
        "time": t,
        "time_msc": t * 1000,
        "type": typ,
        "entry": entry,
        "reason": reason,
        "magic": 0,
        "volume": volume,
        "price": price,
        "profit": profit,
        "commission": commission,
        "swap": swap,
        "fee": "0",
        "symbol": symbol,
        "sl": sl,
        "tp": tp,
    }


def balance_deal(ticket: int, wall: str, amount: str) -> dict[str, Any]:
    return deal(ticket, 0, 0, wall, BALANCE, IN, "0", "0", amount, "")


def order(
    ticket: int,
    position: int,
    wall: str,
    typ: int,
    volume: str,
    price: str,
    symbol: str,
    *,
    sl: str = "0",
    tp: str = "0",
) -> dict[str, Any]:
    t = sv(wall)
    return {
        "_server_time": wall,
        "ticket": ticket,
        "position_id": position,
        "time_setup": t,
        "time_setup_msc": t * 1000,
        "type": typ,
        "state": FILLED,
        "volume_initial": volume,
        "price_open": price,
        "sl": sl,
        "tp": tp,
        "symbol": symbol,
    }


def account(balance: str, equity: str, login: int = LOGIN) -> dict[str, Any]:
    return {
        "login": login,
        "server": SERVER,
        "balance": balance,
        "equity": equity,
        "currency": "USD",
    }


def ticks(wall: str, symbols: list[str]) -> dict[str, int]:
    return dict.fromkeys(symbols, sv(wall))


def _balance(deals: list[dict[str, Any]]) -> Decimal:
    return sum(
        (Decimal(d["profit"]) + Decimal(d["commission"]) + Decimal(d["swap"]) for d in deals),
        Decimal(0),
    )


ALL = ["EURUSD", "GBPUSD", "XAUUSD", "GER40"]


def basic_week() -> dict[str, Any]:
    eu, gu, xau, ger = "EURUSD", "GBPUSD", "XAUUSD", "GER40"
    deals = [
        balance_deal(1000001, "2026-10-16 12:00:00", "100000"),
        # T1 EURUSD buy 1.00, SL on the deal, 3 partial exits (Mon london)
        deal(
            1000101,
            2000101,
            2000101,
            "2026-10-19 10:30:00",
            BUY,
            IN,
            "1",
            "1.165",
            "0",
            eu,
            commission="-3",
            sl="1.162",
            tp="1.17",
        ),
        deal(
            1000102,
            2000102,
            2000101,
            "2026-10-19 11:15:00",
            SELL,
            OUT,
            "0.4",
            "1.167",
            "80",
            eu,
            commission="-1.2",
            sl="1.162",
            tp="1.17",
        ),
        deal(
            1000103,
            2000103,
            2000101,
            "2026-10-19 11:45:00",
            SELL,
            OUT,
            "0.3",
            "1.168",
            "90",
            eu,
            commission="-0.9",
            sl="1.162",
            tp="1.17",
        ),
        deal(
            1000104,
            2000104,
            2000101,
            "2026-10-19 12:30:00",
            SELL,
            OUT,
            "0.3",
            "1.169",
            "120",
            eu,
            commission="-0.9",
            sl="1.162",
            tp="1.17",
        ),
        # T2 GBPUSD sell, scale-in, SL only on the opening order, closed by TP (Mon ny)
        deal(
            1000201,
            2000201,
            2000201,
            "2026-10-19 15:05:00",
            SELL,
            IN,
            "0.5",
            "1.34",
            "0",
            gu,
            commission="-1.5",
        ),
        deal(
            1000202,
            2000202,
            2000201,
            "2026-10-19 15:20:00",
            SELL,
            IN,
            "0.5",
            "1.341",
            "0",
            gu,
            commission="-1.5",
        ),
        deal(
            1000203,
            2000203,
            2000201,
            "2026-10-19 16:10:00",
            BUY,
            OUT,
            "1",
            "1.337",
            "350",
            gu,
            commission="-3",
            reason=TP,
        ),
        # T3 XAUUSD buy stopped out (Tue london)
        deal(
            1000301,
            2000301,
            2000301,
            "2026-10-20 10:10:00",
            BUY,
            IN,
            "0.5",
            "4105.5",
            "0",
            xau,
            commission="-1.5",
            sl="4095.5",
            tp="4125.5",
        ),
        deal(
            1000302,
            2000302,
            2000301,
            "2026-10-20 10:40:00",
            SELL,
            OUT,
            "0.5",
            "4095.5",
            "-500",
            xau,
            commission="-1.5",
            reason=SL,
            sl="4095.5",
            tp="4125.5",
        ),
        # T4 XAUUSD re-entry buy, same session after the loss (Tue london)
        deal(
            1000401,
            2000401,
            2000401,
            "2026-10-20 11:05:00",
            BUY,
            IN,
            "0.5",
            "4093",
            "0",
            xau,
            commission="-1.5",
            sl="4086",
            tp="4110",
        ),
        deal(
            1000402,
            2000402,
            2000401,
            "2026-10-20 11:50:00",
            SELL,
            OUT,
            "0.5",
            "4103",
            "500",
            xau,
            commission="-1.5",
            sl="4086",
            tp="4110",
        ),
        # T5 GER40 sell in premarket, no SL anywhere (Wed)
        deal(1000501, 2000501, 2000501, "2026-10-21 12:30:00", SELL, IN, "2", "24150", "0", ger),
        deal(1000502, 2000502, 2000501, "2026-10-21 13:40:00", BUY, OUT, "2", "24110", "92.8", ger),
        # T6 GER40 buy, SL on the opening order only (Thu ny)
        deal(1000601, 2000601, 2000601, "2026-10-22 15:00:00", BUY, IN, "5", "24200", "0", ger),
        deal(1000602, 2000602, 2000601, "2026-10-22 16:20:00", SELL, OUT, "5", "24260", "348", ger),
        # T7 EURUSD sell, still open at step 0; SL only on the open position (Fri london)
        deal(
            1000701,
            2000701,
            2000701,
            "2026-10-23 10:45:00",
            SELL,
            IN,
            "0.8",
            "1.163",
            "0",
            eu,
            commission="-2.4",
        ),
    ]
    orders = [
        order(
            2000101, 2000101, "2026-10-19 10:30:00", BUY, "1", "1.165", eu, sl="1.162", tp="1.17"
        ),
        order(2000102, 2000101, "2026-10-19 11:15:00", SELL, "0.4", "1.167", eu),
        order(2000103, 2000101, "2026-10-19 11:45:00", SELL, "0.3", "1.168", eu),
        order(2000104, 2000101, "2026-10-19 12:30:00", SELL, "0.3", "1.169", eu),
        order(
            2000201, 2000201, "2026-10-19 15:05:00", SELL, "0.5", "1.34", gu, sl="1.344", tp="1.337"
        ),
        order(
            2000202,
            2000201,
            "2026-10-19 15:20:00",
            SELL,
            "0.5",
            "1.341",
            gu,
            sl="1.344",
            tp="1.337",
        ),
        order(2000203, 2000201, "2026-10-19 16:10:00", BUY, "1", "1.337", gu),
        order(
            2000301,
            2000301,
            "2026-10-20 10:10:00",
            BUY,
            "0.5",
            "4105.5",
            xau,
            sl="4095.5",
            tp="4125.5",
        ),
        order(2000302, 2000301, "2026-10-20 10:40:00", SELL, "0.5", "4095.5", xau),
        order(
            2000401, 2000401, "2026-10-20 11:05:00", BUY, "0.5", "4093", xau, sl="4086", tp="4110"
        ),
        order(2000402, 2000401, "2026-10-20 11:50:00", SELL, "0.5", "4103", xau),
        order(2000501, 2000501, "2026-10-21 12:30:00", SELL, "2", "24150", ger),
        order(2000502, 2000501, "2026-10-21 13:40:00", BUY, "2", "24110", ger),
        order(
            2000601, 2000601, "2026-10-22 15:00:00", BUY, "5", "24200", ger, sl="24170", tp="24290"
        ),
        order(2000602, 2000601, "2026-10-22 16:20:00", SELL, "5", "24260", ger),
        order(2000701, 2000701, "2026-10-23 10:45:00", SELL, "0.8", "1.163", eu),
    ]
    t7 = sv("2026-10-23 10:45:00")
    position = {
        "_server_time": "2026-10-23 10:45:00",
        "ticket": 2000701,
        "identifier": 2000701,
        "time": t7,
        "time_msc": t7 * 1000,
        "type": SELL,
        "volume": "0.8",
        "price_open": "1.163",
        "sl": "1.165",
        "tp": "1.159",
        "price_current": "1.1625",
        "profit": "40",
        "swap": "0",
        "symbol": eu,
    }
    close_deal = deal(
        1000702,
        2000702,
        2000701,
        "2026-10-23 16:30:00",
        BUY,
        OUT,
        "0.8",
        "1.16",
        "240",
        eu,
        commission="-2.4",
        sl="1.165",
        tp="1.159",
    )
    balance0 = _balance(deals)
    balance1 = balance0 + _balance([close_deal])
    assert balance0 == Decimal("101060.40"), balance0
    assert balance1 == Decimal("101298.00"), balance1
    return {
        "format": 1,
        "description": "FundedNext-like 100k USD account, week 2026-10-19..23 (see README.md)",
        "account": account("101060.40", "101100.40"),
        "ticks": ticks("2026-10-23 13:00:00", ALL),
        "symbols": [SPECS[s] for s in ALL],
        "deals": deals,
        "orders": orders,
        "positions": [position],
        "steps": [
            {
                "name": "T7 closed at 15:30 Brussels",
                "account": account("101298.00", "101298.00"),
                "ticks": ticks("2026-10-23 16:31:00", ALL),
                "add_deals": [close_deal],
                "add_orders": [
                    order(2000702, 2000701, "2026-10-23 16:30:00", BUY, "0.8", "1.16", eu)
                ],
                "positions": [],
            }
        ],
    }


def dst_switch() -> dict[str, Any]:
    eu = "EURUSD"
    login = 51234568
    deals = [
        balance_deal(3000001, "2026-10-22 12:00:00", "50000"),
        # D1 Fri 23 Oct: server UTC+3, Brussels UTC+2
        deal(
            3000101,
            4000101,
            4000101,
            "2026-10-23 10:30:00",
            BUY,
            IN,
            "0.5",
            "1.16",
            "0",
            eu,
            commission="-1.5",
            sl="1.158",
            tp="1.164",
        ),
        deal(
            3000102,
            4000102,
            4000101,
            "2026-10-23 11:30:00",
            SELL,
            OUT,
            "0.5",
            "1.161",
            "50",
            eu,
            commission="-1.5",
        ),
        # D2 Mon 26 Oct: EU on winter time, US still on DST -> server = Brussels + 2 h
        deal(
            3000201,
            4000201,
            4000201,
            "2026-10-26 14:30:00",
            SELL,
            IN,
            "0.5",
            "1.164",
            "0",
            eu,
            commission="-1.5",
            sl="1.165",
            tp="1.162",
        ),
        deal(
            3000202,
            4000202,
            4000201,
            "2026-10-26 15:00:00",
            BUY,
            OUT,
            "0.5",
            "1.1645",
            "-25",
            eu,
            commission="-1.5",
        ),
        # D3 Fri 30 Oct -> Mon 2 Nov, held across the US switch, swap on the exit deal
        deal(
            3000301,
            4000301,
            4000301,
            "2026-10-30 22:00:00",
            SELL,
            IN,
            "1",
            "1.165",
            "0",
            eu,
            commission="-3",
            sl="1.168",
            tp="1.161",
        ),
        # Sun 1 Nov: withdrawal inside the repeated server hour 08:00-09:00 (fold=0 -> UTC+3)
        balance_deal(3000002, "2026-11-01 08:30:00", "-1000"),
        deal(
            3000302,
            4000302,
            4000301,
            "2026-11-02 10:30:00",
            BUY,
            OUT,
            "1",
            "1.163",
            "200",
            eu,
            commission="-3",
            swap="-15.4",
        ),
        # D4 Mon 2 Nov: both on winter time, server UTC+2
        deal(
            3000401,
            4000401,
            4000401,
            "2026-11-02 10:45:00",
            BUY,
            IN,
            "0.5",
            "1.162",
            "0",
            eu,
            commission="-1.5",
            sl="1.16",
            tp="1.166",
        ),
        deal(
            3000402,
            4000402,
            4000401,
            "2026-11-02 11:15:00",
            SELL,
            OUT,
            "0.5",
            "1.163",
            "50",
            eu,
            commission="-1.5",
        ),
    ]
    orders = [
        order(
            4000101, 4000101, "2026-10-23 10:30:00", BUY, "0.5", "1.16", eu, sl="1.158", tp="1.164"
        ),
        order(
            4000201,
            4000201,
            "2026-10-26 14:30:00",
            SELL,
            "0.5",
            "1.164",
            eu,
            sl="1.165",
            tp="1.162",
        ),
        order(
            4000301, 4000301, "2026-10-30 22:00:00", SELL, "1", "1.165", eu, sl="1.168", tp="1.161"
        ),
        order(
            4000401, 4000401, "2026-11-02 10:45:00", BUY, "0.5", "1.162", eu, sl="1.16", tp="1.166"
        ),
    ]
    balance = _balance(deals)
    assert balance == Decimal("49244.60"), balance
    return {
        "format": 1,
        "description": "Deals across the EU (2026-10-25) and US (2026-11-01) DST switches",
        "account": account("49244.60", "49244.60", login),
        "ticks": ticks("2026-11-02 12:00:00", [eu]),
        "symbols": [SPECS[eu]],
        "deals": deals,
        "orders": orders,
        "positions": [],
    }


def _small_closed_trade() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eu = "EURUSD"
    deals = [
        balance_deal(5000001, "2026-10-26 09:00:00", "10000"),
        deal(
            5000101,
            6000101,
            6000101,
            "2026-10-27 11:00:00",
            BUY,
            IN,
            "0.1",
            "1.16",
            "0",
            eu,
            commission="-0.3",
            sl="1.159",
            tp="1.162",
        ),
        deal(
            5000102,
            6000102,
            6000101,
            "2026-10-27 12:00:00",
            SELL,
            OUT,
            "0.1",
            "1.162",
            "20",
            eu,
            commission="-0.3",
            reason=TP,
        ),
    ]
    orders = [
        order(
            6000101, 6000101, "2026-10-27 11:00:00", BUY, "0.1", "1.16", eu, sl="1.159", tp="1.162"
        ),
    ]
    return deals, orders


def _failure_fixture(description: str, failures: dict[str, Any]) -> dict[str, Any]:
    deals, orders = _small_closed_trade()
    return {
        "format": 1,
        "description": description,
        "account": account("10019.40", "10019.40", 51234569),
        "ticks": ticks("2026-10-27 13:00:00", ["EURUSD"]),
        "symbols": [SPECS["EURUSD"]],
        "deals": deals,
        "orders": orders,
        "positions": [],
        "failures": failures,
    }


def fail_login() -> dict[str, Any]:
    return _failure_fixture(
        "Wrong investor password: initialize fails with MT5 -6",
        {"connect": {"last_error": [-6, "Terminal: Authorization failed"]}},
    )


def fail_terminal_not_found() -> dict[str, Any]:
    return _failure_fixture(
        "Terminal missing at the configured path: initialize fails with MT5 -10003",
        {"connect": {"last_error": [-10003, "IPC initialize failed, MetaTrader 5 x64 not found"]}},
    )


def fail_timeout_mid_sync() -> dict[str, Any]:
    return _failure_fixture(
        "Connect OK, then history_deals_get times out (MT5 -10005)",
        {"deals": {"last_error": [-10005, "IPC timeout"]}},
    )


def fail_then_recover() -> dict[str, Any]:
    data = _failure_fixture(
        "Step 0: terminal does not start (MT5 -10004); step 1: next cycle succeeds",
        {"connect": {"last_error": [-10004, "IPC initialize failed, no IPC connection"]}},
    )
    data["steps"] = [{"name": "terminal started", "failures": {}}]
    return data


# --- M5-06 calculator QA (SYNTHETIC values, not FundedNext evidence) --------------------

QA_CALC_LOGIN = 51234570
QA_CALC_SERVER = "QA-Synthetic-Server"


def _calc_spec(name: str, digits: int, **values: str | None) -> dict[str, Any]:
    keys = (
        "contract_size",
        "tick_size",
        "tick_value",
        "volume_min",
        "volume_step",
        "volume_max",
        "currency_profit",
        "currency_margin",
        "point",
        "tick_value_loss",
    )
    return {"name": name, "digits": digits, **{k: values[k] for k in keys}}


QA_CALC_QUOTE_WALL = "2026-11-11 10:00:00"  # server wall clock of the fixture quotes


def calculator_qa() -> dict[str, Any]:
    """One synced USD account, 4 broker-style symbols + one legacy spec, margins for 3."""
    usd = {"currency_profit": "USD"}
    return {
        "format": 1,
        "description": (
            "SYNTHETIC M5 calculator QA fixture (scripts/qa_live_check_m5.py). Values look "
            "realistic but are NOT FundedNext specifications and NOT broker evidence."
        ),
        "account": {
            "login": QA_CALC_LOGIN,
            "server": QA_CALC_SERVER,
            "balance": "100000.00",
            "equity": "100000.00",
            "currency": "USD",
        },
        # No ticks: the offset check falls back to the configured broker_time rule.
        "ticks": {},
        "symbols": [
            _calc_spec(
                "EURUSD",
                5,
                contract_size="100000",
                tick_size="0.00001",
                tick_value="1",
                tick_value_loss="1",
                point="0.00001",
                volume_min="0.01",
                volume_step="0.01",
                volume_max="50",
                currency_margin="EUR",
                **usd,
            ),
            _calc_spec(
                "GBPUSD",
                5,
                contract_size="100000",
                tick_size="0.00001",
                tick_value="1",
                tick_value_loss="1",
                point="0.00001",
                volume_min="0.01",
                volume_step="0.01",
                volume_max="50",
                currency_margin="GBP",
                **usd,
            ),
            _calc_spec(
                "XAUUSD",
                2,
                contract_size="100",
                tick_size="0.01",
                tick_value="1",
                tick_value_loss="1",
                point="0.01",
                volume_min="0.01",
                volume_step="0.01",
                volume_max="50",
                currency_margin="XAU",
                **usd,
            ),
            # EUR index on a USD account: loss tick value differs slightly from profit.
            _calc_spec(
                "GER40.cash",
                2,
                contract_size="1",
                tick_size="0.01",
                tick_value="0.0116",
                tick_value_loss="0.01161",
                point="0.01",
                volume_min="0.1",
                volume_step="0.1",
                volume_max="100",
                currency_profit="EUR",
                currency_margin="EUR",
            ),
            # A spec synced before point/tick_value_loss were captured -> specs_incomplete.
            _calc_spec(
                "EURUSD.legacy",
                5,
                contract_size="100000",
                tick_size="0.00001",
                tick_value="1",
                tick_value_loss=None,
                point=None,
                volume_min="0.01",
                volume_step="0.01",
                volume_max="50",
                currency_margin="EUR",
                **usd,
            ),
        ],
        "deals": [],
        "orders": [],
        "positions": [],
        # Per 1.0 lot, account currency (USD). GER40.cash deliberately has none.
        "margins": {
            "EURUSD": {"buy": "1163.50", "sell": "1163.20"},
            "GBPUSD": {"buy": "1342.10", "sell": "1341.90"},
            "XAUUSD": {"buy": "4105.20", "sell": "4104.80"},
        },
        # M5-09: GER40.cash is EUR-profit on a USD account, so it sizes with the EURUSD rate:
        # ask 1.16100 -> 0.01 * 1 * 1.161 = 0.01161 per tick per lot (= its tick_value_loss,
        # so the M5-06 hand results stay valid). Fixed time: the rate is shown as stale.
        "quotes": {
            "EURUSD": {"bid": "1.16095", "ask": "1.16100", "time": sv(QA_CALC_QUOTE_WALL)},
            "GER40.cash": {"bid": "24149.50", "ask": "24150.00", "time": sv(QA_CALC_QUOTE_WALL)},
        },
        # order_calc_profit check per tick per lot; agrees with the rate value.
        "profit_per_tick": {"GER40.cash": "0.01161"},
    }


# --- M5-08 canonical symbols: FundedNext names the DAX GER30 (SYNTHETIC values) ----------

GER30_LOGIN = 51234571
GER30_NAMES = ["EURUSD", "GBPUSD", "XAUUSD", "GER30"]


def _ger30_specs() -> list[dict[str, Any]]:
    usd = {"currency_profit": "USD"}
    fx = {
        "contract_size": "100000",
        "tick_size": "0.00001",
        "tick_value": "1",
        "tick_value_loss": "1",
        "point": "0.00001",
        "volume_min": "0.01",
        "volume_step": "0.01",
        "volume_max": "50",
    }
    return [
        _calc_spec("EURUSD", 5, currency_margin="EUR", **fx, **usd),
        _calc_spec("GBPUSD", 5, currency_margin="GBP", **fx, **usd),
        _calc_spec(
            "XAUUSD",
            2,
            contract_size="100",
            tick_size="0.01",
            tick_value="1",
            tick_value_loss="1",
            point="0.01",
            volume_min="0.01",
            volume_step="0.01",
            volume_max="20",
            currency_margin="XAU",
            **usd,
        ),
        # The DAX under its old name; no GER40 symbol at this broker.
        _calc_spec(
            "GER30",
            2,
            contract_size="1",
            tick_size="0.01",
            tick_value="0.0116",
            tick_value_loss="0.01161",
            point="0.01",
            volume_min="0.1",
            volume_step="0.1",
            volume_max="100",
            currency_profit="EUR",
            currency_margin="EUR",
        ),
    ]


def funded_next_ger30() -> dict[str, Any]:
    """FundedNext-like account whose broker has GER30 (no GER40): the M5-07 owner finding."""
    ger = "GER30"
    deals = [
        balance_deal(7000001, "2026-11-02 09:00:00", "100000"),
        deal(
            7000101,
            8000101,
            8000101,
            "2026-11-03 10:30:00",
            BUY,
            IN,
            "1",
            "24000",
            "0",
            ger,
            sl="23970",
            tp="24060",
        ),
        deal(
            7000102, 8000102, 8000101, "2026-11-03 11:30:00", SELL, OUT, "1", "24030", "34.8", ger
        ),
        deal(7000201, 8000201, 8000201, "2026-11-03 15:00:00", SELL, IN, "2", "24100", "0", ger),
    ]
    orders = [
        order(
            8000101, 8000101, "2026-11-03 10:30:00", BUY, "1", "24000", ger, sl="23970", tp="24060"
        ),
        order(8000102, 8000101, "2026-11-03 11:30:00", SELL, "1", "24030", ger),
        order(8000201, 8000201, "2026-11-03 15:00:00", SELL, "2", "24100", ger),
    ]
    opened = sv("2026-11-03 15:00:00")
    position = {
        "_server_time": "2026-11-03 15:00:00",
        "ticket": 8000201,
        "identifier": 8000201,
        "time": opened,
        "time_msc": opened * 1000,
        "type": SELL,
        "volume": "2",
        "price_open": "24100",
        "sl": "24130",
        "tp": "24040",
        "price_current": "24090",
        "profit": "23.2",
        "swap": "0",
        "symbol": ger,
    }
    balance = _balance(deals)
    assert balance == Decimal("100034.80"), balance
    return {
        "format": 1,
        "description": (
            "SYNTHETIC FundedNext-like account with the DAX named GER30 (no GER40), "
            "M5-08 canonical symbols (see README.md). Not broker evidence."
        ),
        "account": account("100034.80", "100058.00", GER30_LOGIN),
        "ticks": ticks("2026-11-03 16:00:00", GER30_NAMES),
        "symbols": _ger30_specs(),
        "deals": deals,
        "orders": orders,
        "positions": [position],
        # Per 1.0 lot in USD; keyed by the broker name only.
        "margins": {"GER30": {"buy": "4800.00", "sell": "4799.50"}},
    }


FIXTURES = {
    "basic_week.json": basic_week,
    "dst_switch.json": dst_switch,
    "fail_login.json": fail_login,
    "fail_terminal_not_found.json": fail_terminal_not_found,
    "fail_timeout_mid_sync.json": fail_timeout_mid_sync,
    "fail_then_recover.json": fail_then_recover,
    "calculator_qa.json": calculator_qa,
    "funded_next_ger30.json": funded_next_ger30,
}


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main() -> None:
    for name, build in FIXTURES.items():
        (HERE / name).write_text(render(build()), encoding="utf-8", newline="\n")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
