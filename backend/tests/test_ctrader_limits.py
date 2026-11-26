"""cTrader phase c6: Home limits and daily/weekly stops count a cTrader account like MT5.

Mirrors tests/test_home_api.py::test_limits_of_one_account for both platforms: the figures
come from the trades and the account size only, with no platform branch.
"""

# ruff: noqa: F811 - the imported Home fixtures are used as parameters
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Account
from tests.ctrader_fakes import make_ctrader_account
from tests.test_dashboard_api import closed, open_position
from tests.test_home_api import (  # noqa: F401 - fixtures of the Home tests
    MON,
    NOV_3,
    OCT_20,
    TODAY,
    _clean,
    clock,
    data_dir,
    home,
    session,
)
from tests.test_trades_api import add_account

D = Decimal
FIRM = {"firm": "FundedNext", "program": "Stellar 2-Step", "reference_balance": D("10000.00")}


def make(session: Session, platform: str, name: str = "Alpha") -> Account:
    if platform == "ctrader":
        return make_ctrader_account(session, name=name, **FIRM)
    return add_account(session, name, 1, reference_balance=FIRM["reference_balance"])


@pytest.fixture(params=["mt5", "ctrader"])
def platform(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_limits_of_one_account_are_the_same_on_both_platforms(
    client: TestClient, session: Session, platform: str
) -> None:
    alpha = make(session, platform)
    closed(session, alpha, TODAY, "250.00")
    closed(session, alpha, TODAY + timedelta(hours=1), "-40.00", excluded_from_stats=True,
           excluded_reason="test trade", excluded_at=TODAY)  # fmt: skip
    closed(session, alpha, MON, "100.00")
    closed(session, alpha, NOV_3, "-300.00")
    closed(session, alpha, OCT_20, "999.00")  # last month: never counted
    open_position(session, alpha)

    limits = home(client, account_id=alpha.id)["limits"]

    assert limits == {
        "account_id": alpha.id,
        "account_name": "Alpha",
        "currency": "USD",
        "day": {"pct": "2.1000", "loss_pct": "-3.0000", "profit_pct": "5.0000"},
        "week": {"pct": "3.1000", "loss_pct": "-6.0000", "profit_pct": "10.0000"},
        "month": {"pct": "0.1000", "loss_pct": "-10.0000", "profit_pct": "10.0000"},
        "trades_week": 4,
        "max_trades_week": 10,
        "to_daily_stop_pct": "5.1000",
        "floating_pnl": None,
        "floating_included": False,
        "balance": None,
        "equity": None,
        "balance_fresh": False,
        "firm_day": None,
    }


def test_daily_stop_state_is_reached_by_a_ctrader_account_like_by_mt5(
    client: TestClient, session: Session, platform: str
) -> None:
    alpha = make(session, platform)
    closed(session, alpha, TODAY, "-350.00")  # -3.5 % of 10000, the daily stop is -3 %

    limits: dict[str, Any] = home(client, account_id=alpha.id)["limits"]

    assert limits["day"]["pct"] == "-3.5000"
    assert limits["to_daily_stop_pct"] == "-0.5000"  # past the stop: the «СТОП» state


def test_all_accounts_pick_the_closest_to_the_stop_across_platforms(
    client: TestClient, session: Session
) -> None:
    mt5 = add_account(session, "Mt5 account", 1, reference_balance=FIRM["reference_balance"])
    ct = make_ctrader_account(session, name="cTrader account", **FIRM)
    closed(session, mt5, TODAY, "210.00")  # +2.1 % -> 5.1 to the stop
    closed(session, ct, TODAY, "-250.00")  # -2.5 % -> 0.5 to the stop

    limits = home(client)["limits"]

    assert (limits["account_id"], limits["to_daily_stop_pct"]) == (ct.id, "0.5000")
