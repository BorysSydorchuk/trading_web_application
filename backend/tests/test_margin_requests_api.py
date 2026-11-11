"""Margin requests API (docs/api.md M5-04d exact shapes). Runs against the test DB.

POST /api/calculator/margin-requests takes the calculate body, re-runs the same sizing and
queues a request for the worker (202). It never touches MT5. GET returns one request.
All specs here are SYNTHETIC (EURUSD-like and GER40-like), never broker evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.models import Account
from app.models.account import SymbolSpec
from app.models.calculator import CalculatorMarginRequest
from app.services.margin_requests import STALE_PROCESSING_S
from tests.test_calculator_api import (
    calculate,
    error_of,
    eurusd_body,
    ger40_body,
    make_account,
    make_ger40,
    make_spec,
    parse_utc,
    request_count,
)

D = Decimal
URL = "/api/calculator/margin-requests"
ITEM_KEYS = {
    "id",
    "account_id",
    "symbol",
    "direction",
    "volume",
    "entry",
    "status",
    "source",
    "amount",
    "currency",
    "created_at",
    "started_at",
    "finished_at",
    "expires_at",
    "error_code",
}
REQUEST_TTL = timedelta(seconds=60)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def account(db_session: Session) -> Account:
    return make_account(db_session)


@pytest.fixture
def eurusd(db_session: Session, account: Account) -> SymbolSpec:
    return make_spec(db_session, account, "EURUSD")


def post(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post(URL, json=body)


def accepted(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = post(client, body)
    assert response.status_code == 202, response.text
    item: dict[str, Any] = response.json()
    return item


def get_item(client: TestClient, request_id: int) -> dict[str, Any]:
    response = client.get(f"{URL}/{request_id}")
    assert response.status_code == 200, response.text
    item: dict[str, Any] = response.json()
    return item


def set_state(db_engine: Engine, request_id: int, sql_set: str) -> None:
    """Move a row to another state with DB times (CHECK result_matches_status holds)."""
    with db_engine.begin() as conn:
        conn.execute(
            text(f"UPDATE calculator_margin_requests SET {sql_set} WHERE id = :id"),  # noqa: S608
            {"id": request_id},
        )


PROCESSING = "status = 'processing', started_at = created_at + interval '1 second'"
DONE = (
    "status = 'done', started_at = created_at + interval '1 second', "
    "finished_at = created_at + interval '2 seconds', margin = 550.25"
)
FAILED = (
    "status = 'failed', started_at = created_at + interval '1 second', "
    "finished_at = created_at + interval '2 seconds', error_code = 'timeout'"
)
EXPIRED = (
    "status = 'expired', finished_at = created_at + interval '61 seconds', "
    "error_code = 'request_expired'"
)
INTERRUPTED = (
    "status = 'failed', started_at = created_at + interval '1 second', "
    "finished_at = created_at + interval '3 seconds', error_code = 'interrupted'"
)
STATES = {"processing": PROCESSING, "done": DONE, "failed": FAILED, "expired": EXPIRED}


# --- POST: success ---


@pytest.mark.usefixtures("eurusd")
def test_post_returns_202_pending_item_with_exact_keys(
    client: TestClient, db_session: Session, account: Account
) -> None:
    item = accepted(client, eurusd_body(account))

    assert set(item) == ITEM_KEYS
    assert isinstance(item["id"], int)
    assert item["account_id"] == account.id
    assert (item["symbol"], item["direction"]) == ("EURUSD", "buy")
    assert D(item["volume"]) == D("0.50")  # 1% of 10000 / 200 per lot
    assert D(item["entry"]) == D("1.10000")
    assert item["status"] == "pending"
    assert item["currency"] == "USD"
    for key in ("source", "amount", "started_at", "finished_at", "error_code"):
        assert item[key] is None, key
    assert parse_utc(item["expires_at"]) - parse_utc(item["created_at"]) == REQUEST_TTL
    assert request_count(db_session) == 1


@pytest.mark.usefixtures("eurusd")
def test_post_stores_the_row_with_db_times(
    client: TestClient, db_session: Session, db_engine: Engine, account: Account
) -> None:
    with db_engine.connect() as conn:
        before = conn.scalar(text("SELECT now()"))
    item = accepted(client, eurusd_body(account))
    with db_engine.connect() as conn:
        after = conn.scalar(text("SELECT now()"))

    row = db_session.get(CalculatorMarginRequest, item["id"])
    assert row is not None
    assert (row.account_id, row.symbol, row.direction) == (account.id, "EURUSD", "buy")
    assert (row.volume, row.entry, row.currency, row.status) == (
        D("0.50"),
        D("1.10000"),
        "USD",
        "pending",
    )
    assert row.started_at is None
    assert row.finished_at is None
    assert row.margin is None
    assert row.error_code is None
    assert before <= row.created_at <= after
    assert row.expires_at == row.created_at + REQUEST_TTL
    assert parse_utc(item["created_at"]) == row.created_at


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"risk_percent": "0.37"},
        {"risk_amount": "123.45"},
        {"sl_price": None, "sl_points": 150, "direction": "sell", "entry": "1.20000"},
    ],
)
def test_volume_is_recomputed_server_side_like_calculate(
    client: TestClient, account: Account, changes: dict[str, Any]
) -> None:
    body = eurusd_body(account, **changes)
    body = {key: value for key, value in body.items() if value is not None}
    calculated = calculate(client, body)
    assert calculated.status_code == 200, calculated.text

    item = accepted(client, body)

    expected = calculated.json()
    assert D(item["volume"]) == D(expected["volume"])
    assert D(item["entry"]) == D(expected["entry"])
    assert item["direction"] == expected["direction"]
    assert item["currency"] == expected["currency"]


def test_currency_is_the_account_currency(client: TestClient, db_session: Session) -> None:
    eur = make_account(db_session, currency="EUR")
    # EUR profit on the EUR account: same currency, no FX rate needed (M5-09).
    make_ger40(db_session, eur, currency_profit="EUR", currency_margin="EUR")

    item = accepted(client, ger40_body(eur))

    assert item["currency"] == "EUR"
    assert item["symbol"] == "GER40.cash"


# --- POST: calculate errors pass through unchanged, no row ---


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    "changes",
    [
        {"entry": 1.1},  # JSON float: 422 validation_error
        {"bogus": 1},  # unknown key: 422 validation_error
        {"risk_percent": "1", "risk_amount": "100"},  # both risk fields: 422
        {"symbol": "EURUSD.raw"},  # unknown symbol: 404 not_found details.symbol
        {"symbol": "EUR"},  # never prefix-matched
        {"account_id": 999999},  # unknown account: 404 not_found details.account_id
        {"sl_price": "1.10200"},  # SL on the profit side: 422 invalid_stop
        {"sl_price": "1.098005"},  # off the tick grid: 422 off_tick_grid
        {"risk_amount": "0.01"},  # below the minimum volume: 422 below_min_volume
    ],
)
def test_calculate_errors_pass_through_unchanged_and_create_no_row(
    client: TestClient, db_session: Session, account: Account, changes: dict[str, Any]
) -> None:
    body = eurusd_body(account, **changes)
    expected = calculate(client, body)
    assert expected.status_code in (404, 409, 422), expected.text

    response = post(client, body)

    assert response.status_code == expected.status_code
    assert response.json() == expected.json()
    assert request_count(db_session) == 0


def test_balance_and_specs_errors_pass_through(client: TestClient, db_session: Session) -> None:
    no_balance = make_account(db_session, reference_balance=D("0"))  # unusable size (M5-10)
    make_spec(db_session, no_balance, "EURUSD")
    incomplete = make_account(db_session)
    make_spec(db_session, incomplete, "EURUSD", point=None)

    for body, status, code in (
        (eurusd_body(no_balance), 409, "balance_unavailable"),
        (eurusd_body(incomplete), 409, "specs_incomplete"),
    ):
        expected = calculate(client, body)
        response = post(client, body)
        error_of(response, status, code)
        assert response.json() == expected.json()
    assert request_count(db_session) == 0


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(("changes", "field"), [({"entry": 1.1}, "entry"), ({"x": 1}, "x")])
def test_body_is_strict_like_calculate(
    client: TestClient, account: Account, changes: dict[str, Any], field: str
) -> None:
    error = error_of(post(client, eurusd_body(account, **changes)), 422, "validation_error")

    assert field in error["details"]["fields"]


# --- POST: de-duplication ---


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize("state", ["pending", "processing"])
def test_identical_open_request_is_returned_instead_of_a_new_row(
    client: TestClient, db_session: Session, db_engine: Engine, account: Account, state: str
) -> None:
    first = accepted(client, eurusd_body(account))
    if state == "processing":
        set_state(db_engine, first["id"], PROCESSING)

    again = post(client, eurusd_body(account))

    assert again.status_code == 202
    assert again.json() == get_item(client, first["id"])
    assert again.json()["status"] == state
    assert request_count(db_session) == 1


@pytest.mark.usefixtures("eurusd")
def test_dedup_key_is_volume_not_risk_input(
    client: TestClient, db_session: Session, account: Account
) -> None:
    by_percent = accepted(client, eurusd_body(account, risk_percent="1"))
    by_amount = accepted(client, eurusd_body(account, risk_amount="100"))  # same 0.50 lot

    assert by_amount["id"] == by_percent["id"]
    assert request_count(db_session) == 1


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize("state", ["done", "failed", "expired"])
def test_finished_request_is_not_reused(
    client: TestClient, db_session: Session, db_engine: Engine, account: Account, state: str
) -> None:
    first = accepted(client, eurusd_body(account))
    set_state(db_engine, first["id"], STATES[state])

    second = accepted(client, eurusd_body(account))

    assert second["id"] != first["id"]
    assert second["status"] == "pending"
    assert request_count(db_session) == 2


@pytest.mark.usefixtures("eurusd")
def test_pending_request_past_its_expiry_is_not_reused(
    client: TestClient, db_session: Session, db_engine: Engine, account: Account
) -> None:
    """The worker has not expired it yet, but it can never be started any more."""
    first = accepted(client, eurusd_body(account))
    set_state(
        db_engine,
        first["id"],
        "created_at = now() - interval '2 minutes', expires_at = now() - interval '1 minute'",
    )

    second = accepted(client, eurusd_body(account))

    assert second["id"] != first["id"]
    assert request_count(db_session) == 2


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "sell", "sl_price": "1.10200"},
        {"entry": "1.10010", "sl_price": "1.09810"},  # same volume, other entry
        {"risk_percent": "2"},  # other volume
    ],
)
def test_different_key_creates_a_new_row(
    client: TestClient, db_session: Session, account: Account, changes: dict[str, Any]
) -> None:
    first = accepted(client, eurusd_body(account))

    second = accepted(client, eurusd_body(account, **changes))

    assert second["id"] != first["id"]
    assert request_count(db_session) == 2


def test_other_account_or_symbol_creates_a_new_row(
    client: TestClient, db_session: Session, account: Account
) -> None:
    other = make_account(db_session)
    make_spec(db_session, account, "EURUSD")
    make_spec(db_session, account, "EURUSD.x")
    make_spec(db_session, other, "EURUSD")

    ids = {
        accepted(client, eurusd_body(account))["id"],
        accepted(client, eurusd_body(account, symbol="EURUSD.x"))["id"],
        accepted(client, eurusd_body(other))["id"],
    }

    assert len(ids) == 3
    assert request_count(db_session) == 3


def processing_since(seconds_ago: int) -> str:
    """SET clause: processing, started ``seconds_ago`` s ago (DB clock), created 1 s before."""
    return (
        f"status = 'processing', started_at = now() - interval '{seconds_ago} seconds', "
        f"created_at = now() - interval '{seconds_ago + 1} seconds', "
        f"expires_at = now() - interval '{seconds_ago - 59} seconds'"
    )


@pytest.mark.usefixtures("eurusd")
def test_stale_processing_request_is_not_reused(
    client: TestClient, db_session: Session, db_engine: Engine, account: Account
) -> None:
    """A row stuck in processing (lost result, dead worker) must not block new lookups."""
    first = accepted(client, eurusd_body(account))
    set_state(db_engine, first["id"], processing_since(STALE_PROCESSING_S + 5))

    second = accepted(client, eurusd_body(account))

    assert second["id"] != first["id"]
    assert second["status"] == "pending"
    assert request_count(db_session) == 2


@pytest.mark.usefixtures("eurusd")
def test_recent_processing_request_is_still_reused(
    client: TestClient, db_session: Session, db_engine: Engine, account: Account
) -> None:
    first = accepted(client, eurusd_body(account))
    set_state(db_engine, first["id"], processing_since(STALE_PROCESSING_S - 30))

    assert accepted(client, eurusd_body(account))["id"] == first["id"]
    assert request_count(db_session) == 1


# --- POST: values the request table cannot store exactly (NUMERIC(20, 8)) ---


def test_entry_beyond_twelve_integer_digits_is_422_and_creates_no_row(
    client: TestClient, db_session: Session, account: Account
) -> None:
    """Calculate accepts it (nothing is stored); the request row could not hold it."""
    make_ger40(db_session, account)
    body = ger40_body(account, entry="1000000000000", sl_price="999999999970")
    assert calculate(client, body).status_code == 200

    error = error_of(post(client, body), 422, "validation_error")

    assert set(error["details"]["fields"]) == {"entry"}
    assert request_count(db_session) == 0


# --- GET ---


@pytest.mark.usefixtures("eurusd")
def test_get_pending_equals_the_post_item(client: TestClient, account: Account) -> None:
    item = accepted(client, eurusd_body(account))

    assert get_item(client, item["id"]) == item


@pytest.mark.usefixtures("eurusd")
def test_get_processing_has_started_at_only(
    client: TestClient, db_engine: Engine, account: Account
) -> None:
    item = accepted(client, eurusd_body(account))
    set_state(db_engine, item["id"], PROCESSING)

    got = get_item(client, item["id"])

    assert set(got) == ITEM_KEYS
    assert got["status"] == "processing"
    assert parse_utc(got["started_at"]) - parse_utc(got["created_at"]) == timedelta(seconds=1)
    for key in ("source", "amount", "finished_at", "error_code"):
        assert got[key] is None, key


@pytest.mark.usefixtures("eurusd")
def test_get_done_has_mt5_source_and_amount(
    client: TestClient, db_engine: Engine, account: Account
) -> None:
    item = accepted(client, eurusd_body(account))
    set_state(db_engine, item["id"], DONE)

    got = get_item(client, item["id"])

    assert got["status"] == "done"
    assert got["source"] == "mt5"
    assert D(got["amount"]) == D("550.25")
    assert "e" not in got["amount"].lower()
    assert got["currency"] == "USD"
    assert got["error_code"] is None
    assert parse_utc(got["finished_at"]) - parse_utc(got["created_at"]) == timedelta(seconds=2)
    assert parse_utc(got["started_at"]) - parse_utc(got["created_at"]) == timedelta(seconds=1)
    for key in ("account_id", "symbol", "direction", "volume", "entry", "expires_at"):
        assert got[key] == item[key], key


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    ("sql_set", "status", "error_code", "started"),
    [
        (FAILED, "failed", "timeout", True),
        (INTERRUPTED, "failed", "interrupted", True),
        (EXPIRED, "expired", "request_expired", False),
    ],
)
def test_get_failed_or_expired_has_error_code_and_no_amount(
    client: TestClient,
    db_engine: Engine,
    account: Account,
    sql_set: str,
    status: str,
    error_code: str,
    started: bool,
) -> None:
    item = accepted(client, eurusd_body(account))
    set_state(db_engine, item["id"], sql_set)

    got = get_item(client, item["id"])

    assert got["status"] == status
    assert got["error_code"] == error_code
    assert got["source"] is None
    assert got["amount"] is None
    assert got["finished_at"] is not None
    assert (got["started_at"] is not None) is started


def test_get_unknown_id_is_404_with_details_id(client: TestClient) -> None:
    error = error_of(client.get(f"{URL}/987654"), 404, "not_found")

    assert error["details"] == {"id": 987654}


@pytest.mark.usefixtures("eurusd")
def test_get_never_changes_the_row(
    client: TestClient, db_session: Session, account: Account
) -> None:
    item = accepted(client, eurusd_body(account))
    get_item(client, item["id"])
    get_item(client, item["id"])

    db_session.expire_all()
    rows = db_session.scalars(select(CalculatorMarginRequest)).all()
    assert [(r.id, r.status, r.started_at) for r in rows] == [(item["id"], "pending", None)]
