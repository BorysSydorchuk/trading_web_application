"""Generate ``digest_qa.json``: the SYNTHETIC M6 digest/dashboard QA data set (M6-08).

    cd backend && uv run python -m tests.fixtures.mt5.build_digest_qa

Used by ``scripts/qa_live_check_m6.py`` (docs/reports/M6-live-check.md, hand calculation in
"QA hand calculation"). Not a broker record: every value is made up so the digest numbers are
easy to check by hand.

The file is a wrapper (``format`` "digest_qa/1"), not one `FixtureMt5Source` file: the QA
needs three accounts and a fixture source serves one login. Each ``accounts[i].fixture`` is a
normal format-1 fixture (top level = step 0 = sync pass 1, ``steps[0]`` = pass 2). The
launcher's seed step (``tests.fixtures.mt5.digest_qa_seed``) runs the real
``app.services.sync.sync_account`` for each account at the two ``sync_passes`` instants, then
archives the accounts marked ``archive``; ``api_seed`` (bias notes, journal values) is posted
through the HTTP API afterwards.

Accounts (USD, FundedNext-like specs, commission 0): A size 10 000 (risk 90 = 0.45 lot x 20
pips), B size 20 000 (risk 180 = 0.90 lot x 20 pips), C size 10 000 (archived). Server time is
"ny_close" (New York + 7 h) without ticks, so the configured broker_time rule converts it.
History: 6 weeks Mon 2026-09-28 .. Fri 2026-11-06, 5 trades a week (A Mon/Wed/Fri, B Tue/Thu).
Test week Mon 2026-11-09: A 5 trades, B 4 closed + 1 open, C 1 (archived).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tests.fixtures.mt5.build_fixtures import (
    BALANCE,
    BUY,
    CLIENT,
    IN,
    OUT,
    SELL,
    SPECS,
    deal,
    order,
    render,
)

HERE = Path(__file__).resolve().parent
FILE_NAME = "digest_qa.json"
FORMAT = "digest_qa/1"
SERVER = "QA-Synthetic-Server"
BRUSSELS = ZoneInfo("Europe/Brussels")
NEW_YORK = ZoneInfo("America/New_York")
NY_CLOSE_SHIFT = timedelta(hours=7)  # FundedNext server = New York + 7 h
SL_DISTANCE = Decimal("0.0020")
TP_DISTANCE = Decimal("0.0050")  # planned RR 2.5 (>= min_planned_rr 1.5)
CONTRACT = Decimal(100000)  # EURUSD / GBPUSD
ENTRY = {"EURUSD": Decimal("1.16000"), "GBPUSD": Decimal("1.34000")}
# Two sync passes (UTC): the first sync reads initial_history_days (30) back, so the history
# needs a pass in October; the second one reads from the last success - overlap_days.
SYNC_PASSES = ("2026-10-17T12:00:00Z", "2026-11-15T23:00:00Z")
# The pinned API clock of the QA run (Fri 16:00 Brussels: weekly suggestion due).
QA_NOW = "2026-11-13T15:00:00Z"

ACCOUNTS: dict[str, dict[str, Any]] = {
    "A": {"login": 51234581, "size": "10000.00", "volume": "0.45", "archive": False},
    "B": {"login": 51234582, "size": "20000.00", "volume": "0.90", "archive": False},
    "C": {"login": 51234583, "size": "10000.00", "volume": "0.45", "archive": True},
}
DEPOSITS = {"A": "2026-09-25 12:00", "B": "2026-09-25 12:00", "C": "2026-11-02 08:00"}

# (account, symbol, direction, open Brussels, close Brussels, R) for the history weeks; the
# weekly pattern is A Mon 09:00, B Tue 14:00, A Wed 09:30, B Thu 09:00, A Fri 14:00.
_SLOTS: tuple[tuple[str, str, int, str, str], ...] = (
    ("A", "EURUSD", 0, "09:00", "10:00"),
    ("B", "GBPUSD", 1, "14:00", "15:00"),
    ("A", "EURUSD", 2, "09:30", "10:30"),
    ("B", "EURUSD", 3, "09:00", "10:00"),
    ("A", "GBPUSD", 4, "14:00", "15:00"),
)
HISTORY_R: tuple[tuple[str, ...], ...] = (
    ("2", "-1", "1", "-1", "-1"),  # Mon 2026-09-28
    ("1.5", "-1", "1", "0.5", "-1"),  # Mon 2026-10-05
    ("2", "-1", "-1", "1", "1"),  # Mon 2026-10-12
    ("-1", "1.5", "1", "-1", "0.5"),  # Mon 2026-10-19
    ("1", "1", "-1", "1", "-1"),  # Mon 2026-10-26
    ("1", "0.5", "1", "-1", "0.5"),  # Mon 2026-11-02
)
HISTORY_MONDAYS = (
    "2026-09-28",
    "2026-10-05",
    "2026-10-12",
    "2026-10-19",
    "2026-10-26",
    "2026-11-02",
)


def _test_week() -> list[dict[str, Any]]:
    """Trades of the test week (labels T1..T10 and C1 as in the hand calculation)."""
    rows: list[tuple[str, str, str, str, str, str | None, str | None, str | None]] = [
        # label, account, symbol, direction, open, close, R, net override (no SL)
        ("T1", "A", "EURUSD", "buy", "2026-11-09 09:00", "2026-11-09 10:00", "5", None),
        ("T2", "A", "GBPUSD", "sell", "2026-11-10 14:00", "2026-11-10 15:00", "-1", None),
        ("T3", "A", "EURUSD", "buy", "2026-11-11 09:30", "2026-11-11 10:30", "0.05", None),
        ("T4", "A", "EURUSD", "buy", "2026-11-13 13:30", "2026-11-13 14:00", "-3.5", None),
        ("T5", "A", "GBPUSD", "buy", "2026-11-13 14:30", "2026-11-13 15:00", "0.5", None),
        ("T6", "B", "GBPUSD", "buy", "2026-11-09 14:00", "2026-11-09 15:00", "-1", None),
        ("T7", "B", "EURUSD", "sell", "2026-11-10 09:00", "2026-11-10 10:00", None, "-54"),
        ("T8", "B", "EURUSD", "buy", "2026-11-12 09:00", "2026-11-12 10:00", "-1", None),
        ("T9", "B", "EURUSD", "buy", "2026-11-13 15:00", "2026-11-15 23:30", "4", None),
        ("T10", "B", "GBPUSD", "sell", "2026-11-12 14:00", None, None, None),
        ("C1", "C", "EURUSD", "buy", "2026-11-11 09:00", "2026-11-11 10:00", "2", None),
    ]
    return [
        {
            "label": label,
            "account": acc,
            "symbol": sym,
            "direction": direction,
            "open": opened,
            "close": closed,
            "r": r,
            "net": net,
        }
        for label, acc, sym, direction, opened, closed, r, net in rows
    ]


def _history() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for week, (monday, rs) in enumerate(zip(HISTORY_MONDAYS, HISTORY_R, strict=True), start=1):
        start = datetime.fromisoformat(monday)
        for slot, (acc, sym, offset, opened, closed) in enumerate(_SLOTS, start=1):
            day = (start + timedelta(days=offset)).date().isoformat()
            out.append(
                {
                    "label": f"H{week}.{slot}",
                    "account": acc,
                    "symbol": sym,
                    "direction": "buy",
                    "open": f"{day} {opened}",
                    "close": f"{day} {closed}",
                    "r": rs[slot - 1],
                    "net": None,
                }
            )
    return out


def trade_plan() -> list[dict[str, Any]]:
    """Every synthetic trade (history first, then the test week) in a readable form."""
    return [*_history(), *_test_week()]


def server_wall(brussels: str) -> str:
    """Brussels wall time 'YYYY-MM-DD HH:MM' -> server ('ny_close') wall 'YYYY-MM-DD HH:MM:SS'."""
    local = datetime.fromisoformat(brussels).replace(tzinfo=BRUSSELS)
    ny = local.astimezone(NEW_YORK).replace(tzinfo=None)
    return (ny + NY_CLOSE_SHIFT).strftime("%Y-%m-%d %H:%M:%S")


def utc_iso(brussels: str) -> str:
    local = datetime.fromisoformat(brussels).replace(tzinfo=BRUSSELS)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _price(value: Decimal) -> str:
    return f"{value:.5f}"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _trade_prices(t: dict[str, Any], volume: Decimal) -> dict[str, Decimal]:
    sign = Decimal(1) if t["direction"] == "buy" else Decimal(-1)
    entry = ENTRY[t["symbol"]]
    if t["net"] is not None:  # no SL: the exit gives the stated net P&L
        move = Decimal(t["net"]) / (CONTRACT * volume)
    else:
        move = Decimal(t["r"] or "0") * SL_DISTANCE
    return {
        "entry": entry,
        "exit": entry + sign * move,
        "profit": move * CONTRACT * volume,
        "sl": entry - sign * SL_DISTANCE,
        "tp": entry + sign * TP_DISTANCE,
    }


def _deals_for(
    t: dict[str, Any], pid: int, deal_ticket: int, volume: Decimal
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    """In/out deals, the opening order and (for an open trade) the position."""
    p = _trade_prices(t, volume)
    has_sl = t["net"] is None
    sl = _price(p["sl"]) if has_sl else "0"
    tp = _price(p["tp"]) if has_sl else "0"
    typ_in = BUY if t["direction"] == "buy" else SELL
    typ_out = SELL if typ_in == BUY else BUY
    vol = f"{volume}"
    opened = server_wall(t["open"])
    deals = [
        deal(deal_ticket, pid, pid, opened, typ_in, IN, vol, _price(p["entry"]), "0",
             t["symbol"], sl=sl, tp=tp),
    ]  # fmt: skip
    opening = order(pid, pid, opened, typ_in, vol, _price(p["entry"]), t["symbol"], sl=sl, tp=tp)
    if t["close"] is None:
        epoch = deals[0]["time"]
        position = {
            "_server_time": opened,
            "ticket": pid,
            "identifier": pid,
            "time": epoch,
            "time_msc": epoch * 1000,
            "type": typ_in,
            "volume": vol,
            "price_open": _price(p["entry"]),
            "sl": sl,
            "tp": tp,
            "price_current": "1.33900",
            "profit": "90.00",
            "swap": "0",
            "symbol": t["symbol"],
        }
        return deals, opening, position
    deals.append(
        deal(deal_ticket + 1, pid + 500, pid, server_wall(t["close"]), typ_out, OUT, vol,
             _price(p["exit"]), _money(p["profit"]), t["symbol"], reason=CLIENT)
    )  # fmt: skip
    return deals, opening, None


def position_id(key: str, index: int) -> int:
    """Position id (= opening order ticket) of the account's ``index``-th trade (1-based)."""
    return {"A": 7, "B": 8, "C": 9}[key] * 1_000_000 + 100_000 + index * 10


def _account_fixture(key: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    meta = ACCOUNTS[key]
    base = {"A": 7, "B": 8, "C": 9}[key] * 1_000_000
    volume = Decimal(meta["volume"])
    deposit_wall = server_wall(DEPOSITS[key])
    deals: list[dict[str, Any]] = [
        deal(base + 1, 0, 0, deposit_wall, BALANCE, IN, "0", "0", meta["size"], "")
    ]
    orders: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    pass1_end = datetime.fromisoformat(SYNC_PASSES[0])
    pass1_balance = Decimal(meta["size"]) if key != "C" else Decimal(0)
    for i, t in enumerate(trades, start=1):
        pid = position_id(key, i)
        own, opening, position = _deals_for(t, pid, base + 200_000 + i * 10, volume)
        deals.extend(own)
        orders.append(opening)
        if position is not None:
            positions.append(position)
        if t["close"] is not None and datetime.fromisoformat(utc_iso(t["close"])) < pass1_end:
            pass1_balance += Decimal(own[-1]["profit"])
    final = sum((Decimal(d["profit"]) for d in deals), Decimal(0))
    floating = sum((Decimal(p["profit"]) for p in positions), Decimal(0))

    def info(balance: Decimal, equity: Decimal) -> dict[str, Any]:
        return {
            "login": meta["login"],
            "server": SERVER,
            "balance": _money(balance),
            "equity": _money(equity),
            "currency": "USD",
        }

    return {
        "format": 1,
        "description": f"SYNTHETIC M6 digest QA account {key} (step 0 = sync pass 1).",
        "account": info(pass1_balance, pass1_balance),
        "ticks": {},
        "symbols": [SPECS["EURUSD"], SPECS["GBPUSD"], SPECS["XAUUSD"]],
        "deals": deals,
        "orders": orders,
        "positions": [],
        "steps": [
            {
                "name": "sync pass 2",
                "account": info(final, final + floating),
                "positions": positions,
            }
        ],
    }


def _api_seed() -> dict[str, Any]:
    """Bias notes (with results) and journal values, posted through the API after the sync."""
    return {
        "bias_notes": [
            {"kind": "monthly", "period_date": "2026-11-01",
             "entries": [{"symbol": "EURUSD", "direction": "bullish", "was_correct": True}]},
            {"kind": "weekly", "period_date": "2026-11-09",
             "entries": [{"symbol": "EURUSD", "direction": "bullish", "was_correct": True},
                         {"symbol": "GBPUSD", "direction": "bearish", "was_correct": False}]},
            {"kind": "pre_london", "period_date": "2026-11-09",
             "entries": [{"symbol": "EURUSD", "direction": "bullish", "was_correct": True}]},
            {"kind": "pre_london", "period_date": "2026-11-12",
             "entries": [{"symbol": "XAUUSD", "direction": "neutral", "was_correct": None}]},
            {"kind": "pre_ny", "period_date": "2026-11-13",
             "entries": [{"symbol": "EURUSD", "direction": "bearish", "was_correct": False}]},
        ],
        # Draft journals (complete false): only entry_model is filled.
        "journal": [
            {"label": "T1", "fields": {"entry_model": "ifvg_m5"}},
            {"label": "T4", "fields": {"entry_model": "ifvg_m5"}},
            {"label": "T8", "fields": {"entry_model": "qm_m5"}},
        ],
    }  # fmt: skip


def digest_qa() -> dict[str, Any]:
    plan = trade_plan()
    by_account = {key: [t for t in plan if t["account"] == key] for key in ACCOUNTS}
    fixtures = {key: _account_fixture(key, trades) for key, trades in by_account.items()}
    pids = {
        t["label"]: position_id(key, i)
        for key, trades in by_account.items()
        for i, t in enumerate(trades, start=1)
    }
    accounts = [
        {
            "key": key,
            "name": f"QA M6 {key}",
            "firm": "QA Synthetic",
            "program": "QA M6",
            "phase": "phase_1",
            "login": meta["login"],
            "server": SERVER,
            "size": meta["size"],
            "currency": "USD",
            "archive": meta["archive"],
            # Pass index of the first sync (C is created later, like a new account).
            "first_pass": 1 if key == "C" else 0,
            "fixture": fixtures[key],
        }
        for key, meta in ACCOUNTS.items()
    ]
    trades = [
        {
            "label": t["label"],
            "account": t["account"],
            "position_id": pids[t["label"]],
            "symbol": t["symbol"],
            "direction": t["direction"],
            "open_utc": utc_iso(t["open"]),
            "close_utc": None if t["close"] is None else utc_iso(t["close"]),
            "r": t["r"],
        }
        for t in plan
    ]
    return {
        "format": FORMAT,
        "description": (
            "SYNTHETIC M6 digest QA data (scripts/qa_live_check_m6.py, "
            "docs/reports/M6-live-check.md). Made-up values, not broker evidence."
        ),
        "sync_passes": list(SYNC_PASSES),
        "qa_now": QA_NOW,
        "accounts": accounts,
        "trades": trades,
        "api_seed": _api_seed(),
    }


def main() -> None:
    (HERE / FILE_NAME).write_text(render(digest_qa()), encoding="utf-8", newline="\n")
    print(f"wrote {FILE_NAME}")


if __name__ == "__main__":
    main()
