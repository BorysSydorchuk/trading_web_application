"""Transcript term normalization: the real config/transcript_glossary.yaml rules and the matcher."""

# Cyrillic letters that look like Latin ones (Н, М, Т, ...) are the point of these tests.
# ruff: noqa: RUF001, RUF003

from __future__ import annotations

from pathlib import Path

import pytest

from app.config_files.transcript_glossary import load_transcript_glossary
from app.domain.transcript_glossary import TranscriptGlossary, normalize_transcript

REAL_FILE = Path(__file__).resolve().parents[3] / "config" / "transcript_glossary.yaml"


@pytest.fixture(scope="module")
def real() -> TranscriptGlossary:
    return load_transcript_glossary(REAL_FILE)


# --- one test per rule of the real file ---------------------------------------------------------


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        # FVG
        ("ФВГ", "FVG"),
        ("фвг", "FVG"),
        ("Фвг", "FVG"),
        # FVG H1 (Whisper's "FVH1" after POI, M3-13)
        ("FVH1", "FVG H1"),
        ("fvh1", "FVG H1"),
        # IFVG
        ("ІФВГ", "IFVG"),
        ("іФВГ", "IFVG"),
        ("ИФВГ", "IFVG"),
        ("ифвг", "IFVG"),
        ("іфввг", "IFVG"),
        # FTA
        ("ФТА", "FTA"),
        ("фта", "FTA"),
        # MT5 (Cyrillic М, Т)
        ("МТ5", "MT5"),
        ("МТ-5", "MT5"),
        ("мт5", "MT5"),
        # Cyrillic timeframes
        ("Н1", "H1"),
        ("н1", "H1"),
        ("Н4", "H4"),
        ("н4", "H4"),
        ("М1", "M1"),
        ("М5", "M5"),
        ("м5", "M5"),
        ("М15", "M15"),
        ("м30", "M30"),
    ],
)
def test_real_rule(real: TranscriptGlossary, spoken: str, expected: str) -> None:
    assert normalize_transcript(f"Вхід по {spoken}, далі.", real) == f"Вхід по {expected}, далі."


@pytest.mark.parametrize(
    "text",
    [
        "Latin H4 H1 M5 M15 FVG IFVG FTA MT5 stay",
        "аж 4, аж один, аж 1",  # real Ukrainian words are never touched
        "ФВГшка, АФВГ, ФВГ2, Н44, М150, 5М5, Н4_",  # inside a longer word/number
        "",
    ],
)
def test_real_rules_leave_text_alone(real: TranscriptGlossary, text: str) -> None:
    assert normalize_transcript(text, real) == text


def test_real_long_note(real: TranscriptGlossary) -> None:
    text = "POI FVH1, далі іфввг на м5 після ФТА (Н4/Н1)."
    assert normalize_transcript(text, real) == "POI FVG H1, далі IFVG на M5 після FTA (H4/H1)."


def test_count_of_replacements(real: TranscriptGlossary) -> None:
    assert real.apply("фвг і ФВГ на Н4") == ("FVG і FVG на H4", 3)
    assert real.apply("нічого") == ("нічого", 0)


# --- matcher rules ------------------------------------------------------------------------------


def _g(*pairs: tuple[str, list[str]]) -> TranscriptGlossary:
    return TranscriptGlossary.from_pairs(pairs)


@pytest.mark.parametrize(
    "text",
    ["(ФВГ)", "«ФВГ»", "ФВГ.", "ФВГ!", "ФВГ-ка", '"ФВГ"', "ФВГ\nдалі", "ФВГ/ФВГ"],
)
def test_punctuation_counts_as_boundary(text: str) -> None:
    out = normalize_transcript(text, _g(("FVG", ["ФВГ"])))
    assert "ФВГ" not in out
    assert "FVG" in out


@pytest.mark.parametrize("text", ["xФВГ", "ФВГx", "1ФВГ", "ФВГ1", "_ФВГ", "ФВГ_", "яФВГ", "ФВГї"])
def test_letters_digits_underscore_are_not_boundaries(text: str) -> None:
    assert normalize_transcript(text, _g(("FVG", ["ФВГ"]))) == text


def test_longest_from_wins_regardless_of_file_order() -> None:
    glossary = _g(("FVG", ["ФВГ"]), ("FVG H1", ["ФВГ Н1"]), ("H1", ["Н1"]))
    assert normalize_transcript("ФВГ Н1 і ФВГ і Н1", glossary) == "FVG H1 і FVG і H1"


def test_single_pass_never_rematches_replaced_text() -> None:
    glossary = _g(("B", ["A"]), ("C", ["B"]))
    assert normalize_transcript("A B", glossary) == "B C"


def test_to_is_inserted_as_written() -> None:
    glossary = _g(("iFVG-x", ["ифвг"]))
    assert normalize_transcript("ИФВГ", glossary) == "iFVG-x"


def test_cyrillic_and_latin_lookalikes_are_different_letters() -> None:
    glossary = _g(("H4", ["Н4"]))  # Cyrillic Н
    assert normalize_transcript("H4 Н4", glossary) == "H4 H4"
    latin = _g(("X", ["H4"]))  # Latin H
    assert normalize_transcript("Н4", latin) == "Н4"


def test_regex_characters_are_literal() -> None:
    glossary = _g(("ok", ["a.b"]))
    assert normalize_transcript("a.b axb", glossary) == "ok axb"


def test_empty_glossary_changes_nothing() -> None:
    assert TranscriptGlossary(()).apply("ФВГ") == ("ФВГ", 0)
