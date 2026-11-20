"""Accounts API: ``starting_balance_suggestion`` from DATA_DIR/starting_balance_suggestions.json
(docs/api.md "Starting balance suggestion (2026-11-20)"); confirmed with PATCH starting_balance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.services import starting_balance_suggestion as sbs
from tests.test_accounts_api import (  # noqa: F401 (fixtures)
    _clean,
    _create,
    _fields,
    fake_env_file,
)

SUGGESTED = {"amount": "10000.00", "time": "2026-11-10T12:53:00Z", "ticket": 194830322}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, app: FastAPI, settings: Settings) -> Path:
    custom = settings.model_copy(update={"data_dir": tmp_path.resolve()})
    app.dependency_overrides[get_settings] = lambda: custom
    sbs._warned.clear()
    return tmp_path.resolve()


def write_file(data_dir: Path, values: Any) -> None:
    text = values if isinstance(values, str) else json.dumps(values)
    (data_dir / sbs.SUGGESTIONS_FILE).write_text(text, encoding="utf-8")


def _get(client: TestClient, account_id: int) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account_id}")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def test_suggestion_shown_when_it_differs(client: TestClient, data_dir: Path) -> None:
    account = _create(client, starting_balance="9986.05")
    write_file(data_dir, {str(account["id"]): SUGGESTED})

    expected = {"amount": "10000.00", "time": "2026-11-10T12:53:00Z"}
    assert _get(client, account["id"])["starting_balance_suggestion"] == expected
    items = client.get("/api/accounts").json()["items"]
    assert items[0]["starting_balance_suggestion"] == expected


def test_confirming_with_patch_removes_the_suggestion(client: TestClient, data_dir: Path) -> None:
    account = _create(client, starting_balance="9986.05", reference_balance="10000.00")
    write_file(data_dir, {str(account["id"]): SUGGESTED})

    response = client.patch(f"/api/accounts/{account['id']}", json={"starting_balance": "10000.00"})

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["starting_balance"] == "10000.00"
    assert data["reference_balance"] == "10000.00"
    assert data["starting_balance_suggestion"] is None
    assert _get(client, account["id"])["starting_balance_suggestion"] is None


@pytest.mark.parametrize(
    "content",
    [
        None,  # no file yet
        "{broken",
        {"1": {"amount": None, "checked_at": "2026-11-20T09:00:00Z"}},  # no deposit found
        {"2": SUGGESTED},  # another account
        {"1": {"amount": "100000", "time": "2026-11-10T12:53:00Z"}},  # equal
    ],
)
def test_no_suggestion(client: TestClient, data_dir: Path, content: Any) -> None:
    account = _create(client)  # id 1, starting_balance 100000.00
    if content is not None:
        write_file(data_dir, content)

    assert _get(client, account["id"])["starting_balance_suggestion"] is None
    assert client.get("/api/accounts").status_code == 200


@pytest.mark.parametrize("value", ["0", "-5.00", "10000.001"])
def test_patch_starting_balance_validation(client: TestClient, value: str) -> None:
    account = _create(client)

    response = client.patch(f"/api/accounts/{account['id']}", json={"starting_balance": value})

    assert "starting_balance" in _fields(response)
