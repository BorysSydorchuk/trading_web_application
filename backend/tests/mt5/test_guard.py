"""MT5 access must stay read-only: no trading calls anywhere in the repo's Python code."""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.mt5.real import ALLOWED_FUNCTIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
# Test code may name the forbidden calls (this file does); dependencies are not ours.
EXCLUDED_DIRS = {"tests", ".venv", ".claude", "node_modules", ".git"}

# Trading functions of the MetaTrader5 package (and its Buy/Sell/Close helpers).
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
    for sample in ("history_orders_get(ticket=1)", "opening_order(1)", "positions_get()"):
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
    assert ALLOWED_FUNCTIONS.isdisjoint(
        {"order_send", "order_check", "order_calc_margin", "order_calc_profit", "Buy", "Sell"}
    )
    assert "Close" not in ALLOWED_FUNCTIONS
