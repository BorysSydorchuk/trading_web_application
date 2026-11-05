"""config/rules.yaml + config/journal_fields.yaml loaders and their endpoints."""

from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Iterator
from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import db as app_db
from app.config import REPO_ROOT
from app.config_files import (
    RULE_KEYS,
    ConfigError,
    check_config_files,
    get_journal_fields,
    get_rules,
    reload_config,
)
from app.config_files.journal_fields import load_journal_fields
from app.config_files.loader import CONFIG_DIR_ENV, read_yaml
from app.config_files.rules import load_rules
from app.main import create_app

REAL_CONFIG = REPO_ROOT / "config"


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A writable copy of the real config dir, active via CONFIG_DIR."""
    for name in (
        "rules.yaml",
        "journal_fields.yaml",
        "ai_pricing.yaml",
        "extraction.yaml",
        "transcription.yaml",
        "transcript_glossary.yaml",
    ):
        shutil.copy(REAL_CONFIG / name, tmp_path / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def _read(path: Path) -> Any:
    # Same parser as the app: `yes`/`no` stay strings.
    return read_yaml(path)


def _write(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _rules_error(cfg_dir: Path, data: Any) -> str:
    _write(cfg_dir / "rules.yaml", data)
    with pytest.raises(ConfigError) as info:
        load_rules()
    return str(info.value)


def _fields_error(cfg_dir: Path, data: Any) -> str:
    _write(cfg_dir / "journal_fields.yaml", data)
    with pytest.raises(ConfigError) as info:
        load_journal_fields()
    return str(info.value)


def _field(data: dict[str, Any], key: str) -> dict[str, Any]:
    field: dict[str, Any] = next(f for f in data["fields"] if f["key"] == key)
    return field


# --- real files ---------------------------------------------------------------------


def test_real_rules_load() -> None:
    reload_config()
    rules = get_rules()

    assert rules.timezone == "Europe/Brussels"
    assert str(rules.tz) == "Europe/Brussels"
    assert [(w.name, w.start, w.end, w.entries_allowed) for w in rules.sessions] == [
        ("london", time(8), time(11), True),
        ("premarket", time(11), time(13), False),
        ("ny", time(13), time(16), True),
    ]
    assert rules.rules.max_risk_pct.value == Decimal("1.1")
    assert isinstance(rules.rules.daily_stop_loss_pct.value, Decimal)
    assert rules.rules.max_trades_per_week.value == 10
    assert rules.rules.qm_not_in_ny.entry_model == "qm_m5"
    assert rules.sync.trading_days == ("mon", "tue", "wed", "thu", "fri")
    assert rules.broker_time == "ny_close"
    ny = rules.session("ny")
    assert ny is not None
    assert ny.contains(time(13))
    assert not ny.contains(time(16))


def test_real_journal_fields_load() -> None:
    reload_config()
    config = get_journal_fields()

    keys = [f.key for f in config.fields]
    assert keys == [
        "setup_context",
        "poi_type",
        "fvg_kind",
        "entry_model",
        "exit_reason",
        "bias_alignment",
        "followed_plan",
        "rule_violations",
        "emotion_before",
        "emotion_after",
        "mistakes",
        "lesson",
        "quality_rating",
        "chart_links",
    ]
    assert "status" not in keys
    setup = config.get("setup_context")
    assert setup is not None
    # `yes`/`no` must stay strings (YAML 1.1 would turn them into booleans).
    assert setup.option_values() == ["yes", "no", "partially"]
    poi = config.get("poi_type")
    assert poi is not None
    assert poi.allow_other_text
    assert poi.text_key == "poi_type_other"
    violations = config.get("rule_violations")
    assert violations is not None
    assert set(violations.option_values()) == set(RULE_KEYS)
    quality = config.get("quality_rating")
    assert quality is not None
    assert (quality.min, quality.max) == (1, 5)


def test_cache_reloads_when_file_changes(cfg_dir: Path) -> None:
    assert get_rules().rules.max_trades_per_week.value == 10
    data = _read(cfg_dir / "rules.yaml")
    data["rules"]["max_trades_per_week"]["value"] = 7
    data["timezone"] = "Europe/Kyiv"  # also changes the size, so the stamp differs
    _write(cfg_dir / "rules.yaml", data)

    assert get_rules().rules.max_trades_per_week.value == 7


# --- invalid rules.yaml ---------------------------------------------------------------


def test_overlapping_sessions(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "rules.yaml")
    data["sessions"]["premarket"]["start"] = "10:30"
    msg = _rules_error(cfg_dir, data)
    assert "rules.yaml" in msg
    assert "sessions: premarket (10:30-13:00) overlaps london (08:00-11:00)" in msg


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("8:00", 'expected time as "HH:MM"'),
        ("24:00", 'expected time as "HH:MM"'),
        (480, 'expected a quoted "HH:MM" string'),
    ],
)
def test_bad_session_time(cfg_dir: Path, value: Any, expected: str) -> None:
    data = _read(cfg_dir / "rules.yaml")
    data["sessions"]["london"]["start"] = value
    msg = _rules_error(cfg_dir, data)
    assert "london.start" in msg
    assert expected in msg


def test_unquoted_time_in_yaml_is_readable(cfg_dir: Path) -> None:
    path = cfg_dir / "rules.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'start: "08:00", end: "11:00"', "start: 08:00, end: 11:00"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match='expected a quoted "HH:MM" string'):
        load_rules()


def test_session_end_before_start(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "rules.yaml")
    data["sessions"]["ny"] = {"start": "16:00", "end": "13:00", "entries_allowed": True}
    assert "ny.(root): start 16:00 must be before end 13:00" in _rules_error(cfg_dir, data)


def test_unknown_session_and_rule_and_timezone(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "rules.yaml")
    data["sessions"]["asia"] = {"start": "01:00", "end": "05:00", "entries_allowed": False}
    data["rules"]["max_coffee"] = {"enabled": True}
    data["timezone"] = "Europe/Atlantis"
    msg = _rules_error(cfg_dir, data)
    assert "asia: unknown session name" in msg
    assert "rules.max_coffee: Extra inputs are not permitted" in msg
    assert "timezone: unknown timezone 'Europe/Atlantis'" in msg


def test_missing_rule_and_wrong_sign(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "rules.yaml")
    del data["rules"]["no_breakeven"]
    data["rules"]["daily_stop_loss_pct"]["value"] = 3
    msg = _rules_error(cfg_dir, data)
    assert "rules.no_breakeven: Field required" in msg
    assert "rules.daily_stop_loss_pct.value: Input should be less than 0" in msg


def test_duplicate_yaml_key(cfg_dir: Path) -> None:
    path = cfg_dir / "rules.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("sessions:\n", 'sessions:\n  ny: { start: "17:00" }\n'), "utf-8")
    with pytest.raises(ConfigError, match="found duplicate key 'ny'"):
        load_rules()


def test_missing_file(cfg_dir: Path) -> None:
    (cfg_dir / "rules.yaml").unlink()
    with pytest.raises(ConfigError, match=r"rules\.yaml:\n  - file not found"):
        get_rules()


# --- invalid journal_fields.yaml ---------------------------------------------------------


def test_unknown_field_type(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    _field(data, "lesson")["type"] = "essay"
    msg = _fields_error(cfg_dir, data)
    assert "journal_fields.yaml" in msg
    assert re.search(r"fields\[\d+\] \(lesson\)\.type: Input should be 'enum'", msg)


def test_column_key_not_on_trade(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    data["fields"].append(
        {
            "key": "news_risk",
            "label": "Новини",
            "type": "bool",
            "required": False,
            "analytics": True,
            "storage": "column",
        }
    )
    msg = _fields_error(cfg_dir, data)
    assert "news_risk: storage is column but trades has no column 'news_risk'" in msg


def test_extra_field_is_accepted(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    data["fields"].append(
        {
            "key": "news_risk",
            "label": "Новини",
            "type": "bool",
            "required": False,
            "analytics": True,
            "storage": "extra",
        }
    )
    _write(cfg_dir / "journal_fields.yaml", data)
    field = load_journal_fields().get("news_risk")
    assert field is not None
    assert field.storage == "extra"


def test_missing_text_column(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    _field(data, "entry_model").update(text_key="entry_model_other", allow_other_text=True)
    msg = _fields_error(cfg_dir, data)
    assert "entry_model: trades has no column 'entry_model_other' for text_key" in msg


def test_duplicate_option_values(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    _field(data, "exit_reason")["options"].append({"value": "sl", "label": "стоп"})
    msg = _fields_error(cfg_dir, data)
    assert re.search(r"fields\[\d+\] \(exit_reason\): duplicate option values: sl", msg)


def test_reserved_and_duplicate_keys(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    data["fields"].append(dict(_field(data, "lesson")))
    msg = _fields_error(cfg_dir, data)
    assert "key 'lesson' is used twice" in msg

    data = _read(REAL_CONFIG / "journal_fields.yaml")
    data["fields"].append({**_field(data, "lesson"), "key": "status"})
    assert "status: reserved trade column" in _fields_error(cfg_dir, data)


def test_bias_option_outside_db_values(cfg_dir: Path) -> None:
    data = _read(cfg_dir / "journal_fields.yaml")
    _field(data, "bias_alignment")["options"].append({"value": "maybe", "label": "може"})
    assert "unknown option values maybe" in _fields_error(cfg_dir, data)


def test_qm_rule_must_reference_entry_model_option(cfg_dir: Path) -> None:
    rules = _read(cfg_dir / "rules.yaml")
    rules["rules"]["qm_not_in_ny"]["entry_model"] = "QM M5"
    _write(cfg_dir / "rules.yaml", rules)
    with pytest.raises(ConfigError, match="'QM M5' is not an option of the entry_model field"):
        load_journal_fields()


def test_check_config_files_logs_loudly(cfg_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    (cfg_dir / "journal_fields.yaml").write_text("fields: [", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="app.config_files"):
        errors = check_config_files()
    assert len(errors) == 1
    assert "CONFIG ERROR" in caplog.text
    assert "journal_fields.yaml" in caplog.text
    assert "YAML syntax error" in caplog.text


# --- endpoints (no DB needed) --------------------------------------------------------------


@pytest.fixture
def api() -> Iterator[TestClient]:
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


def test_get_journal_fields(cfg_dir: Path, api: TestClient) -> None:
    response = api.get("/api/journal-fields")
    assert response.status_code == 200
    fields = response.json()["fields"]
    first = fields[0]
    assert set(first) == {
        "key",
        "label",
        "type",
        "options",
        "required",
        "analytics",
        "storage",
        "text_key",
        "allow_other_text",
        "min",
        "max",
    }
    assert first["key"] == "setup_context"
    assert first["options"][0] == {"value": "yes", "label": "так", "deprecated": False}
    assert first["storage"] == "column"


def test_get_rules(cfg_dir: Path, api: TestClient) -> None:
    response = api.get("/api/rules")
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Europe/Brussels"
    assert body["sessions"][0] == {
        "name": "london",
        "start": "08:00",
        "end": "11:00",
        "entries_allowed": True,
    }
    assert body["rules"]["max_risk_pct"] == {"enabled": True, "value": "1.1"}
    assert body["rules"]["max_trades_per_week"] == {"enabled": True, "value": 10}
    assert body["sync"]["trading_hours"] == {"start": "08:00", "end": "16:00"}


def test_api_starts_with_broken_config(
    cfg_dir: Path, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """A config broken before startup is logged, health stays up, endpoints say config_error."""
    (cfg_dir / "journal_fields.yaml").write_text("fields: [", encoding="utf-8")
    application = create_app()
    session_factory = app_db.make_session_factory(db_engine)

    def _get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[app_db.get_db] = _get_db
    with (
        caplog.at_level(logging.ERROR, logger="app.config_files"),
        TestClient(application, raise_server_exceptions=False) as client,
    ):
        health = client.get("/api/health")
        fields = client.get("/api/journal-fields")
        rules = client.get("/api/rules")

    assert "CONFIG ERROR" in caplog.text
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert fields.status_code == 500
    error = fields.json()["error"]
    assert error["code"] == "config_error"
    assert error["details"]["file"] == "journal_fields.yaml"
    assert "YAML syntax error" in error["message"]
    assert rules.status_code == 200  # the other file is still served


def test_broken_config_returns_config_error(cfg_dir: Path, api: TestClient) -> None:
    data = _read(cfg_dir / "rules.yaml")
    data["sessions"]["premarket"]["start"] = "10:00"
    _write(cfg_dir / "rules.yaml", data)

    response = api.get("/api/rules")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "config_error"
    assert "overlaps london" in error["message"]
    assert error["details"]["file"] == "rules.yaml"
    assert any("overlaps" in p for p in error["details"]["problems"])
    # Fixing the file is picked up without a restart.
    shutil.copy(REAL_CONFIG / "rules.yaml", cfg_dir / "rules.yaml")
    assert api.get("/api/rules").status_code == 200
