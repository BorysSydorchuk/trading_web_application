"""A fixed symbols.yaml for tests, independent of edits to the real config/symbols.yaml.

`use_test_config` copies the real config dir (rules, bias, ...) to a temp dir, writes
`TEST_SYMBOLS_YAML` as its symbols.yaml and points CONFIG_DIR at it. The real file is checked
against the contract once, in tests/test_symbols_config.py::test_real_file_matches_contract.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.config_files.symbols import SymbolsConfig

TEST_SYMBOLS_YAML = """\
symbols:
  - { name: EURUSD }
  - { name: GBPUSD }
  - { name: XAUUSD }
  - { name: GER40, broker_names: [GER30, GER40.cash, DE40] }
firms:
  FundedNext: { GER40: [GER30] }
"""
TEST_SYMBOLS = SymbolsConfig.model_validate(
    {
        "symbols": [
            {"name": "EURUSD"},
            {"name": "GBPUSD"},
            {"name": "XAUUSD"},
            {"name": "GER40", "broker_names": ["GER30", "GER40.cash", "DE40"]},
        ],
        "firms": {"FundedNext": {"GER40": ["GER30"]}},
    }
)
TEST_NAMES = ["EURUSD", "GBPUSD", "XAUUSD", "GER40"]


def use_test_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Activate a copy of config/ with the fixed test symbols.yaml; returns the dir.
    The caller's fixture must call `reload_config()` again on teardown."""
    target = tmp_path / "test-config"
    shutil.copytree(REPO_ROOT / "config", target)
    (target / "symbols.yaml").write_text(TEST_SYMBOLS_YAML, encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(target))
    reload_config()
    return target
