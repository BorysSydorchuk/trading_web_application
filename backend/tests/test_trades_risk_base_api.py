"""M5-10: PATCH /api/trades/{id} (user initial SL) divides risk % by the account size."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db import make_session_factory
from tests.test_trades_api import add_account, add_exit, add_trade


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    db = make_session_factory(db_engine)()
    try:
        yield db
    finally:
        db.close()


def test_patch_initial_sl_uses_the_account_size_not_balance_at_open(
    client: TestClient, session: Session
) -> None:
    # balance_at_open 100000.00 (add_trade default) but the account size is 50000.00:
    # realised risk 250.00 -> 0.5000 % of 50000 (0.2500 % of the balance).
    account = add_account(session, "Sized", 11, reference_balance=Decimal("50000.00"))
    trade = add_trade(session, account, status="needs_sl")
    add_exit(session, trade, 8001)

    response = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "2645.00"})

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["risk_amount"] == "250.00"
    assert data["risk_pct"] == "0.5000"
    assert data["balance_at_open"] == "100000.00"
