"""M5-10 accounts API: ``reference_balance`` is the account size (UI label "Розмір рахунку").

POST defaults it to starting_balance; PATCH may change it (null -> 422) and then recomputes
that account's trades risk_pct / pnl_pct and auto rule violations in the same request.
Contract: docs/api.md "M5-10 Risk base = account size".
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config_files.loader import ConfigError
from app.db import make_session_factory
from app.models import RuleViolation, Trade
from app.services import risk_base
from tests.test_accounts_api import _create, _fields

D = Decimal
MON = datetime(2026, 11, 2, 7, 5, tzinfo=UTC)  # Mon 08:05 Brussels (london)
STALE = D("9.9999")


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


# --- create / patch validation -------------------------------------------------------------------


def test_create_without_a_size_uses_the_starting_balance(client: TestClient) -> None:
    data = _create(client, starting_balance="25000.00")

    assert data["reference_balance"] == "25000.00"


def test_create_with_a_size_keeps_it(client: TestClient) -> None:
    data = _create(client, starting_balance="100000.00", reference_balance="10000.00")

    assert data["reference_balance"] == "10000.00"
    assert data["starting_balance"] == "100000.00"


def test_create_with_a_null_size_also_uses_the_starting_balance(client: TestClient) -> None:
    data = _create(client, starting_balance="25000.00", reference_balance=None)

    assert data["reference_balance"] == "25000.00"


def test_patch_null_size_is_a_validation_error_and_changes_nothing(client: TestClient) -> None:
    created = _create(client, reference_balance="10000.00")

    response = client.patch(f"/api/accounts/{created['id']}", json={"reference_balance": None})

    assert "reference_balance" in _fields(response)
    assert client.get(f"/api/accounts/{created['id']}").json()["reference_balance"] == "10000.00"


@pytest.mark.parametrize("bad", ["0", "-1.00", "NaN", 1.5])
def test_patch_rejects_a_non_positive_or_float_size(client: TestClient, bad: Any) -> None:
    created = _create(client)

    response = client.patch(f"/api/accounts/{created['id']}", json={"reference_balance": bad})

    assert "reference_balance" in _fields(response)


def test_patch_changes_the_size(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/accounts/{created['id']}", json={"reference_balance": "10000.00"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["reference_balance"] == "10000.00"


# --- recompute on PATCH --------------------------------------------------------------------------


def _seed_account(client: TestClient, name: str, login: int, size: str) -> int:
    created = _create(
        client, name=name, login=login, starting_balance="100000.00", reference_balance=size
    )
    return int(created["id"])


def _seed_trades(session: Session, account_id: int, base_position: int) -> tuple[int, int]:
    """Mon: closed -300.00 (risk 100.00), then an open entry (risk 100.00). Percents are stale."""
    common: dict[str, Any] = {
        "account_id": account_id,
        "symbol": "XAUUSD",
        "broker_symbol": "XAUUSD",
        "direction": "buy",
        "entry_price": D("2650"),
        "volume": D("1"),
        "balance_at_open": D("10401.70"),
        "session": "london",
        "risk_amount": D("100.00"),
        "risk_pct": STALE,
    }
    closed = Trade(
        **common,
        position_id=base_position,
        open_time=MON,
        close_time=MON + timedelta(minutes=20),
        net_pnl=D("-300.00"),
        pnl_pct=STALE,
        status="needs_description",
    )
    entry = Trade(
        **common,
        position_id=base_position + 1,
        open_time=MON + timedelta(hours=2),
        status="open",
    )
    session.add_all([closed, entry])
    session.commit()
    return closed.id, entry.id


def _row(session: Session, trade_id: int) -> Trade:
    session.expire_all()
    return session.get_one(Trade, trade_id)


def _violation_keys(session: Session, trade_id: int) -> set[str]:
    session.expire_all()
    rows = session.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade_id))
    return {r.rule_key for r in rows}


def test_patching_the_size_recomputes_percents_of_that_account(
    client: TestClient, session: Session
) -> None:
    account = _seed_account(client, "A", 90000011, "100000.00")
    closed, entry = _seed_trades(session, account, 1)

    response = client.patch(f"/api/accounts/{account}", json={"reference_balance": "10000.00"})

    assert response.status_code == 200, response.text
    assert _row(session, closed).risk_pct == D("1.0000")
    assert _row(session, closed).pnl_pct == D("-3.0000")
    assert _row(session, entry).risk_pct == D("1.0000")
    assert _row(session, entry).pnl_pct is None  # open trade


def test_shrinking_the_size_flags_the_daily_stop_in_the_same_request(
    client: TestClient, session: Session
) -> None:
    account = _seed_account(client, "A", 90000011, "100000.00")
    _closed, entry = _seed_trades(session, account, 1)

    client.patch(f"/api/accounts/{account}", json={"reference_balance": "10000.00"})

    assert "daily_stop_loss_pct" in _violation_keys(session, entry)  # -300 = -3.00 % of 10000


def test_growing_the_size_unflags_the_daily_stop(client: TestClient, session: Session) -> None:
    account = _seed_account(client, "A", 90000011, "10000.00")
    _closed, entry = _seed_trades(session, account, 1)

    client.patch(f"/api/accounts/{account}", json={"reference_balance": "10000.01"})
    assert "daily_stop_loss_pct" not in _violation_keys(session, entry)  # -2.99997 %

    client.patch(f"/api/accounts/{account}", json={"reference_balance": "10000.00"})
    assert "daily_stop_loss_pct" in _violation_keys(session, entry)

    client.patch(f"/api/accounts/{account}", json={"reference_balance": "100000.00"})
    assert "daily_stop_loss_pct" not in _violation_keys(session, entry)
    assert _row(session, entry).risk_pct == D("0.1000")


def test_max_risk_pct_follows_the_size(client: TestClient, session: Session) -> None:
    account = _seed_account(client, "A", 90000011, "100000.00")
    closed, _entry = _seed_trades(session, account, 1)  # risk 100.00

    client.patch(f"/api/accounts/{account}", json={"reference_balance": "5000.00"})  # 2 %

    assert _row(session, closed).risk_pct == D("2.0000")
    assert "max_risk_pct" in _violation_keys(session, closed)


def test_other_accounts_are_untouched(client: TestClient, session: Session) -> None:
    changed = _seed_account(client, "A", 90000011, "100000.00")
    other = _seed_account(client, "B", 90000012, "100000.00")
    _seed_trades(session, changed, 1)
    other_closed, other_entry = _seed_trades(session, other, 100)

    client.patch(f"/api/accounts/{changed}", json={"reference_balance": "10000.00"})

    assert _row(session, other_closed).risk_pct == STALE
    assert _row(session, other_closed).pnl_pct == STALE
    assert _violation_keys(session, other_entry) == set()


def test_a_rejected_size_does_not_recompute(client: TestClient, session: Session) -> None:
    account = _seed_account(client, "A", 90000011, "100000.00")
    closed, _entry = _seed_trades(session, account, 1)

    response = client.patch(f"/api/accounts/{account}", json={"reference_balance": None})

    assert response.status_code == 422
    assert _row(session, closed).risk_pct == STALE


def test_patch_with_the_same_size_does_not_recompute(client: TestClient, session: Session) -> None:
    account = _seed_account(client, "A", 90000011, "10000.00")
    closed, entry = _seed_trades(session, account, 1)

    response = client.patch(f"/api/accounts/{account}", json={"reference_balance": "10000"})

    assert response.status_code == 200, response.text
    assert response.json()["reference_balance"] == "10000.00"
    assert _row(session, closed).risk_pct == STALE  # 10000 == 10000.00: no recompute
    assert _row(session, closed).pnl_pct == STALE
    assert _violation_keys(session, entry) == set()


def test_broken_rules_yaml_is_config_error_and_changes_nothing(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _seed_account(client, "A", 90000011, "100000.00")
    closed, entry = _seed_trades(session, account, 1)

    def broken() -> Any:
        raise ConfigError(Path("rules.yaml"), ["daily_stop_loss_pct: not a number"])

    monkeypatch.setattr(risk_base, "get_rules", broken)

    response = client.patch(f"/api/accounts/{account}", json={"reference_balance": "10000.00"})

    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "config_error"
    assert client.get(f"/api/accounts/{account}").json()["reference_balance"] == "100000.00"
    assert _row(session, closed).risk_pct == STALE
    assert _row(session, closed).pnl_pct == STALE
    assert _violation_keys(session, entry) == set()


def test_a_size_whose_percents_overflow_is_a_validation_error_and_changes_nothing(
    client: TestClient, session: Session
) -> None:
    # -300.00 / 0.01 x 100 = -3 000 000 % does not fit NUMERIC(10,4).
    account = _seed_account(client, "A", 90000011, "100000.00")
    closed, _entry = _seed_trades(session, account, 1)

    response = client.patch(f"/api/accounts/{account}", json={"reference_balance": "0.01"})

    assert "reference_balance" in _fields(response)
    assert client.get(f"/api/accounts/{account}").json()["reference_balance"] == "100000.00"
    assert _row(session, closed).risk_pct == STALE
