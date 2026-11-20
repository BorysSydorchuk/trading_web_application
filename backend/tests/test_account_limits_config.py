"""M8-10b: optional ``account_limits`` in config/rules.yaml (docs/api.md "M8-10b").

``{max_drawdown_pct: < 0, profit_target_pct: > 0}``, display only (the «Ліміти» month bar).
Missing section -> ``None``; a wrong sign, a missing or unknown key is a ConfigError.
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


def rules_file(tmp_path: Path, limits: Any = "absent") -> Path:
    data = read_yaml(REPO_ROOT / "config" / "rules.yaml")
    data.pop("account_limits", None)
    if limits != "absent":
        data["account_limits"] = limits
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_missing_section_is_none(tmp_path: Path) -> None:
    assert load_rules(rules_file(tmp_path)).account_limits is None


def test_real_rules_file_has_the_fundednext_limits() -> None:
    limits = load_rules(REPO_ROOT / "config" / "rules.yaml").account_limits

    assert limits is not None
    assert (limits.max_drawdown_pct, limits.profit_target_pct) == (
        Decimal("-10.0"),
        Decimal("10.0"),
    )


def test_values_are_decimals(tmp_path: Path) -> None:
    config = load_rules(rules_file(tmp_path, {"max_drawdown_pct": -8.5, "profit_target_pct": 8}))

    assert config.account_limits is not None
    assert config.account_limits.max_drawdown_pct == Decimal("-8.5")
    assert config.account_limits.profit_target_pct == Decimal("8")


@pytest.mark.parametrize(
    ("limits", "key"),
    [
        ({"max_drawdown_pct": 0, "profit_target_pct": 10}, "max_drawdown_pct"),
        ({"max_drawdown_pct": 10, "profit_target_pct": 10}, "max_drawdown_pct"),
        ({"max_drawdown_pct": -10, "profit_target_pct": 0}, "profit_target_pct"),
        ({"max_drawdown_pct": -10, "profit_target_pct": -5}, "profit_target_pct"),
        ({"max_drawdown_pct": -10, "profit_target_pct": "abc"}, "profit_target_pct"),
        ({"max_drawdown_pct": -10}, "profit_target_pct"),
        ({"max_drawdown_pct": -10, "profit_target_pct": 10, "typo": 1}, "typo"),
    ],
)
def test_invalid_limits_are_a_config_error(tmp_path: Path, limits: Any, key: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_rules(rules_file(tmp_path, limits))

    assert key in str(info.value)


def test_limits_are_in_the_rules_api_dict(tmp_path: Path) -> None:
    limits = {"max_drawdown_pct": -10.0, "profit_target_pct": 10.0}

    api = load_rules(rules_file(tmp_path, limits)).to_api()

    assert api["account_limits"] == {"max_drawdown_pct": "-10.0", "profit_target_pct": "10.0"}
