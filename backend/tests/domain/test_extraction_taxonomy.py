"""M8-04..08 merge B: AI extraction for the taxonomy fields (docs/api.md "Analytics, filters,
AI (merge B)"): schema and catalogue from the YAML (multi values as lists, other-text keys,
show_if conditions, never legacy) and the show_if guard (`parent_not_selected`)."""

# ruff: noqa: RUF001 - Ukrainian/Russian sample texts

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.config_files import JournalFieldsConfig, get_journal_fields, get_number_words
from app.domain.extraction import (
    Dropped,
    GuardResult,
    apply_guards,
    build_extraction_schema,
    render_field_catalogue,
)

TEXT = (
    "Флоу на H1, на H4 рейндж. POI FVG H1 і фрактал H4, FVG після маніпуляції. "
    "Вхід інше: по своїй моделі зі зламом."
)


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


def entry(value: Any, evidence: str) -> dict[str, Any]:
    return {"value": value, "evidence": evidence}


def guard(
    config: JournalFieldsConfig,
    output: Mapping[str, Any],
    current: Mapping[str, Any] | None = None,
) -> GuardResult:
    return apply_guards(config, output, TEXT, get_number_words(), current=current)


def schema_keys(config: JournalFieldsConfig) -> list[str]:
    item = build_extraction_schema(config)["properties"]["fields"]["items"]
    keys: list[str] = item["properties"]["key"]["enum"]
    return keys


def test_schema_offers_new_fields_and_other_texts_but_never_legacy(
    config: JournalFieldsConfig,
) -> None:
    # Act
    keys = schema_keys(config)

    # Assert
    for key in (
        "h1_context",
        "h1_context_other",
        "h4_context_other",
        "poi_types",
        "poi_types_other",
        "fvg_types_h1",
        "fvg_types_h1_other",
        "fvg_types_h4",
        "entry_model_other",
    ):
        assert key in keys
    for key in ("setup_context", "fvg_kind", "poi_type", "poi_type_other"):
        assert key not in keys


def test_catalogue_names_the_show_if_condition_for_the_field_and_its_text(
    config: JournalFieldsConfig,
) -> None:
    # Act
    catalogue = render_field_catalogue(config)

    # Assert
    assert (
        "- `fvg_types_h1` (Тип FVG H1), only when `poi_types` contains `fvg_h1`: "
        "one or more option values:"
    ) in catalogue
    assert (
        "- `fvg_types_h4_other` (Тип FVG H4), only when `poi_types` contains `fvg_h4`: "
        "free text, only when `fvg_types_h4` contains `other`."
    ) in catalogue
    assert "- `h1_context` (Контекст H1): one option value:" in catalogue


def test_show_if_field_is_kept_when_the_extracted_parent_includes_the_option(
    config: JournalFieldsConfig,
) -> None:
    # Arrange
    output = {
        "poi_types": entry(["fvg_h1", "fractal_h4"], "POI FVG H1 і фрактал H4"),
        "fvg_types_h1": entry(["post_manipulation"], "FVG після маніпуляції"),
    }

    # Act
    result = guard(config, output)

    # Assert
    assert result.dropped == []
    assert result.fields == {
        "poi_types": ["fvg_h1", "fractal_h4"],
        "fvg_types_h1": ["post_manipulation"],
    }


def test_show_if_field_and_its_text_are_dropped_when_no_parent_includes_the_option(
    config: JournalFieldsConfig,
) -> None:
    # Arrange: POI H1 only, yet the model also filled the H4 FVG type and its other-text
    output = {
        "poi_types": entry(["fvg_h1"], "POI FVG H1"),
        "fvg_types_h4": entry(["post_manipulation", "other"], "FVG після маніпуляції"),
        "fvg_types_h4_other": entry("зі зламом", "зі зламом"),
    }

    # Act
    result = guard(config, output, current={"poi_types": ["fractal_h1"]})

    # Assert
    assert result.fields == {"poi_types": ["fvg_h1"]}
    assert result.dropped == [
        Dropped("fvg_types_h4", "parent_not_selected"),
        Dropped("fvg_types_h4_other", "parent_not_selected"),
    ]


def test_show_if_field_is_kept_when_the_current_parent_includes_the_option(
    config: JournalFieldsConfig,
) -> None:
    # Arrange: POI already saved on the trade, the text only names the FVG type
    output = {"fvg_types_h1": entry(["post_manipulation"], "FVG після маніпуляції")}

    # Act
    kept = guard(config, output, current={"poi_types": ["fvg_h1"]})
    without_current = guard(config, output)

    # Assert
    assert kept.fields == {"fvg_types_h1": ["post_manipulation"]}
    assert without_current.dropped == [Dropped("fvg_types_h1", "parent_not_selected")]


def test_entry_model_other_keeps_his_words(config: JournalFieldsConfig) -> None:
    # Arrange
    output = {
        "entry_model": entry("other", "Вхід інше"),
        "entry_model_other": entry("по своїй моделі зі зламом", "по своїй моделі зі зламом"),
    }

    # Act
    result = guard(config, output)

    # Assert
    assert result.fields == {
        "entry_model": "other",
        "entry_model_other": "по своїй моделі зі зламом",
    }


def test_legacy_key_from_the_model_is_not_fillable(config: JournalFieldsConfig) -> None:
    result = guard(config, {"setup_context": entry("yes", "Флоу на H1")})

    assert result.fields == {}
    assert result.dropped == [Dropped("setup_context", "not_fillable")]
