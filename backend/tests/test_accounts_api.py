"""Accounts API (docs/api.md "Accounts"). Runs against the test DB; tables are emptied per test."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import config
from app.db import make_session_factory
from app.models import Account, Trade
from app.models.enums import Direction

LOGIN = 90000001
CLOSE_TIME = datetime(2026, 10, 30, 9, 40, tzinfo=UTC)


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "FN Stellar P1",
        "firm": "FundedNext",
        "program": "Stellar 2-Step",
        "phase": "phase_1",
        "login": LOGIN,
        "server": "FundedNext-Server",
        "terminal_path": "D:\\MT5\\fn-p1\\terminal64.exe",
        "starting_balance": "100000.00",
        "currency": "USD",
        "status": "active",
        "daily_loss_pct": "5.00",
        "max_drawdown_pct": "10.00",
        "profit_target_pct": "8.00",
    }
    return body | overrides


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture(autouse=True)
def fake_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Never read the developer's real .env: point the lookup at an empty temp file."""
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    for login in (LOGIN, LOGIN + 1):
        monkeypatch.delenv(config.mt5_password_key(login), raising=False)
    return env_file


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    db = make_session_factory(db_engine)()
    try:
        yield db
    finally:
        db.close()


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/api/accounts", json=_body(**overrides))
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def _fields(response: Any) -> dict[str, str]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields: dict[str, str] = error["details"]["fields"]
    return fields


def _add_trade(session: Session, account_id: int) -> None:
    session.add(
        Trade(
            account_id=account_id,
            position_id=555,
            symbol="GER40",
            direction=Direction.BUY,
            open_time=CLOSE_TIME,
            close_time=CLOSE_TIME,
            entry_price=Decimal("19500.50"),
            volume=Decimal("1.25"),
        )
    )
    session.commit()


# --- happy paths ---


def test_create_returns_account_with_decimal_strings(client: TestClient) -> None:
    data = _create(client)
    assert data["id"] > 0
    assert data["name"] == "FN Stellar P1"
    assert data["phase"] == "phase_1"
    assert data["status"] == "active"
    assert data["login"] == LOGIN
    assert data["starting_balance"] == "100000.00"
    assert data["daily_loss_pct"] == "5.0000"  # NUMERIC(10,4)
    assert data["reference_balance"] == "100000.00"  # defaults to starting_balance (M5-10)
    assert data["password_env_key"] == f"MT5_PASSWORD_{LOGIN}"
    assert data["password_configured"] is False
    assert data["balance"] is None
    assert data["equity"] is None
    assert data["balance_synced_at"] is None
    assert data["server_offset_hours"] is None
    assert data["created_at"].endswith("Z")
    assert data["updated_at"].endswith("Z")
    assert "password" not in data
    assert "password_ref" not in data


def test_create_minimal_uses_defaults(client: TestClient) -> None:
    body = _body()
    for key in (
        "terminal_path",
        "status",
        "daily_loss_pct",
        "max_drawdown_pct",
        "profit_target_pct",
    ):
        del body[key]
    response = client.post("/api/accounts", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "active"
    assert data["terminal_path"] is None
    assert data["daily_loss_pct"] is None


def test_integer_decimal_input_accepted(client: TestClient) -> None:
    data = _create(client, starting_balance=50000, daily_loss_pct=5)
    assert data["starting_balance"] == "50000.00"
    assert data["daily_loss_pct"] == "5.0000"


def test_get_account(client: TestClient) -> None:
    created = _create(client)
    response = client.get(f"/api/accounts/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_includes_sync_fields_as_utc(client: TestClient, session: Session) -> None:
    created = _create(client)
    account = session.get(Account, created["id"])
    assert account is not None
    account.balance = Decimal("100512.30")
    account.equity = Decimal("100498.10")
    account.balance_synced_at = CLOSE_TIME
    account.server_offset_hours = 2
    session.commit()

    data = client.get(f"/api/accounts/{created['id']}").json()
    assert data["balance"] == "100512.30"
    assert data["equity"] == "100498.10"
    assert data["balance_synced_at"] == "2026-10-30T09:40:00Z"
    assert data["server_offset_hours"] == 2


def test_get_unknown_is_404(client: TestClient) -> None:
    response = client.get("/api/accounts/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_sorted_by_name_and_hides_archived(client: TestClient) -> None:
    _create(client, name="b account", login=LOGIN)
    _create(client, name="A account", login=LOGIN + 1)
    _create(client, name="C archived", login=LOGIN + 2, status="archived")

    names = [a["name"] for a in client.get("/api/accounts").json()["items"]]
    assert names == ["A account", "b account"]

    response = client.get("/api/accounts", params={"include_archived": "true"})
    names = [a["name"] for a in response.json()["items"]]
    assert names == ["A account", "b account", "C archived"]


def test_list_empty(client: TestClient) -> None:
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_patch_partial(client: TestClient) -> None:
    created = _create(client)
    response = client.patch(
        f"/api/accounts/{created['id']}",
        json={"phase": "funded", "daily_loss_pct": "4.5", "terminal_path": None},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["phase"] == "funded"
    assert data["daily_loss_pct"] == "4.5000"
    assert data["terminal_path"] is None
    # untouched fields keep their values
    assert data["name"] == created["name"]
    assert data["max_drawdown_pct"] == created["max_drawdown_pct"]
    assert data["updated_at"] >= created["updated_at"]


def test_patch_empty_body_is_noop(client: TestClient) -> None:
    created = _create(client)
    response = client.patch(f"/api/accounts/{created['id']}", json={})
    assert response.status_code == 200
    assert response.json()["name"] == created["name"]


def test_patch_unknown_is_404(client: TestClient) -> None:
    response = client.patch("/api/accounts/999999", json={"name": "x"})
    assert response.status_code == 404


def test_delete_without_trades_removes(client: TestClient) -> None:
    created = _create(client)
    response = client.delete(f"/api/accounts/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/accounts/{created['id']}").status_code == 404


def test_delete_with_trades_archives(client: TestClient, session: Session) -> None:
    created = _create(client)
    _add_trade(session, created["id"])

    response = client.delete(f"/api/accounts/{created['id']}")
    assert response.status_code == 204

    data = client.get(f"/api/accounts/{created['id']}").json()
    assert data["status"] == "archived"
    assert client.get("/api/accounts").json()["items"] == []


def test_delete_unknown_is_404(client: TestClient) -> None:
    assert client.delete("/api/accounts/999999").status_code == 404


# --- password_configured ---


def test_password_configured_from_environment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create(client)
    monkeypatch.setenv(f"MT5_PASSWORD_{LOGIN}", "not-a-real-secret")
    data = client.get(f"/api/accounts/{created['id']}").json()
    assert data["password_configured"] is True
    assert "not-a-real-secret" not in client.get("/api/accounts").text


def test_password_configured_from_env_file(client: TestClient, fake_env_file: Path) -> None:
    fake_env_file.write_text(f"MT5_PASSWORD_{LOGIN}=not-a-real-secret\n", encoding="utf-8")
    data = _create(client)
    assert data["password_configured"] is True


def test_password_for_other_login_does_not_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"MT5_PASSWORD_{LOGIN + 1}", "not-a-real-secret")
    assert _create(client)["password_configured"] is False


def test_password_key_follows_login_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"MT5_PASSWORD_{LOGIN + 1}", "not-a-real-secret")
    created = _create(client)
    data = client.patch(f"/api/accounts/{created['id']}", json={"login": LOGIN + 1}).json()
    assert data["password_env_key"] == f"MT5_PASSWORD_{LOGIN + 1}"
    assert data["password_configured"] is True


# --- 409 conflicts ---


def test_duplicate_name_is_409(client: TestClient) -> None:
    _create(client)
    response = client.post("/api/accounts", json=_body(login=LOGIN + 1))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["details"] == {"field": "name"}


def test_duplicate_login_server_is_409(client: TestClient) -> None:
    _create(client)
    response = client.post("/api/accounts", json=_body(name="Other"))
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"field": "login"}


def test_same_login_other_server_ok(client: TestClient) -> None:
    _create(client)
    _create(client, name="Other", server="Other-Server")


def test_patch_to_duplicate_name_is_409(client: TestClient) -> None:
    _create(client)
    other = _create(client, name="Other", login=LOGIN + 1)
    response = client.patch(f"/api/accounts/{other['id']}", json={"name": "FN Stellar P1"})
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"field": "name"}
    # the failed update left the account untouched
    assert client.get(f"/api/accounts/{other['id']}").json()["name"] == "Other"


def test_patch_to_duplicate_login_is_409(client: TestClient) -> None:
    _create(client)
    other = _create(client, name="Other", login=LOGIN + 1)
    response = client.patch(f"/api/accounts/{other['id']}", json={"login": LOGIN})
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"field": "login"}


# --- 422 validation ---


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 101),
        ("firm", ""),
        ("phase", "phase_3"),
        ("status", "deleted"),
        ("login", 0),
        ("login", -5),
        ("login", "12345678"),
        ("login", 1.5),
        ("login", 2**63),
        ("currency", "usd"),
        ("currency", "USDT"),
        ("currency", "US"),
        ("starting_balance", "0"),
        ("starting_balance", "-1.00"),
        ("starting_balance", "100.123"),
        ("starting_balance", "abc"),
        ("starting_balance", "NaN"),
        ("starting_balance", "Infinity"),
        ("starting_balance", 100000.5),
        ("starting_balance", True),
        ("starting_balance", None),
        ("reference_balance", "0"),
        ("daily_loss_pct", "-0.01"),
        ("daily_loss_pct", "100.01"),
        ("daily_loss_pct", "1.12345"),
        ("max_drawdown_pct", 10.0),
        ("terminal_path", "D:\\MT5\\fn-p1\\terminal.exe"),
        ("terminal_path", "D:\\MT5\\fn-p1"),
    ],
)
def test_create_validation_errors(client: TestClient, field: str, value: Any) -> None:
    fields = _fields(client.post("/api/accounts", json=_body(**{field: value})))
    assert field in fields


def test_missing_required_fields_listed(client: TestClient) -> None:
    fields = _fields(client.post("/api/accounts", json={}))
    assert set(fields) == {
        "name",
        "firm",
        "program",
        "phase",
        "login",
        "server",
        "starting_balance",
        "currency",
    }


def test_unknown_field_rejected(client: TestClient) -> None:
    body = _body(password="dummy")  # noqa: S106
    fields = _fields(client.post("/api/accounts", json=body))
    assert "password" in fields


@pytest.mark.parametrize(
    "path",
    [
        "C:/MT5/terminal64.exe",
        "D:\\MT5\\FN\\Terminal64.EXE",
        "  D:\\MT5\\terminal64.exe  ",
    ],
)
def test_terminal_path_variants_accepted(client: TestClient, path: str) -> None:
    assert _create(client, terminal_path=path)["terminal_path"] == path.strip()


def test_blank_terminal_path_means_none(client: TestClient) -> None:
    assert _create(client, terminal_path="  ")["terminal_path"] is None


def test_upper_bounds_accepted(client: TestClient) -> None:
    data = _create(client, daily_loss_pct="100", max_drawdown_pct="0", name="x" * 100)
    assert data["daily_loss_pct"] == "100.0000"
    assert data["max_drawdown_pct"] == "0.0000"


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "firm",
        "program",
        "phase",
        "login",
        "server",
        "starting_balance",
        "currency",
        "status",
        "reference_balance",  # the account size cannot be removed (M5-10)
    ],
)
def test_patch_required_field_to_null_rejected(client: TestClient, field: str) -> None:
    created = _create(client)
    fields = _fields(client.patch(f"/api/accounts/{created['id']}", json={field: None}))
    assert field in fields


def test_patch_validation_error(client: TestClient) -> None:
    created = _create(client)
    fields = _fields(
        client.patch(f"/api/accounts/{created['id']}", json={"currency": "eur", "login": 0})
    )
    assert set(fields) == {"currency", "login"}


def test_patch_float_rejected(client: TestClient) -> None:
    created = _create(client)
    fields = _fields(client.patch(f"/api/accounts/{created['id']}", json={"starting_balance": 1.1}))
    assert "starting_balance" in fields


# --- terminal under Program Files (DECISIONS 2026-11-03, MT5_SETUP.md step 1) ---

PROGRAM_FILES_PATHS = [
    "C:\\Program Files\\FundedNext MT5 Terminal\\terminal64.exe",
    "c:/program files (x86)/MT5/terminal64.exe",
    '"C:\\Program Files\\MT5\\terminal64.exe"',
    "C:\\MT5\\..\\Program Files\\x\\terminal64.exe",
    "C:\\PROGRA~1\\MT5\\terminal64.exe",
    "%ProgramFiles%\\MT5\\terminal64.exe",
    "C:\\Program Files\\MT5",  # folder: the Program Files reason wins over the file name
]


def _assert_program_files_error(response: Any) -> None:
    fields = _fields(response)
    assert set(fields) == {"terminal_path"}
    assert "docs/MT5_SETUP.md step 1" in fields["terminal_path"]
    details = response.json()["error"]["details"]
    assert details["field_codes"] == {"terminal_path": "terminal_in_program_files"}


@pytest.fixture
def default_program_files_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", "C:\\Program Files (x86)")


@pytest.mark.usefixtures("default_program_files_env")
@pytest.mark.parametrize("path", PROGRAM_FILES_PATHS)
def test_create_rejects_terminal_in_program_files(client: TestClient, path: str) -> None:
    _assert_program_files_error(client.post("/api/accounts", json=_body(terminal_path=path)))
    assert client.get("/api/accounts").json()["items"] == []


@pytest.mark.usefixtures("default_program_files_env")
@pytest.mark.parametrize("path", PROGRAM_FILES_PATHS)
def test_update_rejects_terminal_in_program_files(client: TestClient, path: str) -> None:
    created = _create(client)
    response = client.patch(f"/api/accounts/{created['id']}", json={"terminal_path": path})
    _assert_program_files_error(response)
    stored = client.get(f"/api/accounts/{created['id']}").json()
    assert stored["terminal_path"] == created["terminal_path"]


@pytest.mark.parametrize(
    "path",
    [
        "C:\\Program Files Backup\\MT5\\terminal64.exe",
        "D:\\Program Files\\MT5\\terminal64.exe",
        "C:\\MT5\\Program Files\\terminal64.exe",
    ],
)
def test_program_files_lookalikes_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramFiles(Arm)", raising=False)
    assert _create(client, terminal_path=path)["terminal_path"] == path


def test_other_validation_errors_have_no_field_codes(client: TestClient) -> None:
    response = client.post("/api/accounts", json=_body(terminal_path="D:\\MT5\\terminal.exe"))
    assert "terminal_path" in _fields(response)
    assert "field_codes" not in response.json()["error"]["details"]
