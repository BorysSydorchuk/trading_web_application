"""The shared period percent base (PM 2026-11-20; app.domain.period_base)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.period_base import period_base

D = Decimal
SIZES = {1: D("10000"), 2: D("10000"), 3: D("10000")}


def test_one_account_is_its_size_whatever_it_traded() -> None:
    assert period_base(SIZES, [], account_id=2) == D("10000")
    assert period_base(SIZES, [1, 3], account_id=2) == D("10000")


def test_all_accounts_sum_the_accounts_that_traded() -> None:
    # November: strategy trades on 1 and 2, only an excluded trade on 3 -> all three
    assert period_base(SIZES, [1, 2, 3]) == D("30000")
    assert period_base(SIZES, {1, 2}) == D("20000")
    assert period_base(SIZES, [1, 1, 1]) == D("10000")


def test_no_traded_account_is_none_unless_the_fallback_is_asked() -> None:
    assert period_base(SIZES, []) is None
    assert period_base(SIZES, [], fallback_to_all=True) == D("30000")
    assert period_base(SIZES, [2], fallback_to_all=True) == D("10000")
    assert period_base({}, [], fallback_to_all=True) is None


@pytest.mark.parametrize("bad", [D("0"), D("-1"), D("NaN"), D("Infinity")])
def test_an_unusable_size_gives_no_base(bad: Decimal) -> None:
    sizes = SIZES | {2: bad}
    assert period_base(sizes, [1, 2]) is None
    assert period_base(sizes, [], account_id=2) is None
    assert period_base(sizes, [], fallback_to_all=True) is None
    assert period_base(sizes, [1, 3]) == D("20000")  # the bad account did not trade


def test_a_traded_account_without_a_known_size_gives_no_base() -> None:
    assert period_base(SIZES, [1, 9]) is None
    assert period_base(SIZES, [], account_id=9) is None


def test_input_is_not_mutated() -> None:
    sizes = dict(SIZES)
    traded = [3, 1]
    period_base(sizes, traded)
    assert (sizes, traded) == (SIZES, [3, 1])
