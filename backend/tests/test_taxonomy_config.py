"""M8-04..M8-08 config/journal_fields.yaml: engine validation (`show_if`, `legacy`) and the
real file's new taxonomy (docs/api.md "Journal taxonomy batch")."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config import REPO_ROOT
from app.config_files import ConfigError, get_journal_fields, reload_config
from app.config_files.journal_fields import load_journal_fields
from app.domain.journal import journal_keys, required_field_keys

ENTRY_MODEL: dict[str, Any] = {
    "key": "entry_model",
    "label": "Модель входу",
    "type": "enum",
    "options": [
        {"value": "ifvg_m5", "label": "IFVG M5"},
        {"value": "qm_m5", "label": "QM M5"},
        {"value": "other", "label": "Інше"},
    ],
    "required": True,
    "analytics": True,
    "storage": "column",
}


def field(key: str, type_: str = "enum", **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": key,
        "label": key,
        "type": type_,
        "required": False,
        "analytics": False,
        "storage": "extra",
    }
    if type_ in {"enum", "multi_enum"}:
        out["options"] = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]
    return out | kw


def load_variant(tmp_path: Path, *fields: dict[str, Any]) -> Any:
    path = tmp_path / "journal_fields.yaml"
    data = {"fields": [ENTRY_MODEL, *fields]}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return load_journal_fields(path)


def problems_of(tmp_path: Path, *fields: dict[str, Any]) -> str:
    with pytest.raises(ConfigError) as info:
        load_variant(tmp_path, *fields)
    message = str(info.value)
    # The rejection must come from a real rule, not from the unknown `show_if` / `legacy` key.
    assert "Extra inputs are not permitted" not in message
    return message


def show_if(parent: str, option: str) -> dict[str, str]:
    return {"field": parent, "includes": option}


# --- show_if validation ---


def test_valid_show_if_and_legacy_load(tmp_path: Path) -> None:
    config = load_variant(
        tmp_path,
        field("parent", "multi_enum"),
        field("child", "multi_enum", show_if=show_if("parent", "a"), required=True),
        field("enum_parent"),
        field("enum_child", show_if=show_if("enum_parent", "b")),
        field("old", legacy=True),
    )

    child = config.get("child")
    assert child is not None
    assert child.show_if.field == "parent"
    assert child.show_if.includes == "a"
    old = config.get("old")
    assert old is not None
    assert old.legacy is True


def test_show_if_unknown_parent_is_rejected(tmp_path: Path) -> None:
    message = problems_of(tmp_path, field("child", show_if=show_if("nope", "a")))

    assert "child" in message
    assert "nope" in message


def test_show_if_parent_later_in_yaml_is_rejected(tmp_path: Path) -> None:
    message = problems_of(
        tmp_path,
        field("child", show_if=show_if("parent", "a")),
        field("parent"),
    )

    assert "child" in message
    assert "parent" in message


def test_show_if_parent_with_its_own_show_if_is_rejected(tmp_path: Path) -> None:
    message = problems_of(
        tmp_path,
        field("grand"),
        field("parent", show_if=show_if("grand", "a")),
        field("child", show_if=show_if("parent", "a")),
    )

    assert "child" in message


def test_show_if_unknown_option_is_rejected(tmp_path: Path) -> None:
    message = problems_of(
        tmp_path, field("parent"), field("child", show_if=show_if("parent", "zzz"))
    )

    assert "child" in message
    assert "zzz" in message


@pytest.mark.parametrize("parent_type", ["bool", "int", "text"])
def test_show_if_parent_must_be_enum_or_multi_enum(tmp_path: Path, parent_type: str) -> None:
    message = problems_of(
        tmp_path,
        field("parent", parent_type),
        field("child", show_if=show_if("parent", "a")),
    )

    assert "child" in message


def test_show_if_on_itself_is_rejected(tmp_path: Path) -> None:
    message = problems_of(tmp_path, field("loop", show_if=show_if("loop", "a")))

    assert "loop" in message


def test_show_if_needs_both_parts(tmp_path: Path) -> None:
    message = problems_of(tmp_path, field("parent"), field("child", show_if={"field": "parent"}))

    assert "child" in message


# --- legacy validation ---


@pytest.mark.parametrize("flag", ["required", "analytics"])
def test_legacy_field_cannot_be_required_or_analytics(tmp_path: Path, flag: str) -> None:
    message = problems_of(tmp_path, field("old", legacy=True, **{flag: True}))

    assert "old" in message
    assert "legacy" in message


# --- real config/journal_fields.yaml ---


@pytest.fixture(scope="module")
def real() -> Any:
    reload_config()
    return get_journal_fields()


def option_values(real: Any, key: str) -> list[str]:
    return real.get(key).option_values()


def test_real_new_fields_in_form_order(real: Any) -> None:
    order = [k.key for k in journal_keys(real)]
    expected = [
        "h1_context",
        "h1_context_other",
        "h4_context",
        "h4_context_other",
        "poi_types",
        "poi_types_other",
        "fvg_types_h1",
        "fvg_types_h1_other",
        "fvg_types_h4",
        "fvg_types_h4_other",
        "entry_model",
        "entry_model_other",
    ]

    assert [k for k in order if k in expected] == expected


def test_real_context_fields(real: Any) -> None:
    for key, label in (("h1_context", "Контекст H1"), ("h4_context", "Контекст H4")):
        f = real.get(key)
        assert f is not None
        assert (f.label, f.type, f.required, f.analytics) == (label, "enum", True, True)
        assert f.option_values() == ["flow", "reversal", "range", "other"]
        assert f.text_key == f"{key}_other"
        assert f.allow_other_text is True
        assert f.show_if is None


def test_real_poi_types(real: Any) -> None:
    f = real.get("poi_types")

    assert (f.label, f.type, f.required, f.analytics) == ("POI", "multi_enum", True, True)
    assert f.storage == "column"
    assert f.option_values() == ["fvg_h4", "fvg_h1", "fractal_h1", "fractal_h4", "other"]
    assert f.text_key == "poi_types_other"
    assert f.allow_other_text is True


@pytest.mark.parametrize(
    ("key", "parent_option"), [("fvg_types_h1", "fvg_h1"), ("fvg_types_h4", "fvg_h4")]
)
def test_real_fvg_types_are_shown_by_poi(real: Any, key: str, parent_option: str) -> None:
    f = real.get(key)

    assert f.type == "multi_enum"
    assert (f.required, f.analytics, f.storage) == (True, True, "column")
    assert f.option_values() == ["fractal_updating", "post_manipulation", "other"]
    assert f.text_key == f"{key}_other"
    assert f.show_if.field == "poi_types"
    assert f.show_if.includes == parent_option


def test_real_entry_model_other_text(real: Any) -> None:
    f = real.get("entry_model")

    assert f.text_key == "entry_model_other"
    assert f.allow_other_text is True
    other = next(o for o in f.options if o.value == "other")
    assert other.label == "Інше"


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("setup_context", "Контекст (Flow H1 синхронний з H4)"),
        ("fvg_kind", "Тип FVG (старе)"),
    ],
)
def test_real_old_fields_are_legacy(real: Any, key: str, label: str) -> None:
    f = real.get(key)

    assert f.legacy is True
    assert f.label == label
    assert (f.required, f.analytics) == (False, False)


def test_real_setup_context_options_unchanged(real: Any) -> None:
    assert option_values(real, "setup_context") == ["yes", "no", "partially"]
    assert option_values(real, "fvg_kind") == ["fractal_updating", "post_manipulation", "na"]


def test_real_poi_type_left_the_yaml(real: Any) -> None:
    keys = {k.key for k in journal_keys(real)}

    assert "poi_type" not in keys
    assert "poi_type_other" not in keys


def test_real_required_keys(real: Any) -> None:
    required = set(required_field_keys(real))

    assert {"h1_context", "h4_context", "poi_types"} <= required
    assert not required & {"setup_context", "poi_type", "fvg_kind"}


def test_real_rule_violations_options_come_from_violations_yaml(real: Any) -> None:
    f = real.get("rule_violations")
    values = f.option_values()

    for key in (
        "max_risk_pct",
        "daily_risk",
        "weekly_risk",
        "max_trades_per_week",
        "max_reentries_per_idea",
        "min_planned_rr",
        "entry_session",
        "qm_not_in_ny",
        "no_breakeven",
        "entry_not_by_model",
        "entry_weak_poi",
        "entry_against_system",
    ):
        assert key in values
    deprecated = {o.value for o in f.options if o.deprecated}
    assert deprecated == {
        "daily_stop_loss_pct",
        "daily_stop_profit_pct",
        "weekly_stop_loss_pct",
        "weekly_stop_profit_pct",
    }


def test_journal_fields_yaml_has_no_inline_rule_violation_options() -> None:
    raw = yaml.safe_load((REPO_ROOT / "config" / "journal_fields.yaml").read_text(encoding="utf-8"))
    entry = next(f for f in raw["fields"] if f["key"] == "rule_violations")

    assert not entry.get("options")
