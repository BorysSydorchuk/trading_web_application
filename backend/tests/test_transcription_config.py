"""config/transcription.yaml: strict validation, prompt, reload on change."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config_files import ConfigError, reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.config_files.transcription import (
    PROMPT_PREFIX,
    get_transcription,
    load_transcription,
)

REAL_FILE = Path(__file__).resolve().parents[2] / "config" / "transcription.yaml"


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_real_file_loads_with_glossary() -> None:
    config = load_transcription(REAL_FILE)
    for term in ("FVG", "IFVG", "QM", "POI", "BOS", "SMT", "Flow", "фрактал", "точка B"):
        assert term in config.glossary
    prompt = config.initial_prompt()
    assert prompt is not None
    assert prompt.startswith(PROMPT_PREFIX + "FVG, IFVG, ")
    assert prompt.endswith("GBPUSD.")


def test_empty_glossary_gives_no_prompt(tmp_path: Path) -> None:
    config = load_transcription(_write(tmp_path / "t.yaml", "glossary: []\n"))
    assert config.initial_prompt() is None


def test_terms_are_stripped(tmp_path: Path) -> None:
    config = load_transcription(_write(tmp_path / "t.yaml", "glossary: ['  FVG ']\n"))
    assert config.glossary == ["FVG"]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("glossary: [FVG, fvg]\n", "listed twice"),
        ("glossary: ['  ']\n", "must not be empty"),
        ("glossary: [" + "x" * 41 + "]\n", "longer than 40"),
        ("glossary: [5]\n", "glossary[0]"),
        ("glossary: FVG\n", "glossary"),
        ("glossary: [FVG]\nextra: 1\n", "extra"),
        ("{}\n", "glossary"),
        ("- FVG\n", "expected a mapping"),
        ("glossary: [\n", "YAML syntax error"),
    ],
)
def test_invalid_files(tmp_path: Path, text: str, problem: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(problem)):
        load_transcription(_write(tmp_path / "t.yaml", text))


def test_missing_file(cfg_dir: Path) -> None:
    with pytest.raises(ConfigError, match="file not found"):
        get_transcription()


def test_reloads_when_file_changes(cfg_dir: Path) -> None:
    path = _write(cfg_dir / "transcription.yaml", "glossary: [FVG]\n")
    assert get_transcription().glossary == ["FVG"]
    _write(path, "glossary: [FVG, POI]\n")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert get_transcription().glossary == ["FVG", "POI"]
