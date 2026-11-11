"""M5-10 calculator: the risk base is always the account size (docs/api.md "M5-10").

Response: ``balance`` = account size, ``balance_source`` = "account_size", ``balance_synced_at``
null; new info fields ``current_balance`` / ``current_balance_synced_at``. Real GER40 case:
EUR->USD 1.1091, buy 26478.80, SL 26414.20 (6460 ticks, 0.11091 USD per tick per lot), 1 %
of a 10 000 account = 100.00 -> 0.13 lot, although the synced balance is 10 401.70.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Account
from tests.test_calculator_api import (
    BALANCE_AT,
    calculate,
    eurusd_body,
    make_account,
    make_spec,
    ok,
)
from tests.test_calculator_fx_api import (  # noqa: F401  (autouse fixtures)
    _clean,
    _symbols,
    ger30_body,
    make_fx_rate,
    make_ger30,
)

D = Decimal


def sized_account(db: Session, size: str = "10000.00", balance: str = "10401.70") -> Account:
    return make_account(
        db,
        reference_balance=D(size),
        balance=D(balance),
        balance_synced_at=BALANCE_AT,
    )


def test_real_ger40_case_one_percent_of_the_size_gives_013_lot(
    client: TestClient, db_session: Session
) -> None:
    account = sized_account(db_session)
    make_ger30(db_session, account)
    make_fx_rate(db_session, account)
    body = ger30_body(account)
    del body["risk_amount"]
    body["risk_percent"] = "1"

    data = ok(client, body)

    assert D(data["risk_budget"]) == D("100.00")
    assert D(data["volume"]) == D("0.13")
    assert D(data["loss_per_tick"]) == D("0.11091")
    assert D(data["sl_points"]) == D("6460")
    assert D(data["balance"]) == D("10000.00")
    assert data["balance_source"] == "account_size"
    assert data["balance_synced_at"] is None
    assert D(data["current_balance"]) == D("10401.70")
    assert data["current_balance_synced_at"] is not None


@pytest.mark.parametrize("balance", ["10401.70", "9857.58"])
def test_one_percent_is_100_above_and_below_a_10000_size(
    client: TestClient, db_session: Session, balance: str
) -> None:
    account = sized_account(db_session, balance=balance)
    make_spec(db_session, account, "EURUSD")

    data = ok(client, eurusd_body(account, risk_percent="1"))

    assert D(data["risk_budget"]) == D("100")
    assert D(data["volume"]) == D("0.5")
    assert D(data["current_balance"]) == D(balance)


def test_risk_percent_and_actual_risk_percent_are_of_the_size(
    client: TestClient, db_session: Session
) -> None:
    account = sized_account(db_session, size="20000.00", balance="10401.70")
    make_spec(db_session, account, "EURUSD")

    data = ok(client, eurusd_body(account, risk_amount="100"))

    assert D(data["actual_risk_percent"]) == D("0.5")  # 100 / 20000, not / 10401.70


def test_the_response_has_no_reference_or_synced_source(
    client: TestClient, db_session: Session
) -> None:
    account = sized_account(db_session)
    make_spec(db_session, account, "EURUSD")

    response = calculate(client, eurusd_body(account))

    assert response.status_code == 200
    assert response.json()["balance_source"] not in {"reference", "synced"}


def test_a_non_finite_synced_balance_is_shown_as_no_current_balance(
    client: TestClient, db_session: Session
) -> None:
    account = sized_account(db_session, balance="NaN")
    make_spec(db_session, account, "EURUSD")

    data = ok(client, eurusd_body(account, risk_percent="1"))

    assert D(data["risk_budget"]) == D("100")  # the size still sizes the trade
    assert data["current_balance"] is None
