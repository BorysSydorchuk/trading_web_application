"""config/transcript_glossary.yaml: strict validation, reload on change, startup check."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config_files import ConfigError, check_config_files, reload_config
from app.config_files.loader import CONFIG_DIR_ENV, REASON_MOJIBAKE
from app.config_files.transcript_glossary import (
    MAX_RULES,
    get_transcript_glossary,
    load_transcript_glossary,
)
from app.domain.transcript_glossary import normalize_transcript

REAL_FILE = Path(__file__).resolve().parents[2] / "config" / "transcript_glossary.yaml"


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, text: str) -> object:
    return load_transcript_glossary(_write(tmp_path / "g.yaml", text))


def test_real_file_is_utf8_without_bom_and_loads() -> None:
    assert not REAL_FILE.read_bytes().startswith(b"\xef\xbb\xbf")
    glossary = load_transcript_glossary(REAL_FILE)
    targets = {rule.to for rule in glossary.rules}
    assert {"FVG", "FVG H1", "IFVG", "H4", "H1", "M5", "FTA"} <= targets


def test_values_are_stripped_and_case_variants_allowed(tmp_path: Path) -> None:
    glossary = load_transcript_glossary(
        _write(tmp_path / "g.yaml", "replacements:\n  - {to: ' FVG ', from: [' ФВГ', фвг]}\n")
    )
    assert normalize_transcript("фвг", glossary) == "FVG"


def test_empty_list_is_valid(tmp_path: Path) -> None:
    glossary = load_transcript_glossary(_write(tmp_path / "g.yaml", "replacements: []\n"))
    assert glossary.apply("ФВГ") == ("ФВГ", 0)


def test_bom_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "g.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + "replacements:\n  - {to: FVG, from: [ФВГ]}\n".encode())
    assert normalize_transcript("ФВГ", load_transcript_glossary(path)) == "FVG"


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("replacements:\n  - {to: '  ', from: [ФВГ]}\n", "replacements[0].to: must not be empty"),
        ("replacements:\n  - {to: FVG, from: []}\n", "replacements[0].from"),
        ("replacements:\n  - {to: FVG, from: ['  ']}\n", "from[0]: must not be empty"),
        ("replacements:\n  - {to: FVG, from: ['--']}\n", "has no letter or digit"),
        ("replacements:\n  - {to: FVG, from: [ФВГ, ФВГ]}\n", "from[1]: 'ФВГ' is listed twice"),
        (
            "replacements:\n  - {to: FVG, from: [ФВГ]}\n  - {to: IFVG, from: [фвг]}\n",
            "replacements[1].from[0]: 'фвг' already maps to 'FVG'",
        ),
        ("replacements:\n  - {to: FVG}\n", "replacements[0].from"),
        ("replacements:\n  - {from: [ФВГ]}\n", "replacements[0].to"),
        ("replacements:\n  - {to: 5, from: [ФВГ]}\n", "replacements[0].to"),
        ("replacements:\n  - {to: FVG, from: [5]}\n", "replacements[0].from[0]"),
        ("replacements:\n  - {to: FVG, from: ФВГ}\n", "replacements[0].from"),
        ("replacements:\n  - {to: FVG, from: [ФВГ], x: 1}\n", "replacements[0].x"),
        ("replacements: []\nextra: 1\n", "extra"),
        ("{}\n", "replacements"),
        ("- FVG\n", "expected a mapping"),
        ("replacements: [\n", "YAML syntax error"),
    ],
)
def test_invalid_files(tmp_path: Path, text: str, problem: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(problem)):
        _load(tmp_path, text)


def test_too_many_rules(tmp_path: Path) -> None:
    rules = "".join(f"  - {{to: T{i}, from: [x{i}]}}\n" for i in range(MAX_RULES + 1))
    with pytest.raises(ConfigError, match="replacements"):
        _load(tmp_path, "replacements:\n" + rules)
    _load(tmp_path, "replacements:\n" + rules.split("\n", 1)[1])  # exactly MAX_RULES is fine


def test_mojibake_is_refused(tmp_path: Path) -> None:
    garbled = "ФВГ".encode().decode("cp1251")
    with pytest.raises(ConfigError) as info:
        _load(tmp_path, f"replacements:\n  - {{to: FVG, from: [ІФВГ, '{garbled}']}}\n")
    assert info.value.reason == REASON_MOJIBAKE


def test_missing_file(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="file not found"):
        get_transcript_glossary()


def test_reloads_on_change(cfg_dir: Path) -> None:
    path = _write(cfg_dir / "transcript_glossary.yaml", "replacements: []\n")
    assert get_transcript_glossary().rules == ()
    _write(path, "replacements:\n  - {to: FVG, from: [ФВГ]}\n")
    stamp = time.time() + 5
    os.utime(path, (stamp, stamp))
    assert normalize_transcript("ФВГ", get_transcript_glossary()) == "FVG"


def test_check_config_files_reports_broken_glossary(
    cfg_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(cfg_dir / "transcript_glossary.yaml", "replacements: 5\n")
    with caplog.at_level(logging.ERROR):
        errors = check_config_files()
    assert any(e.path.name == "transcript_glossary.yaml" for e in errors)
    assert "transcript_glossary.yaml" in caplog.text
