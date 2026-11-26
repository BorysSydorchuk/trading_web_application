"""M8-04 config/violations.yaml (docs/api.md "Violations"): loader, validation and the real
file. New module expected: app.config_files.violations (`load_violations(path)`, entries in
`.violations` with `.key`, `.label`, `.type`, `.status`)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import REPO_ROOT
from app.config_files import ConfigError, check_config_files, reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.config_files.violations import load_violations

ENGINE_KEYS = [
    "max_risk_pct",
    "daily_risk",
    "weekly_risk",
    "firm_daily_loss",
    "max_trades_per_week",
    "max_reentries_per_idea",
    "min_planned_rr",
    "entry_session",
    "qm_not_in_ny",
    "no_breakeven",
]
OLD_KEYS = [
    "daily_stop_loss_pct",
    "daily_stop_profit_pct",
    "weekly_stop_loss_pct",
    "weekly_stop_profit_pct",
]


def entry(key: str, type_: str = "auto", status: str = "active") -> dict[str, str]:
    return {"key": key, "label": f"label {key}", "type": type_, "status": status}


def valid_entries() -> list[dict[str, str]]:
    return [entry(k) for k in ENGINE_KEYS] + [entry("my_manual", "manual")]


def write(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    path = tmp_path / "violations.yaml"
    path.write_text(
        yaml.safe_dump({"violations": entries}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def problems_of(tmp_path: Path, entries: list[dict[str, str]]) -> str:
    with pytest.raises(ConfigError) as info:
        load_violations(write(tmp_path, entries))
    return str(info.value)


# --- loader ---


def test_valid_file_loads(tmp_path: Path) -> None:
    config = load_violations(write(tmp_path, valid_entries()))

    assert [v.key for v in config.violations] == [*ENGINE_KEYS, "my_manual"]
    manual = config.violations[-1]
    assert (manual.type, manual.status) == ("manual", "active")


def test_adding_a_manual_entry_needs_no_code_change(tmp_path: Path) -> None:
    entries = [*valid_entries(), entry("another_manual", "manual")]

    config = load_violations(write(tmp_path, entries))

    assert "another_manual" in {v.key for v in config.violations}


def test_deprecated_entries_are_accepted(tmp_path: Path) -> None:
    entries = [*valid_entries(), entry("old_manual", "manual", "deprecated")]
    entries += [entry(k, "auto", "deprecated") for k in OLD_KEYS]

    config = load_violations(write(tmp_path, entries))

    deprecated = {v.key for v in config.violations if v.status == "deprecated"}
    assert deprecated == {"old_manual", *OLD_KEYS}


def test_duplicate_key_is_rejected(tmp_path: Path) -> None:
    message = problems_of(tmp_path, [*valid_entries(), entry("my_manual", "manual")])

    assert "my_manual" in message


@pytest.mark.parametrize("bad", ["Bad-Key", "1abc", "has space", "UPPER", "", "x" * 51])
def test_bad_key_is_rejected(tmp_path: Path, bad: str) -> None:
    message = problems_of(tmp_path, [*valid_entries(), entry(bad, "manual")])

    assert "violations[" in message or (bad and bad in message)


def test_key_of_50_characters_is_accepted(tmp_path: Path) -> None:
    key = "k" * 50

    config = load_violations(write(tmp_path, [*valid_entries(), entry(key, "manual")]))

    assert key in {v.key for v in config.violations}


def test_unknown_type_or_status_is_rejected(tmp_path: Path) -> None:
    assert "my_manual" in problems_of(tmp_path, [*valid_entries()[:-1], entry("my_manual", "hand")])
    assert "my_manual" in problems_of(
        tmp_path, [*valid_entries()[:-1], entry("my_manual", "manual", "gone")]
    )


def test_missing_engine_key_is_rejected(tmp_path: Path) -> None:
    entries = [e for e in valid_entries() if e["key"] != "no_breakeven"]

    assert "no_breakeven" in problems_of(tmp_path, entries)


def test_engine_key_declared_manual_is_rejected(tmp_path: Path) -> None:
    entries = [entry(k, "manual" if k == "entry_session" else "auto") for k in ENGINE_KEYS]

    assert "entry_session" in problems_of(tmp_path, entries)


def test_engine_key_deprecated_is_rejected(tmp_path: Path) -> None:
    entries = [
        entry(k, "auto", "deprecated" if k == "daily_risk" else "active") for k in ENGINE_KEYS
    ]

    assert "daily_risk" in problems_of(tmp_path, entries)


def test_active_auto_key_unknown_to_the_engine_is_rejected(tmp_path: Path) -> None:
    message = problems_of(tmp_path, [*valid_entries(), entry("mystery_rule", "auto")])

    assert "mystery_rule" in message


def test_no_active_entry_is_rejected(tmp_path: Path) -> None:
    entries = [entry(k, "auto", "deprecated") for k in ENGINE_KEYS]

    assert "active" in problems_of(tmp_path, entries)


def test_empty_list_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_violations(write(tmp_path, []))


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_violations(tmp_path / "violations.yaml")


def test_extra_entry_field_is_rejected(tmp_path: Path) -> None:
    entries: list[dict[str, Any]] = [*valid_entries()]
    entries[0] = entries[0] | {"colour": "red"}

    assert "colour" in problems_of(tmp_path, entries)


# --- the real file ---


def test_real_file_has_the_contract_keys_and_labels() -> None:
    config = load_violations(REPO_ROOT / "config" / "violations.yaml")
    by_key = {v.key: v for v in config.violations}

    assert set(ENGINE_KEYS) <= set(by_key)
    for key in ENGINE_KEYS:
        assert (by_key[key].type, by_key[key].status) == ("auto", "active")
    assert by_key["daily_risk"].label == "Порушення денного ризику"
    assert by_key["weekly_risk"].label == "Порушення тижневого ризику"
    labels = {
        "entry_not_by_model": "Вхід не за моделлю входу",
        "entry_weak_poi": "Вхід від слабкої POI",
        "entry_against_system": ("Вхід не за торговою системою (не дотримуючись контексту H1/H4)"),
    }
    for key, label in labels.items():
        assert (by_key[key].label, by_key[key].type, by_key[key].status) == (
            label,
            "manual",
            "active",
        )


def test_real_file_keeps_old_keys_as_deprecated_auto_with_their_labels() -> None:
    by_key = {
        v.key: v for v in load_violations(REPO_ROOT / "config" / "violations.yaml").violations
    }

    expected = {
        "daily_stop_loss_pct": "вхід після денного стоп-лосу",
        "daily_stop_profit_pct": "вхід після денного стоп-профіту",
        "weekly_stop_loss_pct": "вхід після тижневого стоп-лосу",
        "weekly_stop_profit_pct": "вхід після тижневого стоп-профіту",
    }
    for key, label in expected.items():
        assert (by_key[key].label, by_key[key].type, by_key[key].status) == (
            label,
            "auto",
            "deprecated",
        )


def test_every_engine_key_emitted_by_the_rules_is_in_the_real_file() -> None:
    from app.config_files.rules import RULE_KEYS

    real = {v.key for v in load_violations(REPO_ROOT / "config" / "violations.yaml").violations}
    stop_keys = set(OLD_KEYS)

    assert (set(RULE_KEYS) - stop_keys) <= real


# --- startup check ---


def test_check_config_files_reports_a_broken_violations_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for path in (REPO_ROOT / "config").glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "violations.yaml").write_text("violations: []\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    try:
        errors = check_config_files()
    finally:
        monkeypatch.undo()
        reload_config()

    assert any(e.path.name == "violations.yaml" for e in errors)
