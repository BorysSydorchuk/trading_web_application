"""The read-only guarantee: trading messages cannot leave the cTrader client."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.ctrader import guard, protocol
from app.ctrader.connection import CtraderConnection
from app.ctrader.errors import CtraderError
from tests.ctrader_fakes import FakeConnector, FakeTransport

CTRADER_DIR = Path(guard.__file__).resolve().parent
# A field of a received deal (read-only data), not a message: the only name exception.
READ_ONLY_FIELD = "closepositiondetail"
TRADING_TYPES = (2106, 2108, 2109, 2110, 2111)
TRADING_NAMES = (
    "NewOrder",
    "CancelOrder",
    "AmendOrder",
    "AmendPositionSLTP",
    "ClosePosition",
    "NEW_ORDER",
    "CANCEL_ORDER",
    "AMEND_ORDER",
    "AMEND_POSITION",
    "CLOSE_POSITION",
)


def test_allowlist_is_exactly_the_read_only_set() -> None:
    assert (
        frozenset({51, 2100, 2102, 2114, 2116, 2121, 2124, 2133, 2149, 2187})
        == guard.ALLOWED_OUTGOING
    )


def test_every_outgoing_protocol_constant_is_on_the_allowlist() -> None:
    outgoing = {
        value
        for name, value in vars(protocol).items()
        if name.endswith("_REQ") or name == "HEARTBEAT"
    }
    assert outgoing == guard.ALLOWED_OUTGOING


def test_allowlist_contains_no_trading_message() -> None:
    assert not guard.ALLOWED_OUTGOING & set(TRADING_TYPES)
    assert set(TRADING_TYPES) <= guard.BLOCKED_OUTGOING


@pytest.mark.parametrize("payload_type", [*TRADING_TYPES, 2112, 0, -1, 999999])
def test_guard_refuses_everything_else(payload_type: int) -> None:
    with pytest.raises(guard.ForbiddenMessageError):
        guard.assert_allowed(payload_type)


@pytest.mark.parametrize("value", [True, "2100", 2100.0, None])
def test_guard_refuses_a_non_int_type(value: object) -> None:
    with pytest.raises(guard.ForbiddenMessageError):
        guard.assert_allowed(value)


@pytest.mark.parametrize("payload_type", TRADING_TYPES)
def test_send_raises_before_anything_is_written(payload_type: int) -> None:
    async def scenario() -> FakeTransport:
        transport = FakeTransport({})
        connection = CtraderConnection("wss://fake", FakeConnector(transport))
        await connection.start()
        try:
            with pytest.raises(guard.ForbiddenMessageError):
                await connection.request(payload_type, {}, 0)
        finally:
            await connection.close()
        return transport

    assert asyncio.run(scenario()).sent == []


def test_forbidden_message_is_not_a_retryable_client_error() -> None:
    assert not issubclass(guard.ForbiddenMessageError, CtraderError)


def _sources_outside_guard() -> list[Path]:
    return [p for p in CTRADER_DIR.rglob("*.py") if p.name != "guard.py"]


def test_source_scan_finds_the_package() -> None:
    assert len(_sources_outside_guard()) >= 5


@pytest.mark.parametrize("number", TRADING_TYPES)
def test_no_trading_number_outside_the_guard(number: int) -> None:
    pattern = re.compile(rf"(?<!\d){number}(?!\d)")
    hits = [p.name for p in _sources_outside_guard() if pattern.search(_text(p))]
    assert hits == []


@pytest.mark.parametrize("name", TRADING_NAMES)
def test_no_trading_message_name_outside_the_guard(name: str) -> None:
    hits = [p.name for p in _sources_outside_guard() if name.lower() in _scannable(p)]
    assert hits == []


def test_the_only_name_exception_is_the_close_detail_field() -> None:
    """``closePositionDetail`` is a field of a received deal (read-only data), not a message."""
    for name in ("history.py", "convert.py"):
        assert READ_ONLY_FIELD in _text(CTRADER_DIR / name).lower()
        assert "closeposition" not in _scannable(CTRADER_DIR / name)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scannable(path: Path) -> str:
    return _text(path).lower().replace(READ_ONLY_FIELD, "")
