"""cTrader money values: exact Decimal scaling, never a float."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.money import equity_from, parse_int, scale_money, to_stored


@pytest.mark.parametrize(
    ("raw", "digits", "expected"),
    [
        (100050, 2, "1000.50"),
        (-1234, 2, "-12.34"),
        (0, 2, "0.00"),
        (5, 0, "5"),
        (123456789, 8, "1.23456789"),
        # int64 max at 8 digits: a float would lose the last digits.
        (9223372036854775807, 8, "92233720368.54775807"),
    ],
)
def test_scale_money_is_exact(raw: int, digits: int, expected: str) -> None:
    result = scale_money(raw, digits)
    assert isinstance(result, Decimal)
    assert str(result) == expected


@pytest.mark.parametrize("digits", [-1, 19])
def test_scale_money_rejects_absurd_digits(digits: int) -> None:
    with pytest.raises(CtraderError) as caught:
        scale_money(1, digits)
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


@pytest.mark.parametrize("value", [1.5, True, None, "abc", "1.5", ""])
def test_parse_int_refuses_non_integers(value: object) -> None:
    with pytest.raises(CtraderError) as caught:
        parse_int(value, "balance")
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE


@pytest.mark.parametrize(
    ("value", "expected"), [(12, 12), ("-12", -12), ("9007199254740993", 9007199254740993)]
)
def test_parse_int_accepts_int_and_digit_string(value: object, expected: int) -> None:
    assert parse_int(value, "balance") == expected


def test_equity_is_balance_plus_net_pnl() -> None:
    assert equity_from(Decimal("1000.50"), [Decimal("12.34"), Decimal("-2.34")]) == Decimal(
        "1010.50"
    )


def test_equity_without_positions_is_the_balance() -> None:
    assert equity_from(Decimal("1000.50"), []) == Decimal("1000.50")


def test_equity_keeps_precision_beyond_the_default_context() -> None:
    big = Decimal("92233720368.54775807")
    tiny = Decimal("0.00000000000000001")
    assert equity_from(big, [tiny]) == Decimal("92233720368.54775807000000001")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1000.505", "1000.51"), ("-1000.505", "-1000.51"), ("1000.5", "1000.50")],
)
def test_to_stored_rounds_half_up_to_cents(value: str, expected: str) -> None:
    assert str(to_stored(Decimal(value))) == expected


def test_to_stored_refuses_a_value_the_column_cannot_hold() -> None:
    with pytest.raises(CtraderError) as caught:
        to_stored(Decimal("10000000000000000"))
    assert caught.value.code is CtraderErrorCode.BAD_RESPONSE
