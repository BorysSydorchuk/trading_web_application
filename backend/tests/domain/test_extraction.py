"""AI extraction schema, prompt catalogue and guards (app.domain.extraction)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.config import REPO_ROOT
from app.config_files import JournalFieldsConfig, get_journal_fields, reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.domain.extraction import (
    Dropped,
    apply_guards,
    build_extraction_schema,
    evidence_in_text,
    extraction_missing,
    normalise_for_match,
    render_field_catalogue,
)

REAL_CONFIG = REPO_ROOT / "config"
TEXT = (
    "Вхід по IFVG M5 після зняття ліквідності, Flow H1 синхронний з H4. "
    "Закрив по тейку, був спокійний. Урок: чекати підтвердження."
)


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name in ("rules.yaml", "journal_fields.yaml", "ai_pricing.yaml"):
        shutil.copy(REAL_CONFIG / name, tmp_path / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def entry(value: Any, evidence: str) -> dict[str, Any]:
    return {"value": value, "evidence": evidence}


# --- schema ---


def test_schema_is_strict_object_with_optional_value_evidence_entries(
    config: JournalFieldsConfig,
) -> None:
    schema = build_extraction_schema(config)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "required" not in schema  # every field optional: unknown means left out
    for prop in schema["properties"].values():
        assert prop["additionalProperties"] is False
        assert prop["required"] == ["value", "evidence"]
        assert set(prop["properties"]) == {"value", "evidence"}
        assert prop["properties"]["evidence"]["type"] == "string"


def test_schema_types_follow_the_yaml(config: JournalFieldsConfig) -> None:
    props = build_extraction_schema(config)["properties"]
    assert props["entry_model"]["properties"]["value"] == {
        "type": "string",
        "enum": ["ifvg_m5", "qm_m5", "other"],
    }
    assert props["followed_plan"]["properties"]["value"] == {"type": "boolean"}
    assert props["quality_rating"]["properties"]["value"]["type"] == "integer"
    assert props["poi_type_other"]["properties"]["value"] == {"type": "string"}
    assert props["lesson"]["properties"]["value"] == {"type": "string"}


def test_schema_never_offers_auto_links_rule_violations_or_a_message(
    config: JournalFieldsConfig,
) -> None:
    keys = set(build_extraction_schema(config)["properties"])
    assert {"bias_alignment", "chart_links", "rule_violations"}.isdisjoint(keys)
    assert {"message", "question", "comment", "notes"}.isdisjoint(keys)


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


def test_field_added_to_yaml_appears_in_schema_and_prompt_without_code_changes(
    cfg_dir: Path,
) -> None:
    path = cfg_dir / "journal_fields.yaml"
    path.write_text(path.read_text(encoding="utf-8") + NEW_FIELDS, encoding="utf-8")
    reload_config()
    config = get_journal_fields()

    props = build_extraction_schema(config)["properties"]
    assert props["market_phase"]["properties"]["value"]["enum"] == ["trend", "range", "other"]
    assert props["market_phase_other"]["properties"]["value"] == {"type": "string"}
    assert props["tags"]["properties"]["value"] == {
        "type": "array",
        "items": {"type": "string", "enum": ["news", "gap"]},
    }
    catalogue = render_field_catalogue(config)
    assert "`market_phase` (Фаза ринку)" in catalogue
    assert "`range`: флет" in catalogue
    assert "`old`" not in catalogue  # deprecated options are not offered


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
    result = apply_guards(config, output, TEXT)
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
    result = apply_guards(config, output, TEXT)
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
    result = apply_guards(get_journal_fields(), output, TEXT)
    assert result.fields == {}
    assert {d.reason for d in result.dropped} == {"invalid_option"}
    assert len(result.dropped) == 3


def test_int_out_of_range_is_dropped(config: JournalFieldsConfig) -> None:
    text = "Якість сетапу 7 з 5, а взагалі 4"  # noqa: RUF001 - Ukrainian text
    result = apply_guards(config, {"quality_rating": entry(7, "Якість сетапу 7 з 5")}, text)
    assert result.dropped == [Dropped("quality_rating", "out_of_range")]
    ok = apply_guards(config, {"quality_rating": entry(4, "взагалі 4")}, text)
    assert ok.fields == {"quality_rating": 4}


def test_other_text_needs_parent_other(config: JournalFieldsConfig) -> None:
    text = "POI був OB H4, вхід по IFVG M5"
    result = apply_guards(config, {"poi_type_other": entry("OB H4", "OB H4")}, text)
    assert result.dropped == [Dropped("poi_type_other", "parent_not_other")]
    result = apply_guards(
        config,
        {"poi_type": entry("fvg_h4", "OB H4"), "poi_type_other": entry("OB H4", "OB H4")},
        text,
    )
    assert result.fields == {"poi_type": "fvg_h4"}
    assert result.dropped == [Dropped("poi_type_other", "parent_not_other")]
    result = apply_guards(
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
    result = apply_guards(config, output, TEXT)
    assert result.fields == {"lesson": "чекати підтвердження"}
    assert result.dropped == [Dropped("mistakes", "question")]


def test_question_mark_quoted_from_the_text_is_kept(config: JournalFieldsConfig) -> None:
    text = "Помилка: навіщо я зайшов так рано? Не знаю."  # noqa: RUF001 - Ukrainian text
    output = {"mistakes": entry("навіщо я зайшов так рано?", "навіщо я зайшов так рано?")}
    assert apply_guards(config, output, text).fields == {"mistakes": "навіщо я зайшов так рано?"}


def test_non_fillable_keys_are_dropped(config: JournalFieldsConfig) -> None:
    output = {
        "rule_violations": entry(["max_risk_pct"], "Закрив по тейку"),
        "bias_alignment": entry("aligned", "Закрив по тейку"),
        "chart_links": entry("x", "Закрив по тейку"),
        "message": entry("Які були емоції?", "Закрив по тейку"),
    }
    result = apply_guards(config, output, TEXT)
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
    result = apply_guards(config, output, TEXT)
    assert result.fields == {}
    assert result.dropped == []


def test_text_values_are_trimmed(config: JournalFieldsConfig) -> None:
    result = apply_guards(config, {"lesson": entry("  чекати  ", "чекати")}, TEXT)
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
    result = apply_guards(config, {"followed_plan": entry(True, "лан")}, text)
    assert result.dropped == [Dropped("followed_plan", "evidence_not_in_text")]
    ok = apply_guards(config, {"followed_plan": entry(True, "по плану")}, text)
    assert ok.fields == {"followed_plan": True}


def test_int_needs_its_digits_in_the_evidence(config: JournalFieldsConfig) -> None:
    text = "Сетап дуже хороший, на 4. Ризик 14 пунктів."
    no_digit = apply_guards(config, {"quality_rating": entry(5, "Сетап дуже хороший")}, text)
    assert no_digit.dropped == [Dropped("quality_rating", "evidence_not_in_text")]
    other_number = apply_guards(config, {"quality_rating": entry(4, "Ризик 14 пунктів")}, text)
    assert other_number.dropped == [Dropped("quality_rating", "evidence_not_in_text")]
    ok = apply_guards(config, {"quality_rating": entry(4, "Сетап дуже хороший, на 4")}, text)
    assert ok.fields == {"quality_rating": 4}


def test_text_value_must_be_his_own_words(config: JournalFieldsConfig) -> None:
    text = "Урок: не рухати стоп раніше часу."
    summarised = apply_guards(
        config, {"lesson": entry("Тримати стоп на місці", "Урок: не рухати стоп")}, text
    )
    assert summarised.dropped == [Dropped("lesson", "evidence_not_in_text")]
    mid_word = apply_guards(config, {"lesson": entry("ухати стоп", "не рухати стоп")}, text)
    assert mid_word.dropped == [Dropped("lesson", "evidence_not_in_text")]
    verbatim = apply_guards(
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
    result = apply_guards(config, output, text)
    assert result.fields == {"poi_type": "other"}
    assert result.dropped == [Dropped("poi_type_other", "evidence_not_in_text")]
