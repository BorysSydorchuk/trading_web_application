"""M8-04..M8-08 engine (docs/api.md "Journal taxonomy batch"): `show_if`, `legacy`,
multi_enum with a trades column and `allow_other_text` on multi_enum. Pure, no DB.

RED phase: these tests describe the new behaviour of app.domain.journal and the field model.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.journal import (
    ai_fillable_keys,
    journal_keys,
    missing_required,
    split_storage,
    validate_fields,
    visible_journal,
    writable_keys,
)


def make_config(*fields: dict[str, Any]) -> JournalFieldsConfig:
    """A config without the Trade-model cross-checks (the domain never needs them)."""
    return JournalFieldsConfig.model_validate({"fields": list(fields)})


POI = {
    "key": "poi_types",
    "label": "POI",
    "type": "multi_enum",
    "options": [
        {"value": "fvg_h1", "label": "FVG H1"},
        {"value": "fvg_h4", "label": "FVG H4"},
        {"value": "other", "label": "Інше"},
    ],
    "required": True,
    "analytics": True,
    "storage": "column",
    "text_key": "poi_types_other",
    "allow_other_text": True,
}
FVG_H1 = {
    "key": "fvg_types_h1",
    "label": "Тип FVG H1",
    "type": "multi_enum",
    "options": [
        {"value": "fractal_updating", "label": "оновлює фрактал"},
        {"value": "post_manipulation", "label": "після маніпуляції"},
        {"value": "other", "label": "Інше"},
    ],
    "required": True,
    "analytics": True,
    "storage": "column",
    "text_key": "fvg_types_h1_other",
    "allow_other_text": True,
    "show_if": {"field": "poi_types", "includes": "fvg_h1"},
}
CTX = {
    "key": "ctx",
    "label": "Контекст",
    "type": "enum",
    "options": [
        {"value": "flow", "label": "Flow"},
        {"value": "reversal", "label": "Reversal"},
    ],
    "required": True,
    "analytics": True,
    "storage": "column",
}
CTX_DETAIL = {
    "key": "ctx_detail",
    "label": "Деталі",
    "type": "enum",
    "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
    "required": True,
    "analytics": False,
    "storage": "column",
    "text_key": "ctx_detail_note",
    "allow_other_text": False,
    "show_if": {"field": "ctx", "includes": "reversal"},
}
LEGACY = {
    "key": "old_ctx",
    "label": "Старе",
    "type": "enum",
    "options": [{"value": "yes", "label": "так"}, {"value": "no", "label": "ні"}],
    "required": False,
    "analytics": False,
    "storage": "column",
    "legacy": True,
}


@pytest.fixture
def poi_cfg() -> JournalFieldsConfig:
    return make_config(POI, FVG_H1)


@pytest.fixture
def ctx_cfg() -> JournalFieldsConfig:
    return make_config(CTX, CTX_DETAIL)


@pytest.fixture
def legacy_cfg() -> JournalFieldsConfig:
    return make_config(POI, LEGACY)


# --- show_if: enum parent equals ---


def test_enum_parent_equal_keeps_child_value(ctx_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(
        ctx_cfg, {"ctx": "reversal", "ctx_detail": "a", "ctx_detail_note": "why"}, {}
    )

    assert result.errors == {}
    assert result.values["ctx_detail"] == "a"
    assert result.values["ctx_detail_note"] == "why"


def test_enum_parent_other_value_stores_child_and_its_text_as_none(
    ctx_cfg: JournalFieldsConfig,
) -> None:
    result = validate_fields(
        ctx_cfg, {"ctx": "flow", "ctx_detail": "a", "ctx_detail_note": "why"}, {}
    )

    assert result.errors == {}
    assert result.values["ctx_detail"] is None
    assert result.values["ctx_detail_note"] is None


def test_enum_parent_empty_hides_child(ctx_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(ctx_cfg, {"ctx_detail": "b"}, {})

    assert result.errors == {}
    assert result.values["ctx_detail"] is None


# --- show_if: multi parent contains ---


def test_multi_parent_containing_option_keeps_child(poi_cfg: JournalFieldsConfig) -> None:
    fields = {"poi_types": ["fvg_h1"], "fvg_types_h1": ["post_manipulation"]}

    result = validate_fields(poi_cfg, fields, {})

    assert result.errors == {}
    assert result.values["fvg_types_h1"] == ["post_manipulation"]


def test_multi_parent_without_option_clears_child_and_text(poi_cfg: JournalFieldsConfig) -> None:
    fields = {
        "poi_types": ["fvg_h4"],
        "fvg_types_h1": ["other"],
        "fvg_types_h1_other": "щось",
    }

    result = validate_fields(poi_cfg, fields, {})

    assert result.errors == {}
    assert result.values["fvg_types_h1"] is None
    assert result.values["fvg_types_h1_other"] is None


def test_child_visibility_uses_the_parent_value_of_the_same_save(
    poi_cfg: JournalFieldsConfig,
) -> None:
    current = {"poi_types": ["fvg_h1"], "fvg_types_h1": ["post_manipulation"]}

    result = validate_fields(poi_cfg, {"poi_types": ["fvg_h4"]}, current)

    assert result.values["fvg_types_h1"] is None


def test_hidden_child_with_unchanged_value_is_not_an_error(poi_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(poi_cfg, {"poi_types": ["fvg_h4"], "fvg_types_h1": None}, {})

    assert result.errors == {}


# --- show_if: required only while shown ---


def test_hidden_required_field_is_not_missing(poi_cfg: JournalFieldsConfig) -> None:
    values = {"poi_types": ["fvg_h4"], "fvg_types_h1": None}

    assert missing_required(poi_cfg, values, has_before_link=True) == []


def test_shown_required_field_is_missing_when_empty(poi_cfg: JournalFieldsConfig) -> None:
    values = {"poi_types": ["fvg_h1"], "fvg_types_h1": None}

    assert missing_required(poi_cfg, values, has_before_link=True) == ["fvg_types_h1"]


def test_shown_required_field_filled_is_not_missing(poi_cfg: JournalFieldsConfig) -> None:
    values = {"poi_types": ["fvg_h1"], "fvg_types_h1": ["fractal_updating"]}

    assert missing_required(poi_cfg, values, has_before_link=True) == []


def test_enum_parent_shown_required_child(ctx_cfg: JournalFieldsConfig) -> None:
    shown = {"ctx": "reversal", "ctx_detail": None}
    hidden = {"ctx": "flow", "ctx_detail": None}

    assert missing_required(ctx_cfg, shown, has_before_link=True) == ["ctx_detail"]
    assert missing_required(ctx_cfg, hidden, has_before_link=True) == []


def test_hidden_child_with_a_stale_stored_value_never_blocks(ctx_cfg: JournalFieldsConfig) -> None:
    values = {"ctx": "flow", "ctx_detail": "a"}

    assert missing_required(ctx_cfg, values, has_before_link=True) == []


# --- legacy ---


def test_legacy_field_is_not_writable(legacy_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(legacy_cfg, {"poi_types": ["fvg_h1"], "old_ctx": "yes"}, {})

    assert result.errors["old_ctx"].code == "not_writable"
    assert "old_ctx" not in result.values


def test_legacy_field_left_out_is_no_error_and_not_written(legacy_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(legacy_cfg, {"poi_types": ["fvg_h1"]}, {"old_ctx": "no"})

    assert result.errors == {}
    assert "old_ctx" not in result.values


def test_legacy_field_is_not_a_writable_or_ai_fillable_key(legacy_cfg: JournalFieldsConfig) -> None:
    assert "old_ctx" not in {k.key for k in writable_keys(legacy_cfg)}
    assert "old_ctx" not in {k.key for k in ai_fillable_keys(legacy_cfg)}


def test_legacy_field_is_still_a_journal_key(legacy_cfg: JournalFieldsConfig) -> None:
    assert "old_ctx" in {k.key for k in journal_keys(legacy_cfg)}


def test_legacy_field_is_never_missing(legacy_cfg: JournalFieldsConfig) -> None:
    values = {"poi_types": ["fvg_h1"], "old_ctx": None}

    assert missing_required(legacy_cfg, values, has_before_link=True) == []


def test_legacy_value_is_in_visible_journal(legacy_cfg: JournalFieldsConfig) -> None:
    journal = visible_journal(legacy_cfg, {"poi_types": None, "old_ctx": "no"})

    assert journal["old_ctx"] == "no"


def test_legacy_field_is_not_split_into_storage(legacy_cfg: JournalFieldsConfig) -> None:
    columns, extra = split_storage(legacy_cfg, {"poi_types": ["fvg_h1"], "old_ctx": "yes"})

    assert "old_ctx" not in columns
    assert "old_ctx" not in extra


# --- multi_enum with a column ---


def test_multi_enum_column_empty_list_is_normalised_to_none(poi_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(poi_cfg, {"poi_types": []}, {})

    assert result.errors == {}
    assert result.values["poi_types"] is None


def test_multi_enum_column_keeps_order_of_values(poi_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(poi_cfg, {"poi_types": ["fvg_h4", "fvg_h1"]}, {})

    assert result.values["poi_types"] == ["fvg_h4", "fvg_h1"]


def test_multi_enum_column_required_means_at_least_one_value(
    poi_cfg: JournalFieldsConfig,
) -> None:
    assert missing_required(poi_cfg, {"poi_types": None}, has_before_link=True) == ["poi_types"]
    assert missing_required(poi_cfg, {"poi_types": []}, has_before_link=True) == ["poi_types"]
    assert missing_required(poi_cfg, {"poi_types": ["fvg_h4"]}, has_before_link=True) == []


def test_multi_enum_column_is_split_into_columns(poi_cfg: JournalFieldsConfig) -> None:
    columns, extra = split_storage(poi_cfg, {"poi_types": ["fvg_h4"], "fvg_types_h1": None})

    assert columns["poi_types"] == ["fvg_h4"]
    assert extra == {}


# --- allow_other_text on multi_enum ---


def test_multi_other_text_is_kept_when_other_is_in_the_list(poi_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(
        poi_cfg, {"poi_types": ["fvg_h4", "other"], "poi_types_other": "  OB H4  "}, {}
    )

    assert result.errors == {}
    assert result.values["poi_types_other"] == "OB H4"


def test_multi_other_text_is_cleared_without_other(poi_cfg: JournalFieldsConfig) -> None:
    result = validate_fields(poi_cfg, {"poi_types": ["fvg_h4"], "poi_types_other": "OB H4"}, {})

    assert result.errors == {}
    assert result.values["poi_types_other"] is None


def test_multi_other_without_text_blocks_complete(poi_cfg: JournalFieldsConfig) -> None:
    values = {"poi_types": ["fvg_h4", "other"], "poi_types_other": None}

    assert missing_required(poi_cfg, values, has_before_link=True) == ["poi_types_other"]


def test_multi_other_with_text_does_not_block(poi_cfg: JournalFieldsConfig) -> None:
    values = {"poi_types": ["other"], "poi_types_other": "OB"}

    assert missing_required(poi_cfg, values, has_before_link=True) == []


def test_multi_other_text_of_a_hidden_child_never_blocks(poi_cfg: JournalFieldsConfig) -> None:
    values = {
        "poi_types": ["fvg_h4"],
        "fvg_types_h1": ["other"],
        "fvg_types_h1_other": None,
    }

    assert missing_required(poi_cfg, values, has_before_link=True) == []


def test_shown_child_with_other_and_no_text_blocks(poi_cfg: JournalFieldsConfig) -> None:
    values = {
        "poi_types": ["fvg_h1"],
        "fvg_types_h1": ["other"],
        "fvg_types_h1_other": None,
    }

    assert missing_required(poi_cfg, values, has_before_link=True) == ["fvg_types_h1_other"]
