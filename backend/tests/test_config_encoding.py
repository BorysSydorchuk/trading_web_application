"""Config files: UTF-8 on a cp1251 Windows locale, UTF-8 BOM, mojibake refused (M3-15)."""

# Mojibake samples are look-alike characters on purpose.
# ruff: noqa: RUF001, RUF003

from __future__ import annotations

import builtins
import io
import logging
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.config_files import ConfigError, check_config_files, get_journal_fields, reload_config
from app.config_files.loader import CONFIG_DIR_ENV, REASON_MOJIBAKE, read_yaml
from app.config_files.mojibake import MAX_REPORTED, mojibake_problems, repair_mojibake
from app.main import create_app

REAL_CONFIG = REPO_ROOT / "config"
CONFIG_NAMES = (
    "rules.yaml",
    "journal_fields.yaml",
    "ai_pricing.yaml",
    "extraction.yaml",
    "transcription.yaml",
)


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A writable copy of the real config dir, active via CONFIG_DIR."""
    for name in CONFIG_NAMES:
        shutil.copy(REAL_CONFIG / name, tmp_path / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def _decode_ansi(raw: bytes, codepage: str) -> str:
    """Decode like Windows does: bytes missing from the code page become U+0080-U+009F."""
    return "".join(_byte_char(bytes([b]), codepage) for b in raw)


def _byte_char(byte: bytes, codepage: str) -> str:
    try:
        return byte.decode(codepage)
    except UnicodeDecodeError:
        return chr(byte[0])


def _powershell_resave(text: str) -> bytes:
    """What `Get-Content -Raw | Set-Content -Encoding utf8` (PowerShell 5.1, cp1251) wrote."""
    return b"\xef\xbb\xbf" + _decode_ansi(text.encode("utf-8"), "cp1251").encode("utf-8")


def _real_labels() -> list[str]:
    config = read_yaml(REAL_CONFIG / "journal_fields.yaml")
    labels: list[str] = []
    for field in config["fields"]:
        labels.append(field["label"])
        labels.extend(option["label"] for option in field.get("options") or [])
    return labels


def _all_real_strings() -> list[str]:
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for name in CONFIG_NAMES:
        walk(read_yaml(REAL_CONFIG / name))
    return strings


# --- detection -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("garbled", "original"),
    [
        ("РўРёРї FVG", "Тип FVG"),  # cp1251 (the M3-15 live-check bug)
        ("Ð¢Ð¸Ð¿", "Тип"),  # latin-1 / cp1252
        ("Ð¢Ð¸Ð¿ FVG", "Тип FVG"),
        (_decode_ansi("Якість сетапу (1–5)".encode(), "cp1251"), "Якість сетапу (1–5)"),
        (
            _decode_ansi("Ідеальний вхід, ґанок, є, ї".encode(), "cp1251"),
            "Ідеальний вхід, ґанок, є, ї",
        ),
        (_decode_ansi("Изменение ИИ".encode(), "cp1251"), "Изменение ИИ"),  # 0x98 byte
        (_decode_ansi("Тип".encode(), "latin-1"), "Тип"),
        ("РїКјСЏС‚СЊ", "пʼять"),
        (_decode_ansi("Ні".encode(), "cp1251"), "Ні"),
        (_decode_ansi("café".encode(), "cp1252"), "café"),
        (_decode_ansi("четвёрка".encode(), "cp1252"), "четвёрка"),
    ],
)
def test_repair_mojibake_detects_garbled_text(garbled: str, original: str) -> None:
    assert repair_mojibake(garbled) == original


@pytest.mark.parametrize(
    "text",
    [
        "Тип FVG",
        "Урок",
        "так",
        "ні",
        "і",
        "П’ятірка",
        "пʼятірка",
        "четвёрка",
        "Привіт, як справи?",
        "Ідеальний вхід — «так» № 5",
        "Ёлка, ЁЖ, ґудзик, Ґанок, їжак, Єва",
        "Съешь же ещё этих мягких французских булок",
        "Чуєш їх, доцю, га? Кумедна ж ти, прощайся без ґольфів!",
        "FVG IFVG QM POI BOS SMT EURUSD",
        "café naïve",
        "✓ 100 %",
        "Ні",
        "НІ",
        "Ці",
        "Ві",
        "Ні, BOS",
        "Так / Ні",
        "В H4",
        "≥ 2R",
        "1–2",
        "П’ять",
        "é",
        "Ü",
        "Über",
        "🚀 FVG",
        "😀",
        "",
    ],
)
def test_repair_mojibake_leaves_real_text_alone(text: str) -> None:
    assert repair_mojibake(text) is None


# cp1251 "Р" (UTF-8 lead 0xD0) + a cp1251 continuation-byte letter decodes to a basic Cyrillic
# letter: the only short real-looking strings still flagged (documented in DECISIONS).
KNOWN_RESIDUAL = {"Р" + c for c in "ЁЄІЇҐёєіїґ"}


def _letter_combos() -> list[str]:
    upper = [chr(c) for c in range(0x0410, 0x0430)] + list("ЁЄІЇҐ")
    lower = [c.lower() for c in upper]
    letters = upper + lower
    return [
        *letters,
        *(a + b for a in letters for b in letters),
        *(a + b + c for a in upper for b in lower for c in lower),
        *(a + b + c for a in upper for b in upper for c in upper),
    ]


def test_no_false_positive_on_short_ukrainian_russian_combos() -> None:
    flagged = {
        variant
        for combo in _letter_combos()
        for variant in (combo, f"{combo}, BOS", f"Так / {combo}")
        if repair_mojibake(variant) is not None
    }
    expected = {v for c in KNOWN_RESIDUAL for v in (c, f"{c}, BOS", f"Так / {c}")}
    assert flagged <= expected  # "Так / Рі" is not flagged: "Так" fails the decode
    assert {c for c in flagged if len(c) == 2} == KNOWN_RESIDUAL


def test_no_false_positive_on_any_real_config_string() -> None:
    strings = _all_real_strings()
    assert len(strings) > 100
    assert [s for s in strings if repair_mojibake(s) is not None] == []


def test_mojibake_problems_name_location_and_cap() -> None:
    data = {"fields": [{"label": f"РўРёРї {i}"} for i in range(MAX_REPORTED + 2)]}
    problems = mojibake_problems(data)
    assert problems[0].startswith("fields[0].label: garbled text 'РўРёРї 0'")
    assert "looks like 'Тип 0'" in problems[0]
    assert problems[MAX_REPORTED] == "... and 2 more garbled strings"
    assert "UTF-8" in problems[-1]
    assert mojibake_problems({"РўРёРї": 1})[0].startswith("РўРёРї (key): ")
    assert mojibake_problems({"fields": [{"label": "Тип FVG"}]}) == []


# --- loading ----------------------------------------------------------------------------------


def test_powershell_resaved_journal_fields_is_refused(cfg_dir: Path) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_bytes(_powershell_resave(path.read_text(encoding="utf-8")))
    with pytest.raises(ConfigError) as info:
        get_journal_fields()
    assert info.value.reason == REASON_MOJIBAKE
    assert info.value.path == path
    assert "journal_fields.yaml" in str(info.value)
    assert "garbled text 'РљРѕРЅС‚РµРєСЃС‚" in str(info.value)


def test_mojibake_in_glossary_is_refused(cfg_dir: Path) -> None:
    path = cfg_dir / "transcription.yaml"
    path.write_text("glossary: [FVG, РўРёРї]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        read_yaml(path)
    assert info.value.reason == REASON_MOJIBAKE
    assert "glossary[1]: garbled text" in str(info.value)


def test_other_config_errors_have_no_reason(cfg_dir: Path) -> None:
    (cfg_dir / "journal_fields.yaml").write_text("fields: [", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        get_journal_fields()
    assert info.value.reason is None


def test_bom_file_loads(cfg_dir: Path) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    labels = [field.label for field in get_journal_fields().fields]
    assert labels == [label for label in _real_labels() if label in labels]
    assert "Урок" in labels


def test_startup_check_logs_mojibake(cfg_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_bytes(_powershell_resave(path.read_text(encoding="utf-8")))
    with caplog.at_level(logging.ERROR, logger="app.config_files"):
        errors = check_config_files()
    assert [e.path.name for e in errors] == ["journal_fields.yaml"]
    assert "CONFIG ERROR" in caplog.text
    assert "garbled text" in caplog.text


def test_api_returns_config_error_with_reason(cfg_dir: Path) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_bytes(_powershell_resave(path.read_text(encoding="utf-8")))
    with TestClient(create_app(), raise_server_exceptions=False) as api:
        response = api.get("/api/journal-fields")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "config_error"
    assert error["details"]["file"] == "journal_fields.yaml"
    assert error["details"]["reason"] == "mojibake"
    assert error["details"]["problems"]


# --- cp1251 locale ----------------------------------------------------------------------------


@pytest.fixture
def cp1251_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text I/O without `encoding=` behaves as on a Ukrainian Windows (ANSI code page 1251).

    CPython takes the locale encoding in C, so `locale` patches would not reach `open()`;
    instead `open`/`io.open` and `io.text_encoding` (used by pathlib) default to cp1251.
    """
    real_open: Callable[..., Any] = builtins.open
    real_text_encoding = io.text_encoding

    def fake_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if "b" not in mode and len(args) < 2 and kwargs.get("encoding") in (None, "locale"):
            kwargs["encoding"] = "cp1251"
        return real_open(file, mode, *args, **kwargs)

    def fake_text_encoding(encoding: str | None, stacklevel: int = 2) -> str:
        if encoding is None:
            return "cp1251"
        return real_text_encoding(encoding, stacklevel)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(io, "open", fake_open)
    monkeypatch.setattr(io, "text_encoding", fake_text_encoding)


@pytest.mark.usefixtures("cp1251_locale")
def test_simulated_locale_really_breaks_reads_without_encoding() -> None:
    path = REAL_CONFIG / "journal_fields.yaml"
    assert "РЈСЂРѕРє" in path.read_text()  # allow-default-encoding: the point of this test
    with open(path) as handle:  # allow-default-encoding: the point of this test
        assert "РЈСЂРѕРє" in handle.read()


@pytest.mark.usefixtures("cp1251_locale")
def test_journal_fields_load_correctly_under_cp1251_locale(cfg_dir: Path) -> None:
    labels = [field.label for field in get_journal_fields().fields]
    assert "Урок" in labels
    assert all(repair_mojibake(label) is None for label in labels)
    assert labels == [label for label in _real_labels() if label in labels]
    assert check_config_files() == []
