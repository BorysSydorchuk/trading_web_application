"""MT5 access must stay read-only: no trading calls anywhere in the repo's Python code."""

from __future__ import annotations

import os
import re
from pathlib import Path

import app.mt5.real as real
from app.mt5.real import ALLOWED_FUNCTIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
# Test code may name the forbidden calls (this file does); dependencies are not ours.
EXCLUDED_DIRS = {"tests", ".venv", ".claude", "node_modules", ".git"}

# Trading functions of the MetaTrader5 package (and its Buy/Sell/Close helpers).
# order_calc_margin (PRD 6.8, M5-04d) and order_calc_profit (M5-09 loss-value check) are
# allowed: they only calculate. order_send / order_check stay forbidden.
FORBIDDEN = re.compile(
    r"\border_send\b|\border_check\b|\b_RawOrder\b|\bTRADE_ACTION_\w*|"
    r"\b(?:mt5|MetaTrader5|_mt5\(\)|module)\s*\.\s*(?:Buy|Sell|Close)\b|"
    r"\.(?:Buy|Sell|Close)\s*\("
)


def _python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        files.extend(Path(dirpath) / name for name in filenames if name.endswith(".py"))
    return files


def _trading_calls(root: Path, files: list[Path]) -> list[str]:
    return [
        f"{path.relative_to(root)}:{n}: {line.strip()}"
        for path in files
        for n, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        )
        if FORBIDDEN.search(line)
    ]


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
    for sample in (
        "history_orders_get(ticket=1)",
        "opening_order(1)",
        "positions_get()",
        "mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, volume, price)",
        "source.calc_margin(direction, symbol, volume, price)",
        "mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, 'EURUSD', 1.0, 1.1, 1.2)",
        "source.calc_profit(direction, symbol, volume, price_open, price_close)",
    ):
        assert not FORBIDDEN.search(sample), sample


def test_no_trading_calls_in_repo() -> None:
    files = _python_files(REPO_ROOT)
    # Guard against a vacuous pass (e.g. wrong repo root or over-broad exclusions).
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    assert {"backend/app/mt5/real.py", "backend/app/main.py"} <= scanned
    hits = _trading_calls(REPO_ROOT, files)
    assert hits == [], "MT5 trading calls are forbidden (read-only app):\n" + "\n".join(hits)


def test_scan_flags_source_and_skips_excluded_dirs(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("mt5.order_send(request)\n", encoding="utf-8")
    for excluded in EXCLUDED_DIRS:
        (tmp_path / excluded).mkdir()
        (tmp_path / excluded / "x.py").write_text("mt5.order_send(request)\n", encoding="utf-8")

    hits = _trading_calls(tmp_path, _python_files(tmp_path))

    assert hits == [f"{Path('app', 'main.py')}:1: mt5.order_send(request)"]


def test_allow_list_is_read_only() -> None:
    # order_calc_margin joined the allow-list for the calculator (PRD 6.8, docs/api.md M5-04d).
    assert "order_calc_margin" in ALLOWED_FUNCTIONS
    # order_calc_profit joined it in M5-09 (docs/api.md): only calculates a hypothetical profit.
    assert "order_calc_profit" in ALLOWED_FUNCTIONS
    assert ALLOWED_FUNCTIONS.isdisjoint({"order_send", "order_check", "Buy", "Sell", "Close"})
    assert not any(name.startswith(("order_send", "order_check")) for name in ALLOWED_FUNCTIONS)


def test_allowed_constants_are_only_the_two_order_types() -> None:
    """Module attributes read besides functions: only what order_calc_margin needs."""
    assert frozenset({"ORDER_TYPE_BUY", "ORDER_TYPE_SELL"}) == real.ALLOWED_CONSTANTS
    assert real.ALLOWED_CONSTANTS.isdisjoint(ALLOWED_FUNCTIONS)


ORDER_CALC_MARGIN_CALL = re.compile(r"\border_calc_margin\s*\(")


def test_order_calc_margin_is_called_only_by_the_real_adapter() -> None:
    app_root = REPO_ROOT / "backend" / "app"
    callers = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in _python_files(app_root)
        if ORDER_CALC_MARGIN_CALL.search(path.read_text(encoding="utf-8", errors="replace"))
    )
    assert callers == ["backend/app/mt5/real.py"]


ORDER_CALC_PROFIT_CALL = re.compile(r"\border_calc_profit\s*\(")


def test_order_calc_profit_is_called_only_by_the_real_adapter() -> None:
    app_root = REPO_ROOT / "backend" / "app"
    callers = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in _python_files(app_root)
        if ORDER_CALC_PROFIT_CALL.search(path.read_text(encoding="utf-8", errors="replace"))
    )
    assert callers == ["backend/app/mt5/real.py"]
