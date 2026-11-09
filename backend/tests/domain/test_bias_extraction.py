"""Bias extraction schema and guards (app.domain.bias_extraction, docs/api.md M4)."""

# ruff: noqa: RUF001 - Ukrainian/Russian sample texts

from __future__ import annotations

from typing import Any

import pytest

from app.config_files import get_bias_config, get_number_words
from app.config_files.bias import BiasConfig, BiasReminders, BiasSymbol, ReminderWindow
from app.domain.bias_extraction import (
    BIAS_FIELD_KEYS,
    BiasDropped,
    answer_values,
    apply_bias_guards,
    build_bias_schema,
    mentioned_symbols,
    render_symbol_catalogue,
)
from app.domain.extraction import InvalidAnswer


def wire(*items: tuple[str, str, str, str]) -> dict[str, Any]:
    keys = ("symbol", "key", "value", "evidence")
    return {"entries": [dict(zip(keys, item, strict=True)) for item in items]}


def guard(text: str, *items: tuple[str, str, str, str]) -> Any:
    return apply_bias_guards(
        get_bias_config(), answer_values(wire(*items)), text, get_number_words()
    )


def dropped(result: Any) -> list[tuple[str, str, str]]:
    return [(d.symbol, d.key, d.reason) for d in result.dropped]


# --- schema / catalogue ---


def test_schema_is_flat_with_symbol_and_key_enums() -> None:
    schema = build_bias_schema(get_bias_config())
    item = schema["properties"]["entries"]["items"]
    assert schema["required"] == ["entries"]
    assert schema["additionalProperties"] is False
    assert item["required"] == ["symbol", "key", "value", "evidence"]
    assert item["additionalProperties"] is False
    assert item["properties"]["symbol"]["enum"] == ["EURUSD", "GBPUSD", "XAUUSD", "GER40"]
    assert item["properties"]["key"]["enum"] == list(BIAS_FIELD_KEYS)
    assert item["properties"]["value"] == {"type": "string"}


def test_symbol_catalogue_lists_aliases_in_config_order() -> None:
    lines = render_symbol_catalogue(get_bias_config()).splitlines()
    assert lines[0] == "- `EURUSD`: also called євро, евро, фібер, фибер, fiber, euro, EUR/USD"
    assert lines[3] == "- `GER40`: also called дакс, DAX, GER"


def test_symbol_catalogue_without_aliases() -> None:
    window = ReminderWindow.model_validate({"from": "07:45", "until": "11:00"})
    config = BiasConfig(
        symbols=(BiasSymbol(symbol="NAS100", aliases=()),),
        reminders=BiasReminders(pre_london=window, pre_ny=window),
    )
    assert render_symbol_catalogue(config) == "- `NAS100`"


# --- symbol mentions ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Золото бичаче", {"XAUUSD"}),
        ("по золоту шукаю покупки", {"XAUUSD"}),
        ("По даксу шорт, кабель вгору", {"GER40", "GBPUSD"}),
        ("на кабелі рейндж", {"GBPUSD"}),
        ("фібер і фунт вниз", {"EURUSD", "GBPUSD"}),
        ("DAX long, gold flat", {"GER40", "XAUUSD"}),
        ("GER40 bearish", {"GER40"}),
        ("ger bearish", {"GER40"}),
        ("XAUUSD 2650", {"XAUUSD"}),
        ("EUR/USD вниз, GBP/USD вгору", {"EURUSD", "GBPUSD"}),
        ("XAU/USD long", {"XAUUSD"}),
        ("XAU long, GBP short", {"XAUUSD", "GBPUSD"}),
        ("xauusd і gbpusd", {"XAUUSD", "GBPUSD"}),  # symbol names, any case
        ("GBPJPY short", set()),  # GBP only as a whole word
        ("усі пари бичачі", set()),
        ("золотий стандарт", {"XAUUSD"}),  # accepted false positive of the ending rule
        ("GERMANY", set()),  # Latin names: whole words only
        ("евротур", set()),  # евро: whole word only
        ("Європа відкрилась вниз", set()),  # stem "євр" too short for endings
        ("Европа вниз", set()),
        ("євро вгору", {"EURUSD"}),
        ("по фіберу", {"EURUSD"}),
        ("німецький індекс", set()),
    ],
)
def test_mentioned_symbols(text: str, expected: set[str]) -> None:
    assert mentioned_symbols(get_bias_config(), text) == expected


# --- answer parsing ---


def test_answer_values_skips_empty_and_flags_conflicts() -> None:
    values = answer_values(
        wire(
            ("XAUUSD", "direction", "bullish", "золото вгору"),
            ("XAUUSD", "direction", "bullish", "золото вгору ще раз"),
            ("GER40", "direction", "bullish", "дакс вгору"),
            ("GER40", "direction", "bearish", "дакс вниз"),
            ("EURUSD", "narrative", "  ", "x"),
        )
    )
    assert values[("XAUUSD", "direction")] == ("bullish", "золото вгору")
    assert ("EURUSD", "narrative") not in values
    result = apply_bias_guards(
        get_bias_config(), values, "золото вгору, дакс вгору або дакс вниз", get_number_words()
    )
    assert dropped(result) == [("GER40", "direction", "invalid_option")]


@pytest.mark.parametrize(
    "answer",
    [{}, {"entries": "x"}, {"entries": ["x"]}, {"entries": [{"symbol": "XAUUSD", "key": "d"}]}],
)
def test_answer_values_rejects_wrong_shape(answer: dict[str, Any]) -> None:
    with pytest.raises(InvalidAnswer):
        answer_values(answer)


# --- guards ---


def test_guards_keep_values_in_config_and_field_order() -> None:
    text = "Дакс шорт від FVG H1 18950, впевненість 2. Золото бичаче, чекаю зняття лоу Азії."
    result = guard(
        text,
        ("XAUUSD", "narrative", "чекаю зняття лоу Азії", "чекаю зняття лоу Азії"),
        ("GER40", "confidence", "2", "впевненість 2"),
        ("XAUUSD", "direction", "bullish", "Золото бичаче"),
        ("GER40", "key_levels", "FVG H1 18950", "від FVG H1 18950"),
        ("GER40", "direction", "bearish", "Дакс шорт"),
    )
    assert [(e.symbol, e.fields) for e in result.entries] == [
        ("XAUUSD", {"direction": "bullish", "narrative": "чекаю зняття лоу Азії"}),
        ("GER40", {"direction": "bearish", "key_levels": "FVG H1 18950", "confidence": 2}),
    ]
    assert result.entries[1].evidence == {
        "direction": "Дакс шорт",
        "key_levels": "від FVG H1 18950",
        "confidence": "впевненість 2",
    }
    assert result.dropped == []


def test_value_for_symbol_not_in_text_is_dropped() -> None:
    result = guard("Золото бичаче.", ("EURUSD", "direction", "bullish", "Золото бичаче"))
    assert result.entries == []
    assert result.dropped == [BiasDropped("EURUSD", "direction", "symbol_not_in_text")]


def test_one_sentence_for_several_named_symbols_is_kept_per_symbol() -> None:
    text = "Золото і дакс сьогодні бичачі."
    quote = "Золото і дакс сьогодні бичачі"
    result = guard(
        text,
        ("XAUUSD", "direction", "bullish", quote),
        ("GER40", "direction", "bullish", quote),
        ("EURUSD", "direction", "bullish", quote),
    )
    assert [e.symbol for e in result.entries] == ["XAUUSD", "GER40"]
    assert dropped(result) == [("EURUSD", "direction", "symbol_not_in_text")]


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (("XAUUSD", "direction", "up", "золото вгору"), "invalid_option"),
        (("XAUUSD", "direction", "bullish", "золото вниз"), "evidence_not_in_text"),
        (("XAUUSD", "direction", "bullish", "зо"), "evidence_not_in_text"),
        (("XAUUSD", "confidence", "двійка", "впевненість двійка"), "invalid_option"),
        (("XAUUSD", "confidence", "4", "впевненість 4"), "out_of_range"),
        (("XAUUSD", "confidence", "3", "впевненість двійка"), "evidence_not_in_text"),
        (("XAUUSD", "confidence", "2", "2 або 3"), "evidence_not_in_text"),
        (("XAUUSD", "narrative", "піде вниз?", "золото вгору"), "question"),
        (("XAUUSD", "narrative", "піде на 2700", "золото вгору"), "evidence_not_in_text"),
        (("XAUUSD", "key_levels", "x" * 5001, "золото вгору"), "out_of_range"),
        (("XAUUSD", "chart_links", "x", "золото вгору"), "not_fillable"),
        (("NAS100", "direction", "bullish", "золото вгору"), "not_fillable"),
    ],
)
def test_guard_reasons(item: tuple[str, str, str, str], reason: str) -> None:
    text = "золото вгору, впевненість двійка, 2 або 3, впевненість 4"
    result = guard(text, item)
    assert result.entries == []
    assert dropped(result) == [(item[0], item[1], reason)]


def test_confidence_in_the_accusative() -> None:
    text = "Золото вгору, впевненість на трійку."
    result = guard(text, ("XAUUSD", "confidence", "3", "на трійку"))
    assert result.entries[0].fields == {"confidence": 3}


def test_confidence_from_number_word_and_denominator() -> None:
    text = "Золото вгору, впевненість двійка. Дакс вниз, один з трьох."
    result = guard(
        text,
        ("XAUUSD", "confidence", "2", "впевненість двійка"),
        ("GER40", "confidence", "1", "один з трьох"),
    )
    assert [(e.symbol, e.fields) for e in result.entries] == [
        ("XAUUSD", {"confidence": 2}),
        ("GER40", {"confidence": 1}),
    ]


def test_question_in_text_value_kept_when_he_said_it() -> None:
    text = "Золото: чи дійде до 2700? Не знаю."
    result = guard(text, ("XAUUSD", "narrative", "чи дійде до 2700?", "чи дійде до 2700?"))
    assert result.entries[0].fields == {"narrative": "чи дійде до 2700?"}


def test_dropped_sorted_by_symbol_then_field() -> None:
    result = guard(
        "Дакс вгору. Золото вгору.",
        ("GER40", "confidence", "3", "Дакс вгору"),
        ("XAUUSD", "direction", "bearish", "Золото вниз"),
        ("GER40", "direction", "up", "Дакс вгору"),
        ("NAS100", "direction", "bullish", "Дакс вгору"),
    )
    assert dropped(result) == [
        ("XAUUSD", "direction", "evidence_not_in_text"),
        ("GER40", "direction", "invalid_option"),
        ("GER40", "confidence", "evidence_not_in_text"),
        ("NAS100", "direction", "not_fillable"),
    ]


def test_confidence_russian_number_word_single() -> None:
    # Live M4 miss (PM 2026-11-09): "уверенность единица" = confidence 1.
    text = "Кабель в шорт от POI H4 1.2710. Евро тоже вниз, уверенность единица."
    result = guard(text, ("EURUSD", "confidence", "1", "уверенность единица"))
    assert result.entries[0].fields == {"confidence": 1}


# --- key_levels: several levels joined by "; " in text order (PM 2026-11-09) ---

DAX_TEXT = (
    "Сьогодні по золоту шукаю покупки від FVG H1 2648, впевненість 2. "
    "Дакс ведмежий, чекаю зняття хаю Азії, потім вниз до 18900."
)
DAX_QUOTE = "чекаю зняття хаю Азії, потім вниз до 18900"


def test_key_levels_several_parts_in_text_order_kept() -> None:
    result = guard(DAX_TEXT, ("GER40", "key_levels", "хаю Азії; 18900", DAX_QUOTE))
    assert result.entries[0].fields == {"key_levels": "хаю Азії; 18900"}
    assert result.dropped == []


def test_key_levels_single_part_still_kept() -> None:
    result = guard(DAX_TEXT, ("GER40", "key_levels", "18900", "вниз до 18900"))
    assert result.entries[0].fields == {"key_levels": "18900"}


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("18900; хаю Азії", "invalid_option"),  # not in text order
        ("хаю Азії; 18900; хаю Азії", "invalid_option"),  # duplicate part
        ("хаю Азії; хаю Азії", "invalid_option"),  # duplicate part
        ("хаю Азії; ; 18900", "invalid_option"),  # empty part
        ("хаю Азії; ", "evidence_not_in_text"),  # value is stripped first -> "хаю Азії;"
        ("; 18900", "invalid_option"),  # empty first part
        ("хаю Азії;", "evidence_not_in_text"),  # no "; " separator: ";" is not in the text
        ("хаю Азії; 19000", "evidence_not_in_text"),  # one part not in the text
        ("хай Азії; 18900", "evidence_not_in_text"),  # paraphrased part
        ("хаю Азії; Азії", "invalid_option"),  # second part only inside the first
        ("хаю Азії; 18900?", "question"),
        ("хаю Азії; " + "x" * 5000, "out_of_range"),  # total length limit
    ],
)
def test_key_levels_bad_parts_are_dropped(value: str, reason: str) -> None:
    result = guard(DAX_TEXT, ("GER40", "key_levels", value, DAX_QUOTE))
    assert result.entries == []
    assert dropped(result) == [("GER40", "key_levels", reason)]


def test_key_levels_extra_space_after_separator_kept() -> None:
    result = guard(DAX_TEXT, ("GER40", "key_levels", "хаю Азії;  18900", DAX_QUOTE))
    assert result.entries[0].fields == {"key_levels": "хаю Азії;  18900"}


def test_key_levels_part_also_said_earlier_is_matched_after_previous_part() -> None:
    text = "Дакс: 18900 тримає, чекаю зняття хаю Азії, потім знову 18900."
    quote = "18900 тримає, чекаю зняття хаю Азії, потім знову 18900"
    result = guard(text, ("GER40", "key_levels", "хаю Азії; 18900", quote))
    assert result.entries[0].fields == {"key_levels": "хаю Азії; 18900"}


def test_narrative_is_still_one_continuous_piece() -> None:
    result = guard(DAX_TEXT, ("GER40", "narrative", "хаю Азії; 18900", DAX_QUOTE))
    assert result.entries == []
    assert dropped(result) == [("GER40", "narrative", "evidence_not_in_text")]
