"""M6-04 (RED): ``digest.deviation_sigma`` in config/rules.yaml (docs/api.md "Norm and deviation").

``get_rules().digest.deviation_sigma`` is a Decimal > 0, default 1.0 when the ``digest`` section
(or the key) is absent; a value <= 0 or a non-number is a ConfigError naming the key.
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


def rules_file(tmp_path: Path, digest: Any = "absent") -> Path:
    data = read_yaml(REPO_ROOT / "config" / "rules.yaml")
    data.pop("digest", None)
    if digest != "absent":
        data["digest"] = digest
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_default_sigma_is_one_without_a_digest_section(tmp_path: Path) -> None:
    assert load_rules(rules_file(tmp_path)).digest.deviation_sigma == Decimal("1.0")


def test_default_sigma_is_one_with_an_empty_digest_section(tmp_path: Path) -> None:
    assert load_rules(rules_file(tmp_path, {})).digest.deviation_sigma == Decimal("1.0")


def test_real_rules_file_loads_with_sigma_one() -> None:
    assert load_rules(REPO_ROOT / "config" / "rules.yaml").digest.deviation_sigma == Decimal(1)


@pytest.mark.parametrize("value", [1.5, 0.5, 2, 3.25])
def test_custom_sigma_is_read_as_a_decimal(tmp_path: Path, value: float) -> None:
    config = load_rules(rules_file(tmp_path, {"deviation_sigma": value}))

    assert config.digest.deviation_sigma == Decimal(str(value))


@pytest.mark.parametrize("value", [0, -1, -0.5, "abc", None])
def test_invalid_sigma_is_a_config_error(tmp_path: Path, value: Any) -> None:
    with pytest.raises(ConfigError) as info:
        load_rules(rules_file(tmp_path, {"deviation_sigma": value}))

    assert "deviation_sigma" in str(info.value)


def test_unknown_digest_key_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_rules(rules_file(tmp_path, {"deviation_sigma": 1, "sigma_typo": 2}))

    assert "sigma_typo" in str(info.value)


def test_sigma_is_exposed_in_the_rules_api_dict(tmp_path: Path) -> None:
    api = load_rules(rules_file(tmp_path, {"deviation_sigma": 1.5})).to_api()

    assert api["digest"]["deviation_sigma"] == "1.5"
