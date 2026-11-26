"""`config/firms.yaml` loader (docs/api.md "Firm rules from config: KeyFunding")."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import REPO_ROOT
from app.config_files import ConfigError, reload_config
from app.config_files.firms import (
    clear_firms_cache,
    get_firms_config,
    load_firms,
    normalize_firm,
)
from app.config_files.loader import CONFIG_DIR_ENV

D = Decimal

KEY: dict[str, Any] = {
    "daily_loss_pct": 4.0,
    "max_loss_pct": 8.0,
    "max_loss_type": "static",
    "profit_target_pct": {"phase_1": 8.0, "phase_2": 4.0},
    "daily_basis": "balance",
    "daily_reset": "00:00",
    "reset_timezone": "server",
    "to_verify": ["daily_basis", "daily_reset"],
}


def write(tmp_path: Path, raw: Any) -> Path:
    path = tmp_path / "firms.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def firm_with(**changes: Any) -> dict[str, Any]:
    return {"firms": {"KeyFunding": {**KEY, **changes}}}


def problems(tmp_path: Path, raw: Any) -> str:
    with pytest.raises(ConfigError) as info:
        load_firms(write(tmp_path, raw))
    return str(info.value)


def test_valid_file_loads_with_decimals(tmp_path: Path) -> None:
    config = load_firms(write(tmp_path, {"firms": {"KeyFunding": KEY}}))

    rule = config.firms["KeyFunding"]
    assert rule.daily_loss_pct == D("4.0")
    assert rule.max_loss_pct == D("8.0")
    assert rule.profit_target_pct.phase_1 == D("8.0")
    assert rule.profit_target_pct.phase_2 == D("4.0")
    assert rule.reset_timezone == "server"
    assert rule.to_verify == ("daily_basis", "daily_reset")


def test_real_file_is_the_keyfunding_contract() -> None:
    config = load_firms(REPO_ROOT / "config" / "firms.yaml")

    rule = config.firms["KeyFunding"]
    assert (rule.daily_loss_pct, rule.max_loss_pct) == (D("4"), D("8"))
    assert (rule.profit_target_pct.phase_1, rule.profit_target_pct.phase_2) == (D("8"), D("4"))
    assert rule.max_loss_type == "static"
    assert rule.daily_basis == "balance"
    assert rule.daily_reset == "00:00"
    assert rule.reset_timezone == "EET"  # Borys 2026-11-26: 00:00 server time EET
    assert rule.to_verify == ()  # both items confirmed by Borys 2026-11-26
    assert list(config.firms) == ["KeyFunding"]


def test_missing_file_means_no_firms(tmp_path: Path) -> None:
    config = load_firms(tmp_path / "firms.yaml")

    assert config.firms == {}
    assert config.match("KeyFunding") is None


def test_empty_file_means_no_firms(tmp_path: Path) -> None:
    path = tmp_path / "firms.yaml"
    path.write_text("", encoding="utf-8")

    assert load_firms(path).firms == {}


def test_optional_fields_default(tmp_path: Path) -> None:
    config = load_firms(
        write(tmp_path, {"firms": {"Acme": {"daily_loss_pct": 5, "max_loss_pct": 10}}})
    )

    rule = config.firms["Acme"]
    assert rule.max_loss_type == "static"
    assert rule.daily_basis == "balance"
    assert rule.daily_reset == "00:00"
    assert rule.reset_timezone == "server"
    assert rule.profit_target_pct.phase_1 is None
    assert rule.to_verify == ()


@pytest.mark.parametrize(
    "name", ["KeyFunding", "Key Funding", "keyfunding", " KEY-funding ", "key_funding"]
)
def test_firm_name_matching_ignores_case_spaces_dashes_underscores(
    tmp_path: Path, name: str
) -> None:
    config = load_firms(write(tmp_path, {"firms": {"KeyFunding": KEY}}))

    found = config.match(name)
    assert found is not None
    assert found.name == "KeyFunding"
    assert found.rule.max_loss_pct == D("8.0")


@pytest.mark.parametrize("name", ["FundedNext", "", "Key", None])
def test_other_firm_names_do_not_match(tmp_path: Path, name: str | None) -> None:
    config = load_firms(write(tmp_path, {"firms": {"KeyFunding": KEY}}))

    assert config.match(name) is None


def test_normalize_firm() -> None:
    assert normalize_firm(" Key-Funding_X ") == "keyfundingx"


def test_extra_key_is_rejected(tmp_path: Path) -> None:
    assert "bogus" in problems(tmp_path, firm_with(bogus=1))


def test_extra_top_level_key_is_rejected(tmp_path: Path) -> None:
    assert "other" in problems(tmp_path, {"firms": {}, "other": 1})


def test_root_must_be_a_mapping(tmp_path: Path) -> None:
    assert "mapping" in problems(tmp_path, ["KeyFunding"])


@pytest.mark.parametrize("field", ["daily_loss_pct", "max_loss_pct"])
@pytest.mark.parametrize("value", [0, -1, 100, 150, "abc"])
def test_percent_out_of_range_is_rejected(tmp_path: Path, field: str, value: Any) -> None:
    assert field in problems(tmp_path, firm_with(**{field: value}))


def test_profit_target_out_of_range_is_rejected(tmp_path: Path) -> None:
    text = problems(tmp_path, firm_with(profit_target_pct={"phase_1": 100}))

    assert "profit_target_pct" in text


def test_profit_target_unknown_phase_is_rejected(tmp_path: Path) -> None:
    assert "funded" in problems(tmp_path, firm_with(profit_target_pct={"funded": 5}))


def test_daily_loss_and_max_loss_are_required(tmp_path: Path) -> None:
    text = problems(tmp_path, {"firms": {"Acme": {"daily_loss_pct": 4}}})

    assert "max_loss_pct" in text


def test_duplicate_firm_case_insensitive_is_rejected(tmp_path: Path) -> None:
    raw = {"firms": {"KeyFunding": KEY, "keyfunding": KEY}}

    assert "listed twice" in problems(tmp_path, raw)


def test_duplicate_firm_ignoring_spaces_is_rejected(tmp_path: Path) -> None:
    raw = {"firms": {"KeyFunding": KEY, "Key Funding": KEY}}

    assert "listed twice" in problems(tmp_path, raw)


def test_blank_firm_name_is_rejected(tmp_path: Path) -> None:
    assert "empty" in problems(tmp_path, {"firms": {" ": KEY}})


@pytest.mark.parametrize("bad", ["24:00", "9:00", "0900", "12:60", "ab:cd", "", 0, "00:00:00"])
def test_bad_daily_reset_is_rejected(tmp_path: Path, bad: Any) -> None:
    assert "daily_reset" in problems(tmp_path, firm_with(daily_reset=bad))


@pytest.mark.parametrize("good", ["00:00", "23:59", "07:30"])
def test_good_daily_reset_is_accepted(tmp_path: Path, good: str) -> None:
    rule = load_firms(write(tmp_path, firm_with(daily_reset=good))).firms["KeyFunding"]

    assert rule.daily_reset == good


@pytest.mark.parametrize("bad", ["Mars/Phobos", "", "Europe/", "../etc"])
def test_bad_reset_timezone_is_rejected(tmp_path: Path, bad: str) -> None:
    assert "reset_timezone" in problems(tmp_path, firm_with(reset_timezone=bad))


def test_iana_reset_timezone_is_accepted(tmp_path: Path) -> None:
    config = load_firms(write(tmp_path, firm_with(reset_timezone="America/New_York")))

    assert config.firms["KeyFunding"].reset_timezone == "America/New_York"


def test_unknown_to_verify_item_is_rejected(tmp_path: Path) -> None:
    assert "to_verify" in problems(tmp_path, firm_with(to_verify=["daily_basis", "nonsense"]))


def test_to_verify_duplicates_are_rejected(tmp_path: Path) -> None:
    assert "to_verify" in problems(tmp_path, firm_with(to_verify=["daily_reset", "daily_reset"]))


@pytest.mark.parametrize(
    ("field", "value"), [("max_loss_type", "trailing"), ("daily_basis", "equity")]
)
def test_only_supported_enum_values(tmp_path: Path, field: str, value: str) -> None:
    assert field in problems(tmp_path, firm_with(**{field: value}))


def test_yaml_syntax_error_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "firms.yaml"
    path.write_text("firms: [unclosed", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_firms(path)


def test_duplicate_yaml_key_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "firms.yaml"
    entry = "{daily_loss_pct: 4, max_loss_pct: 8}"
    path.write_text(f"firms:\n  A: {entry}\n  A: {entry}\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_firms(path)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def test_cached_accessor_reloads_when_the_file_changes(cfg: Path) -> None:
    assert get_firms_config().firms == {}  # no file
    write(cfg, {"firms": {"KeyFunding": KEY}})

    assert "KeyFunding" in get_firms_config().firms

    write(cfg, firm_with(max_loss_pct=9.0))
    assert get_firms_config().firms["KeyFunding"].max_loss_pct == D("9.0")


def test_broken_file_is_not_cached(cfg: Path) -> None:
    write(cfg, firm_with(max_loss_pct=0))
    with pytest.raises(ConfigError):
        get_firms_config()

    write(cfg, firm_with(max_loss_pct=8))

    assert get_firms_config().firms["KeyFunding"].max_loss_pct == D("8")


def test_reload_config_clears_the_firms_cache(cfg: Path) -> None:
    write(cfg, {"firms": {"KeyFunding": KEY}})
    first = get_firms_config()
    reload_config()

    assert get_firms_config() is not first
    clear_firms_cache()


def test_daily_loss_above_max_loss_is_rejected(tmp_path: Path) -> None:
    text = problems(tmp_path, firm_with(daily_loss_pct=9.0, max_loss_pct=8.0))

    assert "daily_loss_pct" in text
    assert "max_loss_pct" in text


def test_daily_loss_equal_to_max_loss_is_accepted(tmp_path: Path) -> None:
    rule = load_firms(write(tmp_path, firm_with(daily_loss_pct=8.0))).firms["KeyFunding"]

    assert rule.daily_loss_pct == rule.max_loss_pct


def test_unquoted_daily_reset_says_to_quote_the_time(tmp_path: Path) -> None:
    path = tmp_path / "firms.yaml"
    path.write_text(
        "firms:\n  A:\n    daily_loss_pct: 4\n    max_loss_pct: 8\n    daily_reset: 10:30\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as info:
        load_firms(path)

    assert "daily_reset" in str(info.value)
    assert "quotes" in str(info.value)


@pytest.mark.parametrize("field", ["daily_loss_pct", "max_loss_pct"])
def test_bool_is_not_a_percent(tmp_path: Path, field: str) -> None:
    assert field in problems(tmp_path, firm_with(**{field: True}))


def test_bool_is_not_a_profit_target(tmp_path: Path) -> None:
    assert "profit_target_pct" in problems(tmp_path, firm_with(profit_target_pct={"phase_1": True}))


def test_same_size_edit_with_a_new_mtime_is_reloaded(cfg: Path) -> None:
    import os

    path = write(cfg, firm_with(max_loss_pct=8.0))
    assert get_firms_config().firms["KeyFunding"].max_loss_pct == D("8.0")
    stat = path.stat()

    write(cfg, firm_with(max_loss_pct=7.0))  # same byte size
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    assert get_firms_config().firms["KeyFunding"].max_loss_pct == D("7.0")
