"""Pure parts of the margin requests service (no DB). docs/api.md M5-04d."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.errors import ApiError
from app.mt5.real import (
    CONNECT_GRACE_S,
    DEFAULT_CALL_TIMEOUT_S,
    RETRY_DELAY_S,
    SHUTDOWN_TIMEOUT_S,
)
from app.mt5.source import DEFAULT_CONNECT_TIMEOUT_S
from app.services.margin_requests import STALE_PROCESSING_S, check_storable

D = Decimal


def test_stale_bound_covers_the_worst_case_lookup() -> None:
    """connect (initialize + grace, account_info with one retry), calc_margin with one
    retry and shutdown must all fit before a processing row counts as stuck."""
    read_with_retry = 2 * DEFAULT_CALL_TIMEOUT_S + RETRY_DELAY_S
    worst = DEFAULT_CONNECT_TIMEOUT_S + CONNECT_GRACE_S + 2 * read_with_retry + SHUTDOWN_TIMEOUT_S
    assert isinstance(STALE_PROCESSING_S, int)
    assert worst < STALE_PROCESSING_S <= 10 * 60


@pytest.mark.parametrize(
    "value",
    [D("1"), D("0.00000001"), D("999999999999.99999999"), D("1.100000000"), D("1E+2")],
)
def test_storable_values_pass(value: Decimal) -> None:
    check_storable("entry", value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Not reachable through the API today (tick sizes and volume steps are stored with
        # 8 decimals and prices/volumes sit on their grid); guarded anyway.
        ("entry", D("1.123456789")),
        ("volume", D("0.000000001")),
        ("volume", D("1000000000000")),  # volume_max is NUMERIC(20, 8) too: unreachable
        # Reachable: see tests/test_margin_requests_api.py.
        ("entry", D("1000000000000")),
        ("entry", D("1E+12")),
    ],
)
def test_values_numeric_20_8_cannot_hold_are_422_naming_the_field(
    field: str, value: Decimal
) -> None:
    with pytest.raises(ApiError) as err:
        check_storable(field, value)

    assert (err.value.status_code, err.value.code) == (422, "validation_error")
    assert err.value.details is not None
    assert set(err.value.details["fields"]) == {field}
