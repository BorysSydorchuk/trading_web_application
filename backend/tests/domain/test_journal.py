"""YAML-driven journal logic (app.domain.journal): pure, no DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.config_files.journal_fields import JournalFieldsConfig, load_journal_fields
from app.domain.journal import (
    TEXT_MAX_LENGTH,
    InvalidJournalValue,
    RequirementScope,
    ai_fillable_keys,
    filter_ai_filled,
    journal_keys,
    merge_extra,
    missing_new_fields,
    missing_required,
    normalise_value,
    required_field_keys,
    split_storage,
    validate_fields,
    visible_journal,
    writable_keys,
)


@pytest.fixture(scope="module")
def real() -> JournalFieldsConfig:
    return load_journal_fields()


def make_config(*fields: dict[str, Any]) -> JournalFieldsConfig:
    """A config without the Trade-model cross-checks (the domain module never needs them)."""
    return JournalFieldsConfig.model_validate({"fields": list(fields)})


MOOD = {
    "key": "mood",
    "label": "Настрій",
    "type": "enum",
    "options": [
        {"value": "good", "label": "добре"},
        {"value": "old", "label": "старе", "deprecated": True},
        {"value": "other", "label": "інше"},
    ],
    "required": True,
    "analytics": True,
    "storage": "extra",
    "text_key": "mood_other",
    "allow_other_text": True,
}
TAGS = {
    "key": "tags",
    "label": "Теги",
    "type": "multi_enum",
    "options": [
        {"value": "a", "label": "A"},
        {"value": "b", "label": "B"},
        {"value": "gone", "label": "G", "deprecated": True},
    ],
    "required": False,
    "analytics": True,
    "storage": "extra",
}
SCORE = {
    "key": "score",
    "label": "Оцінка",
    "type": "int",
    "min": 1,
    "max": 5,
    "required": False,
    "analytics": True,
    "storage": "extra",
}
FLAG = {
    "key": "flag",
    "label": "Прапор",
    "type": "bool",
    "required": True,
    "analytics": False,
    "storage": "extra",
}
NOTE = {
    "key": "note",
    "label": "Нотатка",
    "type": "text",
    "required": False,
    "analytics": False,
    "storage": "extra",
}
FEEL = {
    "key": "feel",
    "label": "Відчуття",
    "type": "enum",
    "options": [{"value": "calm", "label": "спокій"}],
    "required": False,
    "analytics": True,
    "storage": "extra",
    "text_key": "feel_text",
    "allow_other_text": False,
}


@pytest.fixture
def cfg() -> JournalFieldsConfig:
    return make_config(MOOD, TAGS, SCORE, FLAG, NOTE, FEEL)


def spec(config: JournalFieldsConfig, key: str) -> Any:
    return next(k for k in journal_keys(config) if k.key == key)


# --- keys ---


def test_journal_keys_in_yaml_order_with_text_keys(real: JournalFieldsConfig) -> None:
    keys = [k.key for k in journal_keys(real)]
    assert keys[:4] == ["setup_context", "poi_type", "poi_type_other", "fvg_kind"]
    assert keys.index("emotion_before_text") == keys.index("emotion_before") + 1
    assert keys[-1] == "chart_links"


def test_writable_keys_exclude_auto_and_links(real: JournalFieldsConfig) -> None:
    keys = {k.key for k in writable_keys(real)}
    assert "bias_alignment" not in keys
    assert "chart_links" not in keys
    assert {"rule_violations", "poi_type_other", "quality_rating"} <= keys


def test_ai_fillable_keys_exclude_rule_violations(real: JournalFieldsConfig) -> None:
    keys = [k.key for k in ai_fillable_keys(real)]
    assert "rule_violations" not in keys
    assert "bias_alignment" not in keys
    assert "chart_links" not in keys
    assert keys[:3] == ["setup_context", "poi_type", "poi_type_other"]
    assert "emotion_after_text" in keys


def test_text_key_spec(real: JournalFieldsConfig) -> None:
    other = spec(real, "poi_type_other")
    assert (other.type, other.is_text_key, other.other_only) == ("text", True, True)
    note = spec(real, "emotion_before_text")
    assert (note.type, note.other_only) == ("text", False)
    assert spec(real, "rule_violations").is_relation
    assert not spec(real, "setup_context").is_relation


# --- normalise_value per type ---


def issue_code(config: JournalFieldsConfig, key: str, value: Any, current: Any = None) -> str:
    with pytest.raises(InvalidJournalValue) as exc:
        normalise_value(spec(config, key), value, current)
    return exc.value.issue.code


def test_enum(cfg: JournalFieldsConfig) -> None:
    assert normalise_value(spec(cfg, "mood"), "good") == "good"
    assert normalise_value(spec(cfg, "mood"), None) is None
    assert issue_code(cfg, "mood", "nope") == "invalid_option"
    assert issue_code(cfg, "mood", 1) == "invalid_type"
    assert issue_code(cfg, "mood", ["good"]) == "invalid_type"


def test_enum_deprecated_only_when_already_stored(cfg: JournalFieldsConfig) -> None:
    assert issue_code(cfg, "mood", "old") == "deprecated_option"
    assert issue_code(cfg, "mood", "old", current="good") == "deprecated_option"
    assert normalise_value(spec(cfg, "mood"), "old", "old") == "old"


def test_multi_enum(cfg: JournalFieldsConfig) -> None:
    tags = spec(cfg, "tags")
    assert normalise_value(tags, ["b", "a"]) == ["b", "a"]
    assert normalise_value(tags, []) is None
    assert issue_code(cfg, "tags", ["a", "a"]) == "duplicate_option"
    assert issue_code(cfg, "tags", ["x"]) == "invalid_option"
    assert issue_code(cfg, "tags", "a") == "invalid_type"
    assert issue_code(cfg, "tags", [1]) == "invalid_type"
    assert issue_code(cfg, "tags", ["gone"]) == "deprecated_option"
    assert normalise_value(tags, ["a", "gone"], ["gone"]) == ["a", "gone"]


def test_bool(cfg: JournalFieldsConfig) -> None:
    assert normalise_value(spec(cfg, "flag"), False) is False
    assert normalise_value(spec(cfg, "flag"), True) is True
    for bad in (0, 1, "true", "так"):
        assert issue_code(cfg, "flag", bad) == "invalid_type"


def test_int(cfg: JournalFieldsConfig) -> None:
    assert normalise_value(spec(cfg, "score"), 1) == 1
    assert normalise_value(spec(cfg, "score"), 5) == 5
    assert issue_code(cfg, "score", 0) == "out_of_range"
    assert issue_code(cfg, "score", 6) == "out_of_range"
    for bad in (True, 4.0, "4"):
        assert issue_code(cfg, "score", bad) == "invalid_type"


def test_text(cfg: JournalFieldsConfig) -> None:
    note = spec(cfg, "note")
    assert normalise_value(note, "  a b  ") == "a b"
    assert normalise_value(note, "   ") is None
    assert normalise_value(note, "x" * TEXT_MAX_LENGTH) == "x" * TEXT_MAX_LENGTH
    assert issue_code(cfg, "note", "x" * (TEXT_MAX_LENGTH + 1)) == "too_long"
    assert issue_code(cfg, "note", 5) == "invalid_type"
    # text_keys are text too
    assert normalise_value(spec(cfg, "mood_other"), " OB ") == "OB"


# --- validate_fields ---


def test_validate_fields_full_replacement(cfg: JournalFieldsConfig) -> None:
    result = validate_fields(cfg, {"mood": "good", "flag": True}, {})
    assert result.errors == {}
    assert result.values == {
        "mood": "good",
        "mood_other": None,
        "tags": None,
        "score": None,
        "flag": True,
        "note": None,
        "feel": None,
        "feel_text": None,
    }


def test_validate_fields_unknown_and_not_writable(real: JournalFieldsConfig) -> None:
    result = validate_fields(
        real, {"nope": 1, "bias_alignment": "aligned", "chart_links": [], "extra": {}}, {}
    )
    assert {k: i.code for k, i in result.errors.items()} == {
        "nope": "unknown_key",
        "bias_alignment": "not_writable",
        "chart_links": "not_writable",
        "extra": "unknown_key",
    }


def test_validate_fields_collects_all_errors(cfg: JournalFieldsConfig) -> None:
    result = validate_fields(cfg, {"mood": "x", "score": 9, "flag": "y"}, {})
    assert set(result.errors) == {"mood", "score", "flag"}
    assert all(issue.message for issue in result.errors.values())


def test_other_text_cleared_unless_parent_other(cfg: JournalFieldsConfig) -> None:
    kept = validate_fields(cfg, {"mood": "other", "mood_other": " OB "}, {})
    assert kept.values["mood_other"] == "OB"
    cleared = validate_fields(cfg, {"mood": "good", "mood_other": "OB"}, {})
    assert cleared.errors == {}
    assert cleared.values["mood_other"] is None
    no_parent = validate_fields(cfg, {"mood_other": "OB"}, {})
    assert no_parent.values["mood_other"] is None


def test_note_text_key_kept_for_any_value(cfg: JournalFieldsConfig) -> None:
    result = validate_fields(cfg, {"feel": "calm", "feel_text": "ok"}, {})
    assert result.values["feel_text"] == "ok"
    # allow_other_text: false → an optional note even without a value.
    assert validate_fields(cfg, {"feel_text": "ok"}, {}).values["feel_text"] == "ok"


def test_validate_fields_deprecated_uses_current(cfg: JournalFieldsConfig) -> None:
    assert "mood" in validate_fields(cfg, {"mood": "old"}, {}).errors
    assert validate_fields(cfg, {"mood": "old"}, {"mood": "old"}).errors == {}


# --- missing_required ---


def test_missing_required_order_and_links(real: JournalFieldsConfig) -> None:
    assert missing_required(real, {}, has_before_link=False) == [
        "setup_context",
        "poi_type",
        "fvg_kind",
        "entry_model",
        "exit_reason",
        "followed_plan",
        "emotion_before",
        "emotion_after",
        "quality_rating",
        "chart_links",
    ]


def test_missing_required_complete(real: JournalFieldsConfig) -> None:
    values = {
        "setup_context": "yes",
        "poi_type": "fvg_h4",
        "fvg_kind": "na",
        "entry_model": "ifvg_m5",
        "exit_reason": "tp",
        "followed_plan": False,  # False is a value, not missing
        "emotion_before": "calm",
        "emotion_after": "calm",
        "quality_rating": 3,
    }
    assert missing_required(real, values, has_before_link=True) == []
    assert missing_required(real, values, has_before_link=False) == ["chart_links"]


def test_missing_required_other_text(real: JournalFieldsConfig) -> None:
    missing = missing_required(real, {"poi_type": "other"}, has_before_link=True)
    assert missing[:3] == ["setup_context", "poi_type_other", "fvg_kind"]
    filled = {"poi_type": "other", "poi_type_other": "OB"}
    assert "poi_type_other" not in missing_required(real, filled, has_before_link=True)


def test_missing_required_links_not_required() -> None:
    links = {
        "key": "chart_links",
        "label": "L",
        "type": "links",
        "options": [{"value": "before", "label": "до"}],
        "required": False,
        "analytics": False,
        "storage": "column",
    }
    assert missing_required(make_config(NOTE, links), {}, has_before_link=False) == []


# --- storage ---


def test_split_storage(real: JournalFieldsConfig) -> None:
    values = validate_fields(real, {"setup_context": "yes", "rule_violations": ["x"]}, {}).values
    columns, extra = split_storage(real, values)
    assert columns["setup_context"] == "yes"
    assert "poi_type_other" in columns
    assert "rule_violations" not in columns  # relation, saved separately
    assert extra == {}


def test_split_storage_extra(cfg: JournalFieldsConfig) -> None:
    values = validate_fields(cfg, {"mood": "other", "mood_other": "x"}, {}).values
    columns, extra = split_storage(cfg, values)
    assert columns == {}
    assert extra["mood"] == "other"
    assert extra["mood_other"] == "x"
    assert extra["note"] is None


def test_merge_extra_keeps_unknown_drops_cleared(cfg: JournalFieldsConfig) -> None:
    old = {"legacy": 1, "mood": "good", "note": "n"}
    merged = merge_extra(cfg, old, {"mood": "other", "note": None, "tags": ["a"]})
    assert merged == {"legacy": 1, "mood": "other", "tags": ["a"]}
    assert old == {"legacy": 1, "mood": "good", "note": "n"}  # not mutated


# --- visible journal / ai_filled ---


def test_visible_journal_every_key_null_when_empty(real: JournalFieldsConfig) -> None:
    journal = visible_journal(real, {"setup_context": "yes", "rule_violations": [], "x": 1})
    assert journal["setup_context"] == "yes"
    assert journal["rule_violations"] is None
    assert journal["bias_alignment"] is None
    assert "x" not in journal
    assert "chart_links" not in journal  # links live in TradeDetail.chart_links
    expected = {k.key for k in journal_keys(real) if k.type != "links"}
    assert set(journal) == expected


def test_filter_ai_filled() -> None:
    values = {"a": "x", "b": None, "c": False}
    assert filter_ai_filled(["c", "a", "b", "zzz", "a"], values) == ["c", "a"]


def test_new_extra_field_is_picked_up_everywhere(cfg: JournalFieldsConfig) -> None:
    extended = make_config(MOOD, TAGS, SCORE, FLAG, NOTE, FEEL, {**NOTE, "key": "newbie"})
    assert "newbie" in {k.key for k in writable_keys(extended)}
    assert "newbie" in {k.key for k in ai_fillable_keys(extended)}
    assert "newbie" in visible_journal(extended, {})


# --- required since (M3 "New required fields") ---

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CHANGE = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
ALL_REQUIRED = (
    "setup_context",
    "poi_type",
    "fvg_kind",
    "entry_model",
    "exit_reason",
    "followed_plan",
    "emotion_before",
    "emotion_after",
    "quality_rating",
    "chart_links",
)


def since_map(**new: datetime) -> dict[str, datetime]:
    """Every required field since 1970, except the given ones."""
    return dict.fromkeys(ALL_REQUIRED, EPOCH) | new


def test_required_field_keys_yaml_order(real: JournalFieldsConfig) -> None:
    assert required_field_keys(real) == ALL_REQUIRED


@pytest.mark.parametrize(
    ("close_time", "counts"),
    [
        (CHANGE - timedelta(microseconds=1), False),
        (CHANGE, True),  # boundary: close_time == required_since counts
        (CHANGE + timedelta(seconds=1), True),
    ],
)
def test_missing_required_respects_required_since(
    real: JournalFieldsConfig, close_time: datetime, counts: bool
) -> None:
    scope = RequirementScope(since_map(quality_rating=CHANGE), close_time)
    missing = missing_required(real, {}, has_before_link=False, scope=scope)
    assert ("quality_rating" in missing) is counts
    assert "setup_context" in missing  # required since 1970 always counts
    new = missing_new_fields(real, {}, has_before_link=False, scope=scope)
    assert new == ([] if counts else ["quality_rating"])


def test_links_field_follows_required_since(real: JournalFieldsConfig) -> None:
    scope = RequirementScope(since_map(chart_links=CHANGE), CHANGE - timedelta(days=1))
    assert "chart_links" not in missing_required(real, {}, has_before_link=False, scope=scope)
    assert missing_new_fields(real, {}, has_before_link=False, scope=scope) == ["chart_links"]
    assert missing_new_fields(real, {}, has_before_link=True, scope=scope) == []


def test_missing_new_fields_yaml_order_and_only_empty(real: JournalFieldsConfig) -> None:
    scope = RequirementScope(
        since_map(quality_rating=CHANGE, setup_context=CHANGE, poi_type=CHANGE),
        CHANGE - timedelta(hours=1),
    )
    values = {"poi_type": "fvg_h4"}
    assert missing_new_fields(real, values, has_before_link=True, scope=scope) == [
        "setup_context",
        "quality_rating",
    ]


def test_other_text_rule_not_affected_by_required_since(real: JournalFieldsConfig) -> None:
    scope = RequirementScope(since_map(poi_type=CHANGE), CHANGE - timedelta(days=1))
    missing = missing_required(real, {"poi_type": "other"}, has_before_link=True, scope=scope)
    assert "poi_type_other" in missing
    assert "poi_type" not in missing


def test_open_trade_scope_counts_everything(real: JournalFieldsConfig) -> None:
    scope = RequirementScope(since_map(quality_rating=CHANGE), None)
    assert "quality_rating" in missing_required(real, {}, has_before_link=False, scope=scope)
    assert missing_new_fields(real, {}, has_before_link=False, scope=scope) == []


def test_field_without_known_date_counts(real: JournalFieldsConfig) -> None:
    scope = RequirementScope({}, CHANGE)
    assert missing_required(real, {}, has_before_link=False, scope=scope) == list(ALL_REQUIRED)
    assert missing_new_fields(real, {}, has_before_link=False, scope=scope) == []
