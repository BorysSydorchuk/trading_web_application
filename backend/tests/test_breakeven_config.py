"""``breakeven_r_threshold`` in config/rules.yaml (Borys/PM 2026-11-14, option A).

Top-level key, Decimal >= 0, default 0.1 when absent; 0 switches back to the P&L-sign rule.
The real rules.yaml sets 0.1 explicitly.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import REPO_ROOT
from app.config_files.loader import ConfigError, read_yaml
from app.config_files.rules import load_rules


def rules_file(tmp_path: Path, value: Any = "absent") -> Path:
    data = read_yaml(REPO_ROOT / "config" / "rules.yaml")
    data.pop("breakeven_r_threshold", None)
    if value != "absent":
        data["breakeven_r_threshold"] = value
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_default_is_point_one_when_absent(tmp_path: Path) -> None:
    assert load_rules(rules_file(tmp_path)).breakeven_r_threshold == Decimal("0.1")


def test_real_rules_file_sets_point_one() -> None:
    data = read_yaml(REPO_ROOT / "config" / "rules.yaml")

    assert data["breakeven_r_threshold"] == 0.1
    assert load_rules(REPO_ROOT / "config" / "rules.yaml").breakeven_r_threshold == Decimal("0.1")


@pytest.mark.parametrize("value", [0, 0.25, 1])
def test_custom_value_is_a_decimal(tmp_path: Path, value: float) -> None:
    assert load_rules(rules_file(tmp_path, value)).breakeven_r_threshold == Decimal(str(value))


@pytest.mark.parametrize("value", [-0.1, "abc", None])
def test_invalid_value_is_a_config_error(tmp_path: Path, value: Any) -> None:
    with pytest.raises(ConfigError) as info:
        load_rules(rules_file(tmp_path, value))

    assert "breakeven_r_threshold" in str(info.value)


def test_exposed_in_the_rules_api_dict(tmp_path: Path) -> None:
    assert load_rules(rules_file(tmp_path, 0.25)).to_api()["breakeven_r_threshold"] == "0.25"
