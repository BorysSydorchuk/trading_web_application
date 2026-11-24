"""cTrader phase c, pure parts (docs/api.md "cTrader integration, phase c"): protocol constants,
c1 spec mapping and c2 tick decoding. Fixture JSON only; values are synthetic."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.ctrader import guard, protocol
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.specs import spec_from_symbol
from app.ctrader.ticks import CtTick, decode_ticks
from app.mt5.types import RawSymbolSpec
from tests.ctrader_history_fakes import load

D = Decimal
ASSETS = {1: "EUR", 2: "USD", 30: "DE40", 40: "XAU"}


def _fixture(symbol_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load("symbols.json")
    light = next(s for s in data["list"]["symbol"] if s["symbolId"] == symbol_id)
    full = next(s for s in data["byId"]["symbol"] if s["symbolId"] == symbol_id)
    return light, full


def test_protocol_has_the_phase_c_message_constants() -> None:
    assert (protocol.ASSET_LIST_REQ, protocol.ASSET_LIST_RES) == (2112, 2113)
    assert (protocol.TRENDBARS_REQ, protocol.TRENDBARS_RES) == (2137, 2138)
    assert (protocol.TICK_DATA_REQ, protocol.TICK_DATA_RES) == (2145, 2146)
    assert {2112, 2137, 2145} <= guard.ALLOWED_OUTGOING


# --- c1: spec_from_symbol -------------------------------------------------------------------


def test_eurusd_cents_become_lots_and_exact_decimals() -> None:
    light, full = _fixture(1)
    spec = spec_from_symbol(light, full, ASSETS)
    assert spec == RawSymbolSpec(
        name="EURUSD",
        digits=5,
        contract_size=D("100000"),  # lotSize 10000000 cents of a unit / 100
        tick_size=D("0.00001"),
        tick_value=D("1"),  # contract_size * tick_size, in the profit currency
        volume_min=D("0.01"),  # 100000 / 10000000
        volume_step=D("0.01"),
        volume_max=D("1000"),  # 10000000000 / 10000000
        currency_profit="USD",
        currency_margin="EUR",
        point=D("0.00001"),
        tick_value_loss=D("1"),
    )
    assert isinstance(spec, RawSymbolSpec)
    assert spec.tick_size == D(1).scaleb(-5)  # exact, never a float


def test_xauusd_contract_is_100() -> None:
    light, full = _fixture(41)
    spec = spec_from_symbol(light, full, ASSETS)
    assert spec is not None
    assert (spec.digits, spec.contract_size, spec.tick_size, spec.tick_value) == (
        2,
        D("100"),
        D("0.01"),
        D("1"),
    )
    assert (spec.volume_min, spec.volume_step, spec.volume_max) == (D("0.01"), D("0.01"), D("100"))
    assert (spec.currency_profit, spec.currency_margin) == ("USD", "XAU")


def test_index_in_eur_keeps_the_broker_name_and_the_cross_profit_currency() -> None:
    light, full = _fixture(2)  # DE40, quoted in EUR (a USD account makes it cross-currency)
    spec = spec_from_symbol(light, full, ASSETS)
    assert spec is not None
    assert spec.name == "DE40"  # the canonical name GER40 is applied when written
    assert (spec.digits, spec.contract_size, spec.tick_size, spec.point) == (
        1,
        D("1"),
        D("0.1"),
        D("0.1"),
    )
    assert (spec.tick_value, spec.tick_value_loss) == (D("0.1"), D("0.1"))
    assert (spec.volume_min, spec.volume_step, spec.volume_max) == (D("0.1"), D("0.1"), D("1000"))
    assert (spec.currency_profit, spec.currency_margin) == ("EUR", "DE40")


def test_zero_digits_means_a_tick_of_one() -> None:
    light, full = _fixture(2)
    spec = spec_from_symbol(light, dict(full, digits=0), ASSETS)
    assert spec is not None
    assert (spec.digits, spec.tick_size) == (0, D("1"))


@pytest.mark.parametrize(
    "broken",
    [
        {"lotSize": None},
        {"lotSize": 0},
        {"lotSize": -100},
        {"digits": None},
        {"digits": -1},
        {"minVolume": None},
        {"minVolume": 0},
        {"stepVolume": 0},
        {"stepVolume": -10},
        {"maxVolume": None},
        {"maxVolume": 0},
        {"lotSize": "abc"},
        {"lotSize": True},
    ],
)
def test_missing_or_non_positive_field_gives_none_and_a_warning(
    broken: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    light, full = _fixture(1)
    changed = {k: v for k, v in (full | broken).items() if v is not None}
    with caplog.at_level(logging.WARNING):
        assert spec_from_symbol(light, changed, ASSETS) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "EURUSD" in warnings[0].getMessage()


@pytest.mark.parametrize("asset_ids", [{}, {"quoteAssetId": 999}, {"baseAssetId": 999}])
def test_unknown_asset_gives_none_and_a_warning(
    asset_ids: dict[str, int], caplog: pytest.LogCaptureFixture
) -> None:
    light, full = _fixture(1)
    assets = {} if not asset_ids else ASSETS
    with caplog.at_level(logging.WARNING):
        assert spec_from_symbol(light | asset_ids, full, assets) is None
    assert [r for r in caplog.records if r.levelno == logging.WARNING]


def test_blank_symbol_name_gives_none() -> None:
    light, full = _fixture(1)
    assert spec_from_symbol(dict(light, symbolName="  "), full, ASSETS) is None


def test_mapping_does_not_change_its_inputs() -> None:
    light, full = _fixture(1)
    before = (dict(light), dict(full), dict(ASSETS))
    spec_from_symbol(light, full, ASSETS)
    assert (light, full, ASSETS) == before


# --- c2: tick decoding (delta encoded) ---------------------------------------------------------


def test_decode_ticks_first_entry_absolute_later_entries_deltas() -> None:
    # ASSUMPTION (Open API docs, to confirm live): ProtoOATickData.timestamp (ms) and .tick
    # (price * 100000) are absolute in the first entry and deltas to the previous one after it.
    entries = [
        {"timestamp": 1795434000000, "tick": 108010},
        {"timestamp": 300000, "tick": 10},  # +5 min, +0.00010
        {"timestamp": 300000, "tick": 14},  # +5 min, +0.00014
    ]
    assert decode_ticks(entries) == (
        CtTick(datetime(2026, 11, 23, 11, 40, tzinfo=UTC), D("1.08010")),
        CtTick(datetime(2026, 11, 23, 11, 45, tzinfo=UTC), D("1.08020")),
        CtTick(datetime(2026, 11, 23, 11, 50, tzinfo=UTC), D("1.08034")),
    )


def test_decode_ticks_negative_price_delta_and_exact_decimal() -> None:
    entries = [{"timestamp": 1795434000000, "tick": 108020}, {"timestamp": 1000, "tick": -10}]
    ticks = decode_ticks(entries)
    assert [t.price for t in ticks] == [D("1.08020"), D("1.08010")]
    assert all(isinstance(t.price, Decimal) for t in ticks)


def test_decode_ticks_empty_is_empty() -> None:
    assert decode_ticks([]) == ()


@pytest.mark.parametrize(
    "entries",
    [[{"timestamp": 1795434000000}], [{"tick": 108010}], [{"timestamp": "x", "tick": 1}], [3]],
)
def test_decode_ticks_refuses_malformed_entries(entries: list[Any]) -> None:
    with pytest.raises(CtraderError) as raised:
        decode_ticks(entries)
    assert raised.value.code is CtraderErrorCode.BAD_RESPONSE
