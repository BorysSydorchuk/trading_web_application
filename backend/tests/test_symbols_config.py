"""config/symbols.yaml: canonical symbol names and broker names (docs/api.md M5-08).

Loader like bias.yaml: strict, UTF-8, mojibake refused, reloaded on change, checked at
API/worker start together with the bias.yaml cross-check (bias symbols must be canonical).
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.config_files import (
    ConfigError,
    SymbolsConfig,
    check_config_files,
    get_bias_config,
    get_symbols_config,
    reload_config,
)
from app.config_files.loader import CONFIG_DIR_ENV, REASON_MOJIBAKE
from app.config_files.symbols import SYMBOLS_FILE, load_symbols
from app.main import create_app

REAL_CONFIG = REPO_ROOT / "config"
REAL_FILE = REAL_CONFIG / "symbols.yaml"

VALID = """
symbols:
  - { name: EURUSD }
  - { name: GER40, broker_names: [GER30, GER40.cash, DE40] }
firms:
  FundedNext: { GER40: [GER30] }
"""


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A writable copy of the whole real config dir, active via CONFIG_DIR."""
    target = tmp_path / "config"
    shutil.copytree(REAL_CONFIG, target)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(target))
    reload_config()
    yield target
    reload_config()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, text: str) -> SymbolsConfig:
    return load_symbols(_write(tmp_path / SYMBOLS_FILE, text))


def _problems(tmp_path: Path, text: str) -> list[str]:
    with pytest.raises(ConfigError) as info:
        _load(tmp_path, text)
    return info.value.problems


def _mentions(problems: list[str], *words: str) -> bool:
    return any(all(word in problem for word in words) for problem in problems)


# --- valid files ---------------------------------------------------------------------------


def test_file_name() -> None:
    assert SYMBOLS_FILE == "symbols.yaml"


def test_real_file_matches_contract() -> None:
    config = load_symbols(REAL_FILE)
    assert config.names == ("EURUSD", "GBPUSD", "XAUUSD", "GER40")
    ger40 = config.symbols[3]
    assert ger40.name == "GER40"
    assert ger40.broker_names == ("GER30", "GER40.cash", "DE40")
    assert config.symbols[0].broker_names == ()
    assert config.firms == {"FundedNext": {"GER40": ("GER30",)}}


def test_valid_file_keeps_order_and_strips_values(tmp_path: Path) -> None:
    text = (
        'symbols:\n  - { name: " XAUUSD " }\n'
        '  - { name: GER40, broker_names: [" GER30 ", DE40] }\n'
        "  - { name: EURUSD }\n"
    )
    config = _load(tmp_path, text)
    assert config.names == ("XAUUSD", "GER40", "EURUSD")
    assert config.symbols[1].broker_names == ("GER30", "DE40")
    assert config.firms == {}  # optional


def test_firm_override_may_repeat_own_broker_names(tmp_path: Path) -> None:
    config = _load(tmp_path, VALID)
    assert config.firms["FundedNext"]["GER40"] == ("GER30",)


def test_firm_override_may_name_a_new_broker_name(tmp_path: Path) -> None:
    text = (
        "symbols:\n  - { name: GER40, broker_names: [GER30] }\nfirms:\n  FTMO: { GER40: [DAX40] }\n"
    )
    assert _load(tmp_path, text).firms == {"FTMO": {"GER40": ("DAX40",)}}


def test_suffix_of_own_name_allowed(tmp_path: Path) -> None:
    """GER40 is the start of GER40.cash, but both belong to the same symbol."""
    text = "symbols:\n  - { name: GER40, broker_names: [GER40.cash] }\n"
    assert _load(tmp_path, text).symbols[0].broker_names == ("GER40.cash",)


def test_bom_accepted(tmp_path: Path) -> None:
    path = tmp_path / SYMBOLS_FILE
    path.write_bytes(b"\xef\xbb\xbf" + REAL_FILE.read_bytes())
    assert load_symbols(path).names[0] == "EURUSD"


# --- invalid files -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("symbols: [\n", "YAML syntax error"),
        ("- a\n", "(root)"),
        ("firms: {}\n", "symbols"),
        ("symbols: []\n", "symbols"),
        ("symbols:\n  - { name: EURUSD }\nextra: 1\n", "extra"),
        ("symbols:\n  - { name: EURUSD, note: x }\n", "note"),
        ("symbols:\n  - { broker_names: [GER30] }\n", "name"),
        ('symbols:\n  - { name: "  " }\n', "must not be empty"),
        ("symbols:\n  - { name: EUR USD }\n", "must not contain spaces"),
        ("symbols:\n  - { name: " + "X" * 51 + " }\n", "longer than 50 characters"),
        ("symbols:\n  - { name: 40 }\n", "valid string"),
        ('symbols:\n  - { name: GER40, broker_names: [GER30, ""] }\n', "must not be empty"),
        ("symbols:\n  - { name: GER40, broker_names: [GER 30] }\n", "must not contain spaces"),
        ("symbols:\n  - { name: GER40, broker_names: GER30 }\n", "broker_names"),
        ("symbols:\n  - { name: GER40 }\nfirms:\n  FundedNext: { GER40: [] }\n", "FundedNext"),
        ("symbols:\n  - { name: GER40 }\nfirms:\n  FundedNext: [GER30]\n", "FundedNext"),
    ],
)
def test_invalid_files(tmp_path: Path, text: str, problem: str) -> None:
    assert _mentions(_problems(tmp_path, text), problem)


@pytest.mark.parametrize(
    "text",
    [
        "symbols:\n  - { name: GER40 }\n  - { name: ger40 }\n",
        "symbols:\n  - { name: GER40, broker_names: [GER30, ger30] }\n",
        "symbols:\n  - { name: GER40, broker_names: [GER40] }\n",
        "symbols:\n  - { name: GER40, broker_names: [GER30] }\n  - { name: ger30 }\n",
        (
            "symbols:\n  - { name: GER40, broker_names: [GER30] }\n"
            "  - { name: DAX, broker_names: [Ger30] }\n"
        ),
    ],
)
def test_duplicate_names_case_insensitive(tmp_path: Path, text: str) -> None:
    problems = _problems(tmp_path, text)
    assert problems
    assert _mentions(problems, "twice") or _mentions(problems, "already")


@pytest.mark.parametrize(
    ("text", "start", "longer"),
    [
        ("symbols:\n  - { name: GER }\n  - { name: GER40 }\n", "GER", "GER40"),
        (
            "symbols:\n  - { name: GER40, broker_names: [DE40] }\n  - { name: DE40X }\n",
            "DE40",
            "DE40X",
        ),
        (
            "symbols:\n  - { name: EURUSD }\n  - { name: XAUUSD, broker_names: [EURUSD.gold] }\n",
            "EURUSD",
            "EURUSD.gold",
        ),
    ],
)
def test_prefix_of_another_symbol_rejected(
    tmp_path: Path, text: str, start: str, longer: str
) -> None:
    assert _mentions(_problems(tmp_path, text), repr(start), repr(longer))


def test_firm_override_name_counts_for_prefix_conflicts(tmp_path: Path) -> None:
    text = (
        "symbols:\n  - { name: EURUSD }\n  - { name: GER40 }\n"
        "firms:\n  FTMO: { GER40: [EURUSD.dax] }\n"
    )
    assert _mentions(_problems(tmp_path, text), "'EURUSD'", "'EURUSD.dax'")


def test_firm_override_cannot_take_another_symbols_broker_name(tmp_path: Path) -> None:
    text = (
        "symbols:\n  - { name: EURUSD }\n  - { name: GER40, broker_names: [GER30] }\n"
        "firms:\n  FundedNext: { EURUSD: [GER30] }\n"
    )
    assert _mentions(_problems(tmp_path, text), "GER30")


def test_firm_override_must_name_a_known_symbol(tmp_path: Path) -> None:
    text = "symbols:\n  - { name: GER40 }\nfirms:\n  FundedNext: { DAX: [GER30] }\n"
    assert _mentions(_problems(tmp_path, text), "FundedNext", "DAX")


def test_firm_names_unique_case_insensitive(tmp_path: Path) -> None:
    text = (
        "symbols:\n  - { name: GER40, broker_names: [GER30] }\n"
        "firms:\n  FundedNext: { GER40: [GER30] }\n  fundednext: { GER40: [GER40] }\n"
    )
    assert _mentions(_problems(tmp_path, text), "fundednext")


def test_mojibake_rejected(tmp_path: Path) -> None:
    garbled = "дакс".encode().decode("cp1251")
    text = f"symbols:\n  - {{ name: GER40, broker_names: [{garbled}] }}\n"
    with pytest.raises(ConfigError) as info:
        _load(tmp_path, text)
    assert info.value.reason == REASON_MOJIBAKE


def test_model_validate_runs_the_same_checks() -> None:
    """Tests build configs in code: SymbolsConfig.model_validate is fully validated too."""
    with pytest.raises(ValueError, match="GER"):
        SymbolsConfig.model_validate({"symbols": [{"name": "GER"}, {"name": "GER40"}]})
    config = SymbolsConfig.model_validate(
        {"symbols": [{"name": "GER40", "broker_names": ["GER30"]}]}
    )
    assert config.names == ("GER40",)


# --- cached accessor, reload, startup check -------------------------------------------------


def test_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    try:
        with pytest.raises(ConfigError, match="file not found"):
            get_symbols_config()
    finally:
        reload_config()


def test_reloads_when_file_changes(cfg_dir: Path) -> None:
    assert get_symbols_config().names == ("EURUSD", "GBPUSD", "XAUUSD", "GER40")
    path = _write(cfg_dir / SYMBOLS_FILE, "symbols:\n  - { name: XAUUSD }\n")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert get_symbols_config().names == ("XAUUSD",)


def test_reload_config_clears_the_cache(cfg_dir: Path) -> None:
    first = get_symbols_config()
    reload_config()
    assert get_symbols_config() == first


def test_real_config_dir_passes_the_startup_check(cfg_dir: Path) -> None:
    assert check_config_files() == []


def test_check_config_files_reports_symbols(
    cfg_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(cfg_dir / SYMBOLS_FILE, "symbols: 5\n")
    with caplog.at_level(logging.ERROR, logger="app.config_files"):
        errors = check_config_files()
    assert [e.path.name for e in errors] == ["symbols.yaml"]
    assert "CONFIG ERROR" in caplog.text
    assert "symbols.yaml" in caplog.text


def test_bias_symbol_must_be_a_canonical_name(
    cfg_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bias = cfg_dir / "bias.yaml"
    _write(bias, bias.read_text(encoding="utf-8").replace("symbol: GER40,", "symbol: GER30,"))
    with caplog.at_level(logging.ERROR, logger="app.config_files"):
        errors = check_config_files()
    assert len(errors) == 1
    (error,) = errors
    assert error.path.name == "bias.yaml"
    assert _mentions(error.problems, "GER30", "symbols.yaml")
    assert "GER30" in caplog.text


def test_bias_cross_check_skipped_when_symbols_file_is_broken(cfg_dir: Path) -> None:
    """One broken file is one error: the bias check needs a valid symbols.yaml."""
    _write(cfg_dir / SYMBOLS_FILE, "symbols: [\n")
    errors = check_config_files()
    assert [e.path.name for e in errors] == ["symbols.yaml"]


def test_symbols_yaml_listed_in_package_exports() -> None:
    import app.config_files as package

    assert {"SymbolsConfig", "get_symbols_config"} <= set(package.__all__)


# --- review fixes ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        "{ GER40: [GER30], ger40: [DE40] }",
        '{ GER40: [GER30], " GER40 ": [DE40] }',
    ],
)
def test_same_symbol_twice_in_one_firm_override(tmp_path: Path, overrides: str) -> None:
    text = (
        "symbols:\n  - { name: GER40, broker_names: [GER30, DE40] }\n"
        f"firms:\n  FundedNext: {overrides}\n"
    )
    assert _mentions(_problems(tmp_path, text), "FundedNext", "twice")


# YAML double-quoted escapes (raw strings): the reader itself refuses raw control characters.
@pytest.mark.parametrize("name", [r'"GER\u200b40"', r'"EUR\u0007USD"', r'"GER\u00a040"'])
def test_non_printable_name_rejected(tmp_path: Path, name: str) -> None:
    for text in (
        f"symbols:\n  - {{ name: {name} }}\n",
        f"symbols:\n  - {{ name: GER40, broker_names: [{name}] }}\n",
    ):
        assert _mentions(_problems(tmp_path, text), "printable")


def test_test_fixture_yaml_matches_the_test_config(tmp_path: Path) -> None:
    from tests.symbols_fixture import TEST_SYMBOLS, TEST_SYMBOLS_YAML

    assert _load(tmp_path, TEST_SYMBOLS_YAML) == TEST_SYMBOLS


def _touch(path: Path) -> None:
    later = time.time() + 5
    os.utime(path, (later, later))


def test_runtime_bias_edit_to_a_non_canonical_symbol_is_a_config_error(cfg_dir: Path) -> None:
    """The bias ⊆ symbols check also runs when bias.yaml is read at runtime, not only at start."""
    assert "GER40" in get_bias_config().symbol_names
    bias = cfg_dir / "bias.yaml"
    _write(bias, bias.read_text(encoding="utf-8").replace("symbol: GER40,", "symbol: GER30,"))
    _touch(bias)

    with pytest.raises(ConfigError) as info:
        get_bias_config()
    assert info.value.path.name == "bias.yaml"
    assert _mentions(info.value.problems, "GER30", "symbols.yaml")


def test_runtime_symbols_edit_dropping_a_bias_symbol_is_a_config_error(cfg_dir: Path) -> None:
    get_bias_config()
    _write(cfg_dir / SYMBOLS_FILE, "symbols:\n  - { name: EURUSD }\n  - { name: GBPUSD }\n")
    _touch(cfg_dir / SYMBOLS_FILE)

    with pytest.raises(ConfigError) as info:
        get_bias_config()
    assert info.value.path.name == "bias.yaml"
    assert _mentions(info.value.problems, "XAUUSD")


def test_runtime_bias_edit_gives_500_config_error_in_the_api(cfg_dir: Path) -> None:
    bias = cfg_dir / "bias.yaml"
    _write(bias, bias.read_text(encoding="utf-8").replace("symbol: GER40,", "symbol: GER30,"))
    _touch(bias)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/api/bias/config")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "config_error"
    assert error["details"]["file"] == "bias.yaml"


def test_alignment_settings_refuse_a_non_canonical_bias_symbol(cfg_dir: Path) -> None:
    from app.services.bias_alignment import alignment_settings

    bias = cfg_dir / "bias.yaml"
    _write(bias, bias.read_text(encoding="utf-8").replace("symbol: GER40,", "symbol: GER30,"))
    _touch(bias)

    with pytest.raises(ConfigError):
        alignment_settings()


def test_bias_check_skipped_while_symbols_yaml_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """symbols.yaml reports its own error; bias.yaml alone still loads."""
    shutil.copy(REAL_CONFIG / "bias.yaml", tmp_path / "bias.yaml")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    try:
        assert get_bias_config().symbol_names[0] == "EURUSD"
    finally:
        reload_config()
