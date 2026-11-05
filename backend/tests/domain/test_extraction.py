"""AI extraction schema, prompt catalogue and guards (app.domain.extraction)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from app.config import REPO_ROOT
from app.config_files import (
    JournalFieldsConfig,
    get_journal_fields,
    get_number_words,
    reload_config,
)
from app.config_files.loader import CONFIG_DIR_ENV
from app.domain.extraction import (
    Dropped,
    GuardResult,
    InvalidAnswer,
    answer_entries,
    apply_guards,
    build_extraction_schema,
    evidence_in_text,
    extraction_missing,
    normalise_for_match,
    render_field_catalogue,
)

REAL_CONFIG = REPO_ROOT / "config"


def guard(config: JournalFieldsConfig, output: Mapping[str, Any], text: str) -> GuardResult:
    """apply_guards with the number words from the real config/extraction.yaml."""
    return apply_guards(config, output, text, get_number_words())


TEXT = (
    "Вхід по IFVG M5 після зняття ліквідності, Flow H1 синхронний з H4. "
    "Закрив по тейку, був спокійний. Урок: чекати підтвердження."
)


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name in (
        "rules.yaml",
        "journal_fields.yaml",
        "ai_pricing.yaml",
        "extraction.yaml",
        "transcription.yaml",
        "transcript_glossary.yaml",
        "bias.yaml",
    ):
        shutil.copy(REAL_CONFIG / name, tmp_path / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def entry(value: Any, evidence: str) -> dict[str, Any]:
    return {"value": value, "evidence": evidence}


NEW_FIELDS = """
  - key: market_phase
    label: "Фаза ринку"
    type: enum
    options:
      - { value: trend, label: "тренд" }
      - { value: range, label: "флет" }
      - { value: old, label: "старе", deprecated: true }
      - { value: other, label: "інше" }
    required: false
    analytics: true
    storage: extra
    text_key: market_phase_other
    allow_other_text: true

  - key: tags
    label: "Теги"
    type: multi_enum
    options:
      - { value: news, label: "новини" }
      - { value: gap, label: "гап" }
    required: false
    analytics: false
    storage: extra
"""


# --- schema ---


def schema_keys(config: JournalFieldsConfig) -> list[str]:
    item = build_extraction_schema(config)["properties"]["fields"]["items"]
    keys: list[str] = item["properties"]["key"]["enum"]
    return keys


def test_schema_is_one_flat_array_of_key_value_evidence(config: JournalFieldsConfig) -> None:
    """Flat on purpose: the API rejected one optional object per key as too complex."""
    schema = build_extraction_schema(config)
    assert schema == {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "enum": schema_keys(config)},
                        "value": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["key", "value", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["fields"],
        "additionalProperties": False,
    }


def test_schema_keys_are_the_ai_fillable_keys_in_yaml_order(config: JournalFieldsConfig) -> None:
    keys = schema_keys(config)
    assert keys[:4] == ["setup_context", "poi_type", "poi_type_other", "fvg_kind"]
    assert {"entry_model", "followed_plan", "quality_rating", "lesson"} <= set(keys)
    assert {"bias_alignment", "chart_links", "rule_violations"}.isdisjoint(keys)
    assert {"message", "question", "comment", "notes"}.isdisjoint(keys)


def test_schema_is_deterministic(config: JournalFieldsConfig) -> None:
    assert build_extraction_schema(config) == build_extraction_schema(config)


def test_field_added_to_yaml_appears_in_schema_and_prompt_without_code_changes(
    cfg_dir: Path,
) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_text(path.read_text(encoding="utf-8") + NEW_FIELDS, encoding="utf-8")
    reload_config()
    config = get_journal_fields()

    assert schema_keys(config)[-3:] == ["market_phase", "market_phase_other", "tags"]
    catalogue = render_field_catalogue(config)
    assert "`market_phase` (Фаза ринку)" in catalogue
    assert "`range`: флет" in catalogue
    assert "`old`" not in catalogue  # deprecated options are not offered
    assert "`tags` (Теги): one or more option values:" in catalogue


# --- answer -> entries ---


def wire(*items: tuple[str, str, str]) -> dict[str, Any]:
    return {"fields": [{"key": k, "value": v, "evidence": e} for k, v, e in items]}


def test_answer_entries_types_values_from_the_yaml(config: JournalFieldsConfig) -> None:
    answer = wire(
        ("entry_model", "ifvg_m5", "Вхід по IFVG M5"),
        ("followed_plan", "True", "по плану"),
        ("quality_rating", " 4 ", "на 4"),
        ("lesson", "чекати", "Урок: чекати"),
        ("mistakes", "  ", "x"),  # blank = not filled
    )
    assert answer_entries(config, answer) == {
        "entry_model": {"value": "ifvg_m5", "evidence": "Вхід по IFVG M5"},
        "followed_plan": {"value": True, "evidence": "по плану"},
        "quality_rating": {"value": 4, "evidence": "на 4"},
        "lesson": {"value": "чекати", "evidence": "Урок: чекати"},
    }


def test_answer_values_that_do_not_parse_are_kept_for_the_guards(
    config: JournalFieldsConfig,
) -> None:
    answer = wire(("followed_plan", "так", "по плану"), ("quality_rating", "4.5", "на 4.5"))
    entries = answer_entries(config, answer)
    assert entries["followed_plan"]["value"] == "так"
    assert entries["quality_rating"]["value"] == "4.5"
    result = guard(config, entries, "Все по плану, на 4.5")  # noqa: RUF001
    assert {d.reason for d in result.dropped} == {"invalid_option"}


def test_answer_repeated_key(config: JournalFieldsConfig) -> None:
    same = wire(("exit_reason", "tp", "по тейку"), ("exit_reason", "tp", "закрив по тейку"))
    assert answer_entries(config, same)["exit_reason"]["evidence"] == "по тейку"
    conflict = answer_entries(
        config, wire(("exit_reason", "tp", "по тейку"), ("exit_reason", "sl", "по стопу"))
    )
    result = guard(config, conflict, "закрив по тейку, по стопу")
    assert result.dropped == [Dropped("exit_reason", "invalid_option")]


def test_answer_multi_enum_items_are_merged_and_each_evidence_checked(cfg_dir: Path) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_text(path.read_text(encoding="utf-8") + NEW_FIELDS, encoding="utf-8")
    reload_config()
    config = get_journal_fields()
    entries = answer_entries(config, wire(("tags", "news", "на новинах"), ("tags", "gap", "гап")))
    assert entries["tags"] == {"value": ["news", "gap"], "evidence": ["на новинах", "гап"]}
    text = "Вхід на новинах після гапу"
    assert guard(config, entries, text).dropped == [Dropped("tags", "evidence_not_in_text")]
    ok = guard(config, entries, text + ", гап закрився")
    assert ok.fields == {"tags": ["news", "gap"]}


@pytest.mark.parametrize(
    "answer",
    [
        {},
        {"fields": "x"},
        {"fields": [1]},
        {"fields": [{"key": "lesson", "value": 4, "evidence": "x"}]},
        {"fields": [{"key": "lesson", "value": "x"}]},
    ],
)
def test_answer_with_wrong_shape_is_invalid(config: JournalFieldsConfig, answer: Any) -> None:
    with pytest.raises(InvalidAnswer):
        answer_entries(config, answer)


# --- prompt catalogue ---


def test_catalogue_lists_options_with_labels_in_yaml_order(config: JournalFieldsConfig) -> None:
    catalogue = render_field_catalogue(config)
    assert "- `setup_context` (Контекст (Flow H1 синхронний з H4)): one option value:" in catalogue
    assert "  - `ifvg_m5`: IFVG M5" in catalogue
    assert "- `quality_rating`" in catalogue
    assert "integer from 1 to 5" in catalogue
    assert "`poi_type_other`" in catalogue
    assert "only when `poi_type` is `other`" in catalogue
    assert catalogue.index("`setup_context`") < catalogue.index("`quality_rating`")
    assert "rule_violations" not in catalogue
    assert "chart_links" not in catalogue


def test_catalogue_is_deterministic(config: JournalFieldsConfig) -> None:
    assert render_field_catalogue(config) == render_field_catalogue(config)


# --- evidence matching ---


def test_evidence_match_ignores_case_whitespace_and_typographic_variants() -> None:
    text = normalise_for_match("Закрив  по\nТЕЙКУ, п’ятихвилинка — IFVG")  # noqa: RUF001 - Ukrainian text
    assert evidence_in_text("закрив по тейку", text)
    assert evidence_in_text("п'ятихвилинка - ifvg", text)
    assert not evidence_in_text("закрив по стопу", text)
    assert not evidence_in_text("", text)
    assert not evidence_in_text("   ", text)
    assert not evidence_in_text(None, text)


# --- guards ---


def test_valid_values_are_kept_in_yaml_order(config: JournalFieldsConfig) -> None:
    output = {
        "lesson": entry("чекати підтвердження", "Урок: чекати підтвердження"),
        "entry_model": entry("ifvg_m5", "Вхід по IFVG M5"),
        "setup_context": entry("yes", "Flow H1 синхронний з H4"),
        "exit_reason": entry("tp", "Закрив по тейку"),
        "emotion_before": entry("calm", "був спокійний"),
    }
    result = guard(config, output, TEXT)
    assert result.dropped == []
    assert list(result.fields) == [
        "setup_context",
        "entry_model",
        "exit_reason",
        "emotion_before",
        "lesson",
    ]
    assert result.ai_filled_fields == list(result.fields)


def test_evidence_not_in_text_is_dropped(config: JournalFieldsConfig) -> None:
    output = {
        "poi_type": entry("fvg_h4", "POI FVG H4"),  # never said
        "followed_plan": {"value": True},  # no evidence at all
        "fvg_kind": "post_manipulation",  # not an entry object
    }
    result = guard(config, output, TEXT)
    assert result.fields == {}
    assert result.dropped == [
        Dropped("poi_type", "evidence_not_in_text"),
        Dropped("fvg_kind", "evidence_not_in_text"),
        Dropped("followed_plan", "evidence_not_in_text"),
    ]


def test_invalid_and_deprecated_options_are_dropped(cfg_dir: Path) -> None:
    path = cfg_dir / "journal_fields.yaml"
    content = path.read_text(encoding="utf-8")
    old = '{ value: partially, label: "частково" }'
    path.write_text(
        content.replace(old, '{ value: partially, label: "частково", deprecated: true }'),
        encoding="utf-8",
    )
    reload_config()
    output = {
        "entry_model": entry("ifvg_h1", "Вхід по IFVG M5"),
        "setup_context": entry("partially", "Flow H1 синхронний з H4"),
        "followed_plan": entry("yes", "Закрив по тейку"),  # wrong type
    }
    result = guard(get_journal_fields(), output, TEXT)
    assert result.fields == {}
    assert {d.reason for d in result.dropped} == {"invalid_option"}
    assert len(result.dropped) == 3


def test_int_out_of_range_is_dropped(config: JournalFieldsConfig) -> None:
    text = "Якість сетапу 7 з 5, а взагалі 4"  # noqa: RUF001 - Ukrainian text
    result = guard(config, {"quality_rating": entry(7, "Якість сетапу 7 з 5")}, text)
    assert result.dropped == [Dropped("quality_rating", "out_of_range")]
    ok = guard(config, {"quality_rating": entry(4, "взагалі 4")}, text)
    assert ok.fields == {"quality_rating": 4}


def test_other_text_needs_parent_other(config: JournalFieldsConfig) -> None:
    text = "POI був OB H4, вхід по IFVG M5"
    result = guard(config, {"poi_type_other": entry("OB H4", "OB H4")}, text)
    assert result.dropped == [Dropped("poi_type_other", "parent_not_other")]
    result = guard(
        config,
        {"poi_type": entry("fvg_h4", "OB H4"), "poi_type_other": entry("OB H4", "OB H4")},
        text,
    )
    assert result.fields == {"poi_type": "fvg_h4"}
    assert result.dropped == [Dropped("poi_type_other", "parent_not_other")]
    result = guard(
        config,
        {"poi_type": entry("other", "POI був OB H4"), "poi_type_other": entry("OB H4", "OB H4")},
        text,
    )
    assert result.fields == {"poi_type": "other", "poi_type_other": "OB H4"}


def test_text_with_question_not_in_evidence_is_dropped(config: JournalFieldsConfig) -> None:
    output = {
        "mistakes": entry("Чому ти не дочекався підтвердження?", "чекати підтвердження"),
        "lesson": entry("чекати підтвердження", "Урок: чекати підтвердження"),
    }
    result = guard(config, output, TEXT)
    assert result.fields == {"lesson": "чекати підтвердження"}
    assert result.dropped == [Dropped("mistakes", "question")]


def test_question_mark_quoted_from_the_text_is_kept(config: JournalFieldsConfig) -> None:
    text = "Помилка: навіщо я зайшов так рано? Не знаю."  # noqa: RUF001 - Ukrainian text
    output = {"mistakes": entry("навіщо я зайшов так рано?", "навіщо я зайшов так рано?")}
    assert guard(config, output, text).fields == {"mistakes": "навіщо я зайшов так рано?"}


def test_non_fillable_keys_are_dropped(config: JournalFieldsConfig) -> None:
    output = {
        "rule_violations": entry(["max_risk_pct"], "Закрив по тейку"),
        "bias_alignment": entry("aligned", "Закрив по тейку"),
        "chart_links": entry("x", "Закрив по тейку"),
        "message": entry("Які були емоції?", "Закрив по тейку"),
    }
    result = guard(config, output, TEXT)
    assert result.fields == {}
    assert {d.key for d in result.dropped} == set(output)
    assert {d.reason for d in result.dropped} == {"not_fillable"}


def test_null_and_empty_values_are_not_filled_and_not_dropped(
    config: JournalFieldsConfig,
) -> None:
    output: dict[str, Any] = {
        "lesson": entry("   ", "Урок"),
        "mistakes": None,
        "followed_plan": {"value": None, "evidence": ""},
    }
    result = guard(config, output, TEXT)
    assert result.fields == {}
    assert result.dropped == []


def test_text_values_are_trimmed(config: JournalFieldsConfig) -> None:
    result = guard(config, {"lesson": entry("  чекати  ", "чекати")}, TEXT)
    assert result.fields == {"lesson": "чекати"}


# --- completeness ---


def test_missing_required_always_lists_chart_links(config: JournalFieldsConfig) -> None:
    """Extraction returns no links, so chart_links is listed even if the text has one."""
    fields = {"setup_context": "yes", "entry_model": "ifvg_m5"}
    assert extraction_missing(config, fields) == [
        "poi_type",
        "fvg_kind",
        "exit_reason",
        "followed_plan",
        "emotion_before",
        "emotion_after",
        "quality_rating",
        "chart_links",
    ]


# --- evidence on word boundaries, values tied to the text ---


@pytest.mark.parametrize(
    "evidence",
    [
        "а",  # 1 char  # noqa: RUF001 - Ukrainian text
        "по",  # 2 chars
        "лан",  # mid-word: inside "плану"
        "хід по IFVG",  # starts mid-word: inside "Вхід"
        "IFVG M",  # ends mid-word ("M5")
        "ідтвердже",  # inside "підтвердження"
    ],
)
def test_short_or_mid_word_evidence_is_rejected(evidence: str) -> None:
    text = normalise_for_match("Вхід по IFVG M5 по плану, а урок: чекати підтвердження.")  # noqa: RUF001
    assert not evidence_in_text(evidence, text)


@pytest.mark.parametrize(
    "evidence", ["IFVG M5", "по плану", "по плану,", "урок: чекати", "підтвердження."]
)
def test_whole_word_evidence_is_accepted(evidence: str) -> None:
    text = normalise_for_match("Вхід по IFVG M5 по плану, а урок: чекати підтвердження.")  # noqa: RUF001
    assert evidence_in_text(evidence, text)


def test_apostrophe_is_part_of_a_word() -> None:
    text = normalise_for_match("п'ятихвилинка IFVG")
    assert not evidence_in_text("ятихвилинка IFVG", text)
    assert evidence_in_text("п'ятихвилинка", text)


def test_mid_word_evidence_drops_the_value(config: JournalFieldsConfig) -> None:
    text = "Все по плану"  # noqa: RUF001
    result = guard(config, {"followed_plan": entry(True, "лан")}, text)
    assert result.dropped == [Dropped("followed_plan", "evidence_not_in_text")]
    ok = guard(config, {"followed_plan": entry(True, "по плану")}, text)
    assert ok.fields == {"followed_plan": True}


def test_int_needs_its_digits_in_the_evidence(config: JournalFieldsConfig) -> None:
    text = "Сетап дуже хороший, на 4. Ризик 14 пунктів."
    no_digit = guard(config, {"quality_rating": entry(5, "Сетап дуже хороший")}, text)
    assert no_digit.dropped == [Dropped("quality_rating", "evidence_not_in_text")]
    other_number = guard(config, {"quality_rating": entry(4, "Ризик 14 пунктів")}, text)
    assert other_number.dropped == [Dropped("quality_rating", "evidence_not_in_text")]
    ok = guard(config, {"quality_rating": entry(4, "Сетап дуже хороший, на 4")}, text)
    assert ok.fields == {"quality_rating": 4}


def test_text_value_must_be_his_own_words(config: JournalFieldsConfig) -> None:
    text = "Урок: не рухати стоп раніше часу."
    summarised = guard(
        config, {"lesson": entry("Тримати стоп на місці", "Урок: не рухати стоп")}, text
    )
    assert summarised.dropped == [Dropped("lesson", "evidence_not_in_text")]
    mid_word = guard(config, {"lesson": entry("ухати стоп", "не рухати стоп")}, text)
    assert mid_word.dropped == [Dropped("lesson", "evidence_not_in_text")]
    verbatim = guard(
        config,
        {"lesson": entry("Не рухати стоп раніше часу", "Урок: не рухати стоп")},  # noqa: RUF001
        text,
    )
    assert verbatim.fields == {"lesson": "Не рухати стоп раніше часу"}  # noqa: RUF001


def test_other_text_value_must_be_in_the_text(config: JournalFieldsConfig) -> None:
    text = "POI був ордер блок на H4"
    output = {
        "poi_type": entry("other", "POI був ордер блок"),
        "poi_type_other": entry("OB H4", "ордер блок на H4"),  # translated, not his words
    }
    result = guard(config, output, text)
    assert result.fields == {"poi_type": "other"}
    assert result.dropped == [Dropped("poi_type_other", "evidence_not_in_text")]
