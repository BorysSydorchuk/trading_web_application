"""Trading safety guard: the app must never place orders through MT5.

Scans every .py file in the repo (outside tests, virtualenvs, .claude and
node_modules) and fails if `order_send` appears anywhere.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = "order_send"
EXCLUDED_DIRS = {"tests", ".venv", ".claude", "node_modules", ".git"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        files.extend(Path(dirpath) / name for name in filenames if name.endswith(".py"))
    return files


def test_no_order_send_in_source() -> None:
    files = _python_files()
    # Guard against a vacuous pass (e.g. wrong repo root).
    assert any(f.parts[-2:] == ("app", "main.py") for f in files), "app/main.py not scanned"

    offenders = [
        str(f.relative_to(REPO_ROOT))
        for f in files
        if FORBIDDEN in f.read_text(encoding="utf-8", errors="replace")
    ]
    assert offenders == [], f"'{FORBIDDEN}' found in: {offenders}"
