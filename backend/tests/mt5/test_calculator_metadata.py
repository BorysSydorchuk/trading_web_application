"""Synthetic broker metadata: capture actual values, never infer sizing inputs."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.mt5.real import spec_from_mt5
from app.mt5.types import RawSymbolSpec, from_json_dict, to_json_dict
from tests.mt5.factories import legacy_spec


def test_legacy_constructor_and_json_leave_new_metadata_unknown() -> None:
    old = legacy_spec()
    assert old.point is None
    assert old.tick_value_loss is None
    payload = to_json_dict(old)
    payload.pop("point")
    payload.pop("tick_value_loss")
    restored = from_json_dict(RawSymbolSpec, payload)
    assert restored == old


def test_actual_broker_fields_are_distinct_from_tick_size_and_generic_value() -> None:
    raw = spec_from_mt5(
        SimpleNamespace(
            name="GER40.cash",
            digits=1,
            point=0.1,
            trade_tick_size=0.5,
            trade_tick_value=2.0,
            trade_tick_value_loss=2.5,
        )
    )
    assert raw.point == Decimal("0.1")
    assert raw.tick_size == Decimal("0.5")
    assert raw.tick_value == Decimal("2")
    assert raw.tick_value_loss == Decimal("2.5")
    assert from_json_dict(RawSymbolSpec, to_json_dict(raw)) == raw


@pytest.mark.parametrize("metadata", [{}, {"point": None, "trade_tick_value_loss": None}])
def test_missing_broker_fields_are_not_manufactured(metadata: dict[str, object]) -> None:
    raw = spec_from_mt5(SimpleNamespace(digits=5, trade_tick_value=1.0, **metadata))
    assert raw.point is None
    assert raw.tick_value_loss is None


def test_broker_zero_is_preserved_for_later_sizing_validation() -> None:
    raw = spec_from_mt5(SimpleNamespace(point=0, trade_tick_value_loss=0))
    assert raw.point == Decimal("0")
    assert raw.tick_value_loss == Decimal("0")
