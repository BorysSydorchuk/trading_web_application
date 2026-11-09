"""config/extraction.yaml loader: number words for the int guard (docs/api.md M3 "Number words")."""

# ruff: noqa: RUF001 - Ukrainian/Russian sample words

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.config_files import ConfigError, check_config_files, get_number_words, reload_config
from app.config_files.extraction import load_number_words
from app.config_files.loader import CONFIG_DIR_ENV
from app.domain.number_words import number_in_evidence

REAL_CONFIG = REPO_ROOT / "config"
CONFIG_FILES = (
    "rules.yaml",
    "journal_fields.yaml",
    "ai_pricing.yaml",
    "extraction.yaml",
    "transcription.yaml",
    "transcript_glossary.yaml",
    "bias.yaml",
)

# The list that was hardcoded as NUMBER_WORDS in app/domain/extraction.py before M3-02,
# plus the accusative forms ("на трійку", M4-06 review).
M2_NUMBER_WORDS = {
    **dict.fromkeys(("один", "одна", "одиниця", "единица", "единичка", "one"), 1),
    **dict.fromkeys(("два", "дві", "двійка", "двойка", "two"), 2),
    **dict.fromkeys(("три", "трійка", "тройка", "three"), 3),
    **dict.fromkeys(("чотири", "четыре", "четвірка", "четверка", "four"), 4),
    **dict.fromkeys(("п'ять", "пять", "п'ятірка", "пятерка", "five"), 5),
}
ACCUSATIVE_NUMBER_WORDS = {
    **dict.fromkeys(("одиницю", "единицу", "единичку"), 1),
    **dict.fromkeys(("двійку", "двойку"), 2),
    **dict.fromkeys(("трійку", "тройку"), 3),
    **dict.fromkeys(("четвірку", "четверку"), 4),
    **dict.fromkeys(("п'ятірку", "пятерку"), 5),
}
# M5 (PM 2026-11-09, bias confidence words): UA diminutive, like RU "единичка".
DIMINUTIVE_NUMBER_WORDS = dict.fromkeys(("одиничка", "одиничку"), 1)


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A writable copy of the real config dir, active via CONFIG_DIR."""
    for name in CONFIG_FILES:
        shutil.copy(REAL_CONFIG / name, tmp_path / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def _write(cfg_dir: Path, content: str) -> Path:
    path = cfg_dir / "extraction.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _error(cfg_dir: Path, content: str) -> str:
    with pytest.raises(ConfigError) as info:
        load_number_words(_write(cfg_dir, content))
    return str(info.value)


def test_real_file_is_the_m2_list_plus_accusative_forms() -> None:
    words = dict(load_number_words(REAL_CONFIG / "extraction.yaml").words)
    assert words == M2_NUMBER_WORDS | ACCUSATIVE_NUMBER_WORDS | DIMINUTIVE_NUMBER_WORDS


def test_words_are_normalised_on_load(cfg_dir: Path) -> None:
    path = _write(cfg_dir, "number_words:\n  4: [Четвёрка, '  ЧЕТВІРОЧКА ']\n  5: [П’ятірка]\n")
    words = load_number_words(path)
    assert dict(words.words) == {"четверка": 4, "четвірочка": 4, "п'ятірка": 5}
    assert number_in_evidence(4, "чесна четвёрка", words)
    assert number_in_evidence(5, "п'ятірка", words)


def test_same_word_twice_for_one_number_is_fine(cfg_dir: Path) -> None:
    path = _write(cfg_dir, "number_words:\n  4: [четверка, четвёрка, Четверка]\n")
    assert dict(load_number_words(path).words) == {"четверка": 4}


def test_word_added_by_borys_works_without_code_changes(cfg_dir: Path) -> None:
    assert not number_in_evidence(4, "майже ідеал", get_number_words())
    path = cfg_dir / "extraction.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("  4: [", "  4: [майже ідеал, "),
        encoding="utf-8",
    )
    assert number_in_evidence(4, "Сетап майже ідеал", get_number_words())  # reloaded on change
    assert number_in_evidence(4, "четвірка", get_number_words())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("number_words:\n  '4': [four]\n", "[key]: Input should be a valid integer"),
        ("number_words:\n  true: [yes]\n", "Input should be a valid integer"),
        ("number_words:\n  -1: [minus]\n", "greater than or equal to 0"),
        ("number_words:\n  4: []\n", "number_words[4]: List should have at least 1 item"),
        ("number_words:\n  4: ['']\n", "at least 1 character"),
        ("number_words:\n  4: [123]\n", "number_words[4][0]: Input should be a valid string"),
        ("number_words:\n  4: four\n", "number_words[4]: Input should be a valid list"),
        ("number_words:\n  4: ['...']\n", "'...' has no letters"),
        ("number_words:\n  4: [four]\n  5: [Four]\n", "'Four' already means 4"),
        ("number_words:\n  4: [четвёрка]\n  5: [четверка]\n", "'четверка' already means 4"),
        ("number_words:\n  4: [four]\nextra: 1\n", "extra: Extra inputs are not permitted"),
        ("{}\n", "number_words: Field required"),
        ("- four\n", "expected a mapping"),
        ("number_words: [\n", "YAML syntax error"),
        ("number_words:\n  4: [four]\n  4: [chetyre]\n", "duplicate key 4"),
    ],
)
def test_invalid_file_is_a_config_error(cfg_dir: Path, content: str, message: str) -> None:
    error = _error(cfg_dir, content)
    assert "extraction.yaml" in error
    assert message in error


def test_missing_file_is_a_config_error(cfg_dir: Path) -> None:
    (cfg_dir / "extraction.yaml").unlink()
    with pytest.raises(ConfigError, match="file not found"):
        get_number_words()


def test_fixed_file_is_picked_up_without_restart(cfg_dir: Path) -> None:
    _write(cfg_dir, "number_words: [\n")
    with pytest.raises(ConfigError):
        get_number_words()
    _write(cfg_dir, "number_words:\n  4: [four]\n")
    assert dict(get_number_words().words) == {"four": 4}


def test_check_config_files_includes_extraction(
    cfg_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write(cfg_dir, "number_words: nope\n")
    with caplog.at_level(logging.ERROR, logger="app.config_files"):
        errors = check_config_files()
    assert [e.path.name for e in errors] == ["extraction.yaml"]
    assert "CONFIG ERROR" in caplog.text
