"""MT5 access must stay read-only: no trading calls anywhere in the backend code."""

from __future__ import annotations

import re
from pathlib import Path

from app.mt5.real import ALLOWED_FUNCTIONS

BACKEND = Path(__file__).resolve().parents[2]
SCANNED = [BACKEND / "app", BACKEND.parent / "scripts"]

# Trading functions of the MetaTrader5 package (and its Buy/Sell/Close helpers).
FORBIDDEN = re.compile(
    r"\border_send\b|\border_check\b|\b_RawOrder\b|\bTRADE_ACTION_\w*|"
    r"\b(?:mt5|MetaTrader5|_mt5\(\)|module)\s*\.\s*(?:Buy|Sell|Close)\b|"
    r"\.(?:Buy|Sell|Close)\s*\("
)


def _python_files() -> list[Path]:
    return [p for root in SCANNED if root.is_dir() for p in root.rglob("*.py")]


def test_pattern_catches_trading_calls() -> None:
    for sample in (
        "mt5.order_send(request)",
        "x = mt5.order_check(r)",
        "mt5.Close('EURUSD')",
        "MetaTrader5.Buy('EURUSD', 0.1)",
        "self._mt5().Sell('X', 1)",
        '{"action": mt5.TRADE_ACTION_DEAL}',
    ):
        assert FORBIDDEN.search(sample), sample
    for sample in ("history_orders_get(ticket=1)", "opening_order(1)", "positions_get()"):
        assert not FORBIDDEN.search(sample), sample


def test_no_trading_calls_in_backend_code() -> None:
    files = _python_files()
    assert any(p.name == "real.py" for p in files)
    hits = [
        f"{path.relative_to(BACKEND.parent)}:{n}: {line.strip()}"
        for path in files
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if FORBIDDEN.search(line)
    ]
    assert hits == [], "MT5 trading calls are forbidden (read-only app):\n" + "\n".join(hits)


def test_allow_list_is_read_only() -> None:
    assert ALLOWED_FUNCTIONS.isdisjoint(
        {"order_send", "order_check", "order_calc_margin", "order_calc_profit", "Buy", "Sell"}
    )
    assert "Close" not in ALLOWED_FUNCTIONS
