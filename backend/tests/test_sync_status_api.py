"""GET /api/sync/status: state per account from sync_log (uses the real config/rules.yaml:
Mon-Fri 08:00-16:00 Brussels, 60 s in trading hours, 900 s otherwise)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api import sync_status
from app.config_files import ConfigError
from app.db import make_session_factory
from app.models import Account, SyncLog
from app.models.enums import AccountPhase, AccountStatus

# Wed 2026-11-04 10:00 UTC = 11:00 Brussels: trading hours, 60 s interval, stale after 180 s.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


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


@pytest.fixture
def clock(app: FastAPI) -> Iterator[list[datetime]]:
    """Pinned clock; tests may replace clock[0]."""
    now = [NOW]
    app.dependency_overrides[sync_status.utc_now] = lambda: now[0]
    yield now
    app.dependency_overrides.pop(sync_status.utc_now, None)


_login = iter(range(5000, 9000))


def add_account(session: Session, name: str, **kw: Any) -> Account:
    account = Account(
        name=name,
        firm="FundedNext",
        program="Stellar 2-Step",
        phase=AccountPhase.PHASE_1.value,
        login=next(_login),
        server="FundedNext-Server",
        starting_balance=Decimal("100000.00"),
        currency="USD",
        **kw,
    )
    session.add(account)
    session.commit()
    return account


def add_sync(
    session: Session,
    account: Account,
    ago: timedelta,
    ok: bool | None,
    *,
    now: datetime = NOW,
    **kw: Any,
) -> SyncLog:
    started = now - ago
    row = SyncLog(
        account_id=account.id,
        started_at=started,
        finished_at=None if ok is None else started + timedelta(seconds=2),
        ok=ok,
        **kw,
    )
    session.add(row)
    session.commit()
    return row


def status_of(client: TestClient, account: Account) -> dict[str, Any]:
    response = client.get("/api/sync/status")
    assert response.status_code == 200, response.text
    item: dict[str, Any] = next(
        i for i in response.json()["items"] if i["account_id"] == account.id
    )
    return item


@pytest.mark.usefixtures("clock")
def test_never(client: TestClient, session: Session) -> None:
    account = add_account(session, "A", server_offset_hours=2)
    assert status_of(client, account) == {
        "account_id": account.id,
        "account_name": "A",
        "state": "never",
        "last_attempt_utc": None,
        "last_success_utc": None,
        "error_code": None,
        "error_message": None,
        "server_offset_hours": 2,
        "open_positions": 0,
    }


@pytest.mark.usefixtures("clock")
def test_ok_uses_latest_success(client: TestClient, session: Session) -> None:
    account = add_account(session, "A")
    add_sync(session, account, timedelta(minutes=2), True, open_positions=5)
    add_sync(session, account, timedelta(seconds=30), True, open_positions=1)
    item = status_of(client, account)
    assert item["state"] == "ok"
    assert item["last_attempt_utc"] == "2026-11-04T09:59:30Z"
    assert item["last_success_utc"] == "2026-11-04T09:59:32Z"  # finished_at
    assert item["open_positions"] == 1
    assert item["error_code"] is None


@pytest.mark.usefixtures("clock")
def test_error_keeps_last_success(client: TestClient, session: Session) -> None:
    account = add_account(session, "A")
    add_sync(session, account, timedelta(minutes=2), True, open_positions=2)
    add_sync(
        session,
        account,
        timedelta(seconds=40),
        False,
        error_code="login_failed",
        error_message="Invalid account",
    )
    item = status_of(client, account)
    assert item["state"] == "error"
    assert item["error_code"] == "login_failed"
    assert item["error_message"] == "Invalid account"
    assert item["last_attempt_utc"] == "2026-11-04T09:59:20Z"
    assert item["last_success_utc"] == "2026-11-04T09:58:02Z"
    assert item["open_positions"] == 2


@pytest.mark.usefixtures("clock")
def test_running(client: TestClient, session: Session) -> None:
    account = add_account(session, "A")
    add_sync(session, account, timedelta(minutes=1), True, open_positions=3)
    add_sync(session, account, timedelta(seconds=5), None)
    item = status_of(client, account)
    assert item["state"] == "running"
    assert item["last_attempt_utc"] == "2026-11-04T09:59:55Z"
    assert item["open_positions"] == 3  # from the last successful sync


@pytest.mark.usefixtures("clock")
def test_stale_success(client: TestClient, session: Session) -> None:
    account = add_account(session, "A")
    add_sync(session, account, timedelta(minutes=10), True)
    assert status_of(client, account)["state"] == "stale"


@pytest.mark.usefixtures("clock")
def test_stuck_running_is_stale(client: TestClient, session: Session) -> None:
    account = add_account(session, "A")
    add_sync(session, account, timedelta(hours=1), None)
    assert status_of(client, account)["state"] == "stale"


@pytest.mark.usefixtures("clock")
def test_old_error_is_stale_but_keeps_error(client: TestClient, session: Session) -> None:
    account = add_account(session, "A")
    add_sync(session, account, timedelta(hours=1), False, error_code="timeout")
    item = status_of(client, account)
    assert item["state"] == "stale"
    assert item["error_code"] == "timeout"
    assert item["last_success_utc"] is None


def test_idle_hours_use_long_interval(
    client: TestClient, session: Session, clock: list[datetime]
) -> None:
    clock[0] = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)  # Saturday: 900 s, stale after 45 min
    account = add_account(session, "A")
    add_sync(session, account, timedelta(minutes=20), True, now=clock[0])
    assert status_of(client, account)["state"] == "ok"
    other = add_account(session, "B")
    add_sync(session, other, timedelta(minutes=50), True, now=clock[0])
    assert status_of(client, other)["state"] == "stale"


def test_idle_gap_at_session_start_not_stale(
    client: TestClient, session: Session, clock: list[datetime]
) -> None:
    # 08:02 Brussels (trading, 60 s); the last run at 07:50 was scheduled with the 900 s interval.
    clock[0] = datetime(2026, 11, 4, 7, 2, tzinfo=UTC)
    account = add_account(session, "A")
    add_sync(session, account, timedelta(minutes=12), True, now=clock[0])
    assert status_of(client, account)["state"] == "ok"


@pytest.mark.usefixtures("clock")
def test_archived_excluded_and_sorted(client: TestClient, session: Session) -> None:
    add_account(session, "b")
    add_account(session, "A")
    add_account(session, "Gone", status=AccountStatus.ARCHIVED.value)
    names = [i["account_name"] for i in client.get("/api/sync/status").json()["items"]]
    assert names == ["A", "b"]


def test_expected_interval_from_rules() -> None:
    assert sync_status.expected_interval(NOW) == timedelta(seconds=60)
    saturday = datetime(2026, 11, 7, 10, 0, tzinfo=UTC)
    assert sync_status.expected_interval(saturday) == timedelta(seconds=900)


def test_expected_interval_falls_back_when_rules_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> Any:
        raise ConfigError(Path("rules.yaml"), ["bad"])

    monkeypatch.setattr(sync_status, "get_rules", broken)
    assert sync_status.expected_interval(NOW) == timedelta(seconds=900)
