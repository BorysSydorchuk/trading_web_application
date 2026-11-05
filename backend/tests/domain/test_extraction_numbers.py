"""Extraction guards: int values as standalone numbers / number words (from
config/extraction.yaml), ambiguity, evidence length, ё."""

# ruff: noqa: RUF001, RUF003 - Ukrainian/Russian sample texts

from __future__ import annotations

import pytest

from app.config_files import JournalFieldsConfig, get_journal_fields, get_number_words
from app.domain.extraction import (
    Dropped,
    NumberWords,
    apply_guards,
    evidence_in_text,
    normalise_for_match,
    number_in_evidence,
)


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


@pytest.fixture
def words() -> NumberWords:
    return get_number_words()


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
def test_number_not_standalone_is_rejected(value: int, evidence: str, words: NumberWords) -> None:
    assert not number_in_evidence(value, evidence, words)


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
def test_standalone_number_is_accepted(value: int, evidence: str, words: NumberWords) -> None:
    assert number_in_evidence(value, evidence, words)


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
        (3, "на трійку"),  # accusative forms (M4-06 review)
        (3, "на тройку"),
        (1, "на единицу"),
        (5, "сетап на п'ятірку"),
        (4, "на четверку"),
    ],
)
def test_number_words_count_as_the_number(value: int, evidence: str, words: NumberWords) -> None:
    assert number_in_evidence(value, evidence, words)


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
def test_other_words_do_not_count(value: int, evidence: str, words: NumberWords) -> None:
    assert not number_in_evidence(value, evidence, words)


def test_rating_from_glued_token_is_dropped(
    config: JournalFieldsConfig, words: NumberWords
) -> None:
    text = "Вхід по IFVG M5, POI FVG H4."
    for value, evidence in ((5, "IFVG M5"), (4, "FVG H4")):
        result = apply_guards(
            config, {"quality_rating": {"value": value, "evidence": evidence}}, text, words
        )
        assert result.dropped == [Dropped("quality_rating", "evidence_not_in_text")]


def test_rating_in_words_is_kept(config: JournalFieldsConfig, words: NumberWords) -> None:
    text = "Сетап ідеальний, чесна четвірка."
    output = {"quality_rating": {"value": 4, "evidence": "чесна четвірка"}}
    assert apply_guards(config, output, text, words).fields == {"quality_rating": 4}


# --- M3-02: the words come from config/extraction.yaml; ambiguous -> empty ---


@pytest.mark.parametrize(
    ("value", "evidence"),
    [
        (4, "4"),
        (4, "четвірка"),
        (4, "четвёрка"),  # ё folded to е
        (4, "four"),
        (4, "на 4 з 5"),
        (4, "4 из 5"),
        (4, "four out of five"),
        (4, "4, ну чесна четвірка"),  # the same number twice is not ambiguous
    ],
)
def test_rating_said_once_is_accepted(value: int, evidence: str, words: NumberWords) -> None:
    assert number_in_evidence(value, evidence, words)


@pytest.mark.parametrize("evidence", ["на 4 з 5", "4 из 5", "setup 4 of 5", "4/5"])
def test_denominator_is_never_the_value(evidence: str, words: NumberWords) -> None:
    assert not number_in_evidence(5, evidence, words)


@pytest.mark.parametrize(
    "evidence",
    [
        "4 або 5",
        "4 или 5",
        "four or five",
        "чотири або п'ять",
        "4 або п'ять",
        "оцінка 4 - 5",  # spaced range
        "оцінка 4 – 5",
        "оцінка 4 -5",
        "на 4, ризик 14 пунктів",  # another number in the quote
        "три тейки, оцінка 4",
    ],
)
def test_two_different_numbers_are_ambiguous(evidence: str, words: NumberWords) -> None:
    for value in range(1, 6):
        assert not number_in_evidence(value, evidence, words), value


def test_ambiguous_rating_is_dropped_by_the_guards(
    config: JournalFieldsConfig, words: NumberWords
) -> None:
    text = "Сетап на 4 або 5, сам не знаю."
    output = {"quality_rating": {"value": 5, "evidence": "Сетап на 4 або 5"}}
    result = apply_guards(config, output, text, words)
    assert result.fields == {}
    assert result.dropped == [Dropped("quality_rating", "evidence_not_in_text")]


def test_words_are_passed_in_not_hardcoded() -> None:
    no_words = NumberWords({})
    assert not number_in_evidence(4, "чесна четвірка", no_words)
    assert number_in_evidence(4, "на 4", no_words)
    custom = NumberWords({"майже ідеал": 4, "четвірочка": 4})
    assert number_in_evidence(4, "майже ідеал", custom)
    assert number_in_evidence(4, "Четвірочка", custom)
    assert not number_in_evidence(4, "майже", custom)


def test_longer_phrase_wins_over_a_word_inside_it() -> None:
    words = NumberWords({"два": 2, "два з половиною": 3})
    assert number_in_evidence(3, "два з половиною", words)
    assert not number_in_evidence(2, "два з половиною", words)


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
