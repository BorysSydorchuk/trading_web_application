"""Extraction guards: int values as standalone numbers / number words, evidence length, ё."""

# ruff: noqa: RUF001, RUF003 - Ukrainian/Russian sample texts

from __future__ import annotations

import pytest

from app.config_files import JournalFieldsConfig, get_journal_fields
from app.domain.extraction import (
    Dropped,
    apply_guards,
    evidence_in_text,
    normalise_for_match,
    number_in_evidence,
)


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


# --- G1: the number must be a standalone token ---


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        (5, "вхід по IFVG M5"),  # glued to a letter
        (4, "FVG H4"),
        (4, "4H FVG"),
        (5, "якість 4.5"),  # part of a decimal
        (4, "якість 4.5"),
        (5, "якість 4,5"),
        (5, "сетап на 4 из 5"),  # denominator
        (5, "сетап на 4 з 5"),
        (5, "сетап на 4 із 5"),
        (5, "setup 4 of 5"),
        (5, "setup 4 out of 5"),
        (5, "сетап 4/5"),
        (5, "сетап 4 / 5"),
        (1, "ризик 14 пунктів"),
        (4, "ризик 14 пунктів"),
        (3, "п'ятихвилинка"),
        (1, "ризик 1%"),  # percent, money, clock time
        (5, "о 9:05"),
        (9, "о 9:05"),
        (5, "$5"),
        (5, "5€"),
        (5, "£5"),
        (5, "5$"),
        (14, "14:30"),
        (30, "14:30"),
        (4, "оцінка 4-5"),  # a range is ambiguous: neither end counts
        (5, "оцінка 4-5"),
        (4, "оцінка 4–5"),
        (5, "оцінка 4—5"),
    ],
)
def test_number_not_standalone_is_rejected(value: int, evidence: str) -> None:
    assert not number_in_evidence(value, evidence)


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        (4, "сетап на 4 из 5"),
        (4, "сетап 4/5"),
        (4, "setup 4 out of 5"),
        (4, "якість 4."),
        (4, "якість: 4, нормально"),
        (3, "(3)"),
        (5, "оцінка 5"),
        (2, "2 бали"),
    ],
)
def test_standalone_number_is_accepted(value: int, evidence: str) -> None:
    assert number_in_evidence(value, evidence)


# --- number words (1-5) ---


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        (4, "чесна четвірка"),
        (4, "Четверка"),
        (4, "чотири з п'яти"),
        (4, "четвёрка"),
        (5, "п'ятірка"),
        (5, "пʼять"),
        (5, "пятерка"),
        (5, "пять"),
        (1, "одиниця"),
        (1, "единичка"),
        (2, "дві"),
        (2, "двойка"),
        (3, "трійка"),
        (3, "Three"),
        (5, "five out of five"),
        (5, "‘п’ять’"),  # in single quotes, inner apostrophe kept
        (5, "'п'ять'"),
        (4, "'чотири'"),
        (4, "оцінка-4"),  # a hyphen after a word is not a range
    ],
)
def test_number_words_count_as_the_number(value: int, evidence: str) -> None:
    assert number_in_evidence(value, evidence)


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        (4, "четвірками"),  # not a whole word from the list
        (3, "тривога"),
        (1, "someone"),
        (5, "чотири з п'яти"),  # denominator in words
        (2, "три"),
        (6, "шість"),  # outside the closed 1-5 list
    ],
)
def test_other_words_do_not_count(value: int, evidence: str) -> None:
    assert not number_in_evidence(value, evidence)


def test_rating_from_glued_token_is_dropped(config: JournalFieldsConfig) -> None:
    text = "Вхід по IFVG M5, POI FVG H4."
    for value, evidence in ((5, "IFVG M5"), (4, "FVG H4")):
        result = apply_guards(
            config, {"quality_rating": {"value": value, "evidence": evidence}}, text
        )
        assert result.dropped == [Dropped("quality_rating", "evidence_not_in_text")]


def test_rating_in_words_is_kept(config: JournalFieldsConfig) -> None:
    text = "Сетап ідеальний, чесна четвірка."
    output = {"quality_rating": {"value": 4, "evidence": "чесна четвірка"}}
    assert apply_guards(config, output, text).fields == {"quality_rating": 4}


# --- G2: minimum counts letters and digits only ---


@pytest.mark.parametrize("evidence", ["TP.", " по,", "SL!!", "a . b", "4 /", "..."])
def test_evidence_needs_three_letters_or_digits(evidence: str) -> None:
    text = normalise_for_match("Закрив по TP. Потім по, SL!! a . b 4 / ...")
    assert not evidence_in_text(evidence, text)


@pytest.mark.parametrize("evidence", ["по TP", "SL!! a", "TP. Потім"])
def test_evidence_with_three_letters_or_digits_is_accepted(evidence: str) -> None:
    text = normalise_for_match("Закрив по TP. Потім по, SL!! a . b")
    assert evidence_in_text(evidence, text)


# --- G3: ё is folded to е ---


def test_yo_is_folded() -> None:
    assert normalise_for_match("Всё ЁЛКА") == "все елка"
    assert evidence_in_text("всё по плану", normalise_for_match("Все по плану"))
    assert evidence_in_text("все по плану", normalise_for_match("Всё по плану"))
