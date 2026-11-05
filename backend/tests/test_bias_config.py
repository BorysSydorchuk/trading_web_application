"""config/bias.yaml: strict validation, reload on change, GET /api/bias/config (docs/api.md M4)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from datetime import time as dtime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config_files import ConfigError, check_config_files, get_bias_config, reload_config
from app.config_files.bias import load_bias
from app.config_files.loader import CONFIG_DIR_ENV, REASON_MOJIBAKE
from app.main import create_app
from app.models.enums import BiasKind

REAL_FILE = Path(__file__).resolve().parents[2] / "config" / "bias.yaml"

REMINDERS = """
reminders:
  pre_london: { from: "07:45", until: "11:00" }
  pre_ny: { from: "12:30", until: "16:00" }
"""
SYMBOLS = """
symbols:
  - { symbol: EURUSD, aliases: [євро, fiber] }
  - { symbol: GER40, aliases: [дакс, DAX] }
"""


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _problems(tmp_path: Path, text: str) -> list[str]:
    with pytest.raises(ConfigError) as info:
        load_bias(_write(tmp_path / "bias.yaml", text))
    return info.value.problems


def test_real_file_matches_contract() -> None:
    config = load_bias(REAL_FILE)
    assert config.symbol_names == ("EURUSD", "GBPUSD", "XAUUSD", "GER40")
    assert config.symbols[2].aliases == ("золото", "gold", "голд")
    assert config.symbols[3].aliases == ("дакс", "DAX", "GER")
    assert config.reminders.pre_london.to_api() == {"from": "07:45", "until": "11:00"}
    assert config.reminders.pre_ny.to_api() == {"from": "12:30", "until": "16:00"}


def test_reminder_window_half_open() -> None:
    window = load_bias(REAL_FILE).reminders.pre_london
    assert not window.contains(dtime(7, 44))
    assert window.contains(dtime(7, 45))
    assert window.contains(dtime(10, 59))
    assert not window.contains(dtime(11, 0))


def test_reminder_by_kind() -> None:
    config = load_bias(REAL_FILE)
    assert config.reminder(BiasKind.PRE_NY) == config.reminders.pre_ny
    assert config.reminder(BiasKind.PRE_LONDON) == config.reminders.pre_london
    assert config.reminder(BiasKind.WEEKLY) is None


def test_values_are_stripped_and_empty_aliases_allowed(tmp_path: Path) -> None:
    text = 'symbols:\n  - { symbol: " XAUUSD ", aliases: [" золото "] }\n'
    text += "  - { symbol: GER40, aliases: [] }\n" + REMINDERS
    config = load_bias(_write(tmp_path / "bias.yaml", text))
    assert config.symbol_names == ("XAUUSD", "GER40")
    assert config.symbols[0].aliases == ("золото",)


def test_unquoted_time_with_leading_zero_accepted(tmp_path: Path) -> None:
    """YAML reads 07:45 as a string (a leading zero is not base-60), so it parses."""
    text = SYMBOLS + (
        "reminders:\n  pre_london: { from: 07:45, until: '11:00' }\n"
        "  pre_ny: { from: '12:30', until: '16:00' }\n"
    )
    window = load_bias(_write(tmp_path / "bias.yaml", text)).reminders.pre_london
    assert window.to_api() == {"from": "07:45", "until": "11:00"}


def test_unquoted_time_without_leading_zero_rejected(tmp_path: Path) -> None:
    """YAML reads 12:30 as the base-60 number 750: the error says to quote it."""
    text = SYMBOLS + (
        "reminders:\n  pre_london: { from: '07:45', until: '11:00' }\n"
        "  pre_ny: { from: 12:30, until: '16:00' }\n"
    )
    assert _problems(tmp_path, text) == [
        'reminders.pre_ny.from: expected a quoted "HH:MM" string, got the number 750'
    ]


def test_alias_equal_to_own_symbol_allowed(tmp_path: Path) -> None:
    text = "symbols:\n  - { symbol: GER40, aliases: [ger40, дакс] }\n" + REMINDERS
    assert load_bias(_write(tmp_path / "bias.yaml", text)).symbols[0].aliases == ("ger40", "дакс")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("symbols: [\n", "YAML syntax error"),
        ("- a\n", "(root): expected a mapping"),
        (REMINDERS, "symbols: Field required"),
        (SYMBOLS, "reminders: Field required"),
        ("symbols: []\n" + REMINDERS, "symbols: Tuple should have at least 1 item"),
        (SYMBOLS + REMINDERS + "extra: 1\n", "extra: Extra inputs are not permitted"),
        (
            "symbols:\n  - { symbol: EURUSD, aliases: [], note: x }\n" + REMINDERS,
            "symbols[0].note: Extra inputs are not permitted",
        ),
        (
            "symbols:\n  - { symbol: EURUSD }\n" + REMINDERS,
            "symbols[0].aliases: Field required",
        ),
        (
            'symbols:\n  - { symbol: "  ", aliases: [] }\n' + REMINDERS,
            "symbols[0].symbol: must not be empty",
        ),
        (
            "symbols:\n  - { symbol: EUR USD, aliases: [] }\n" + REMINDERS,
            "must not contain spaces",
        ),
        (
            "symbols:\n  - { symbol: " + "X" * 51 + ", aliases: [] }\n" + REMINDERS,
            "longer than 50 characters",
        ),
        (
            "symbols:\n  - { symbol: 40, aliases: [] }\n" + REMINDERS,
            "symbols[0].symbol: Input should be a valid string",
        ),
        (
            'symbols:\n  - { symbol: GER40, aliases: [dax, ""] }\n' + REMINDERS,
            "symbols[0].aliases: alias [1] must not be empty",
        ),
        (
            "symbols:\n  - { symbol: GER40, aliases: [40] }\n" + REMINDERS,
            "symbols[0].aliases[0]: Input should be a valid string",
        ),
        (
            "symbols:\n  - { symbol: GER40, aliases: x }\n" + REMINDERS,
            "symbols[0].aliases: Input should be a valid tuple",
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { from: 7:45, until: '11:00' }\n"
            "  pre_ny: { from: '12:30', until: '16:00' }\n",
            'reminders.pre_london.from: expected a quoted "HH:MM" string',
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { from: '7:45', until: '11:00' }\n"
            "  pre_ny: { from: '12:30', until: '16:00' }\n",
            'reminders.pre_london.from: expected time as "HH:MM"',
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { from: '07:45', until: '11:00' }\n"
            "  pre_ny: { from: '16:00', until: '12:30' }\n",
            "reminders.pre_ny: from 16:00 must be before until 12:30",
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { from: '07:45', until: '07:45' }\n"
            "  pre_ny: { from: '12:30', until: '16:00' }\n",
            "reminders.pre_london: from 07:45 must be before until 07:45",
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { from: '07:45', until: '11:00' }\n",
            "reminders.pre_ny: Field required",
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { from: '07:45', until: '11:00' }\n"
            "  pre_ny: { from: '12:30', until: '16:00' }\n"
            "  weekly: { from: '09:00', until: '10:00' }\n",
            "reminders.weekly: Extra inputs are not permitted",
        ),
        (
            SYMBOLS + "reminders:\n  pre_london: { start: '07:45', until: '11:00' }\n"
            "  pre_ny: { from: '12:30', until: '16:00' }\n",
            "reminders.pre_london.start: Extra inputs are not permitted",
        ),
    ],
)
def test_invalid_files(tmp_path: Path, text: str, problem: str) -> None:
    assert any(problem in p for p in _problems(tmp_path, text))


def test_duplicate_symbol_case_insensitive(tmp_path: Path) -> None:
    text = "symbols:\n  - { symbol: GER40, aliases: [] }\n  - { symbol: ger40, aliases: [] }\n"
    assert _problems(tmp_path, text + REMINDERS) == ["symbols[1].symbol: 'ger40' is listed twice"]


def test_symbol_prefix_of_another_rejected(tmp_path: Path) -> None:
    text = "symbols:\n  - { symbol: GER, aliases: [] }\n  - { symbol: GER40, aliases: [] }\n"
    assert _problems(tmp_path, text + REMINDERS) == [
        "symbols[0].symbol: 'GER' is the start of 'GER40' (trades match symbols by prefix)"
    ]


def test_alias_twice_in_one_symbol(tmp_path: Path) -> None:
    text = "symbols:\n  - { symbol: GER40, aliases: [DAX, dax] }\n" + REMINDERS
    assert _problems(tmp_path, text) == ["symbols[0].aliases[1]: 'dax' is listed twice"]


def test_alias_used_by_two_symbols(tmp_path: Path) -> None:
    text = (
        "symbols:\n  - { symbol: EURUSD, aliases: [Євро] }\n"
        "  - { symbol: GBPUSD, aliases: [євро] }\n" + REMINDERS
    )
    assert _problems(tmp_path, text) == ["symbols[1].aliases[0]: 'євро' already means 'EURUSD'"]


def test_alias_equal_to_other_symbol_name(tmp_path: Path) -> None:
    text = (
        "symbols:\n  - { symbol: EURUSD, aliases: [] }\n"
        "  - { symbol: GBPUSD, aliases: [eurusd] }\n" + REMINDERS
    )
    assert _problems(tmp_path, text) == ["symbols[1].aliases[0]: 'eurusd' already means 'EURUSD'"]


def test_mojibake_rejected(tmp_path: Path) -> None:
    garbled = "золото".encode().decode("cp1251")
    text = f"symbols:\n  - {{ symbol: XAUUSD, aliases: [{garbled}] }}\n" + REMINDERS
    with pytest.raises(ConfigError) as info:
        load_bias(_write(tmp_path / "bias.yaml", text))
    assert info.value.reason == REASON_MOJIBAKE


def test_bom_accepted(tmp_path: Path) -> None:
    path = tmp_path / "bias.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + REAL_FILE.read_bytes())
    assert load_bias(path).symbol_names[0] == "EURUSD"


def test_missing_file(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="file not found"):
        get_bias_config()


def test_reloads_when_file_changes(cfg_dir: Path) -> None:
    path = _write(cfg_dir / "bias.yaml", SYMBOLS + REMINDERS)
    assert get_bias_config().symbol_names == ("EURUSD", "GER40")
    _write(path, "symbols:\n  - { symbol: XAUUSD, aliases: [gold] }\n" + REMINDERS)
    later = time.time() + 5
    os.utime(path, (later, later))
    assert get_bias_config().symbol_names == ("XAUUSD",)


def test_check_config_files_reports_bias(cfg_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write(cfg_dir / "bias.yaml", "symbols: 5\n")
    with caplog.at_level(logging.ERROR, logger="app.config_files"):
        errors = check_config_files()
    assert any(e.path.name == "bias.yaml" for e in errors)
    assert "bias.yaml" in caplog.text


# --- GET /api/bias/config ------------------------------------------------------------------


@pytest.fixture
def api() -> Iterator[TestClient]:
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


def test_get_bias_config(api: TestClient) -> None:
    reload_config()
    response = api.get("/api/bias/config")
    assert response.status_code == 200
    body = response.json()
    assert body["symbols"][0] == {
        "symbol": "EURUSD",
        "aliases": ["євро", "евро", "фібер", "fiber", "euro"],
    }
    assert [s["symbol"] for s in body["symbols"]] == ["EURUSD", "GBPUSD", "XAUUSD", "GER40"]
    assert body["reminders"] == {
        "pre_london": {"from": "07:45", "until": "11:00"},
        "pre_ny": {"from": "12:30", "until": "16:00"},
    }
    assert body["kinds"] == ["pre_london", "pre_ny", "weekly", "monthly"]


def test_get_bias_config_broken_file(cfg_dir: Path, api: TestClient) -> None:
    _write(cfg_dir / "bias.yaml", "symbols: [\n")
    response = api.get("/api/bias/config")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "config_error"
    assert body["error"]["details"]["file"] == "bias.yaml"
