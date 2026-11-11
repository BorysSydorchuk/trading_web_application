"""Calculator API (docs/api.md M5-04c). Runs against the test DB.

All specs here are SYNTHETIC (EURUSD-like and GER40-like), never broker evidence.
Pure sizing arithmetic is covered in tests/domain/test_position_size.py; these tests
cover wiring: selection, balance source, error mapping, serialization and margin metadata.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.config_files import reload_config
from app.domain.position_size import PositionSizeError
from app.domain.position_size import SymbolSpec as CoreSpec
from app.models import Account
from app.models.account import SymbolSpec
from app.models.calculator import CalculatorMarginRequest
from app.services.calculator import error_details
from tests.symbols_fixture import use_test_config

D = Decimal
SYNCED_AT = datetime(2026, 11, 1, 8, 30, tzinfo=UTC)
BALANCE_AT = datetime(2026, 11, 8, 17, 5, tzinfo=UTC)
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
_logins = itertools.count(70000001)

SPEC_KEYS = {
    "symbol",
    "broker_symbol",
    "contract_size",
    "point",
    "tick_size",
    "tick_value_loss",
    "volume_min",
    "volume_step",
    "volume_max",
    "digits",
    "currency_profit",
    "currency_margin",
    "synced_at",
}
RESULT_KEYS = {
    "account_id",
    "symbol",
    "direction",
    "entry",
    "sl_price",
    "sl_distance",
    "sl_points",
    "balance",
    "balance_source",
    "balance_synced_at",
    "currency",
    "risk_percent",
    "risk_amount",
    "risk_budget",
    "volume",
    "actual_risk",
    "actual_risk_percent",
    "tp_1_5",
    "tp_2",
    "tp_3",
    "specs_at",
    "margin",
    "loss_per_tick",  # M5-09
    "conversion",  # M5-09: null for same-currency specs
}
MARGIN_KEYS = {
    "source",
    "amount",
    "currency",
    "calculated_at",
    "sample_price",
    "sample_volume",
    "reason",
}


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


def make_account(db: Session, **changes: Any) -> Account:
    values: dict[str, Any] = {
        "name": f"Synthetic {next(_logins)}",
        "firm": "Fixture",
        "program": "Fixture",
        "phase": "phase_1",
        "login": next(_logins),
        "server": "Fixture",
        "starting_balance": D("99999.00"),  # must never be used as a balance fallback
        "currency": "USD",
        "reference_balance": D("10000.00"),
    }
    row = Account(**(values | changes))
    db.add(row)
    db.commit()
    return row


def make_spec(db: Session, account: Account, symbol: str, **changes: Any) -> SymbolSpec:
    # Synthetic EURUSD-like defaults.
    values: dict[str, Any] = {
        "account_id": account.id,
        "symbol": symbol,
        "contract_size": D("100000"),
        "tick_size": D("0.00001"),
        "tick_value": D("1"),
        "point": D("0.00001"),
        "tick_value_loss": D("1"),
        "volume_min": D("0.01"),
        "volume_step": D("0.01"),
        "volume_max": D("100"),
        "digits": 5,
        "currency_profit": "USD",
        "currency_margin": "USD",
        "synced_at": SYNCED_AT,
    }
    row = SymbolSpec(**(values | changes))
    db.add(row)
    db.commit()
    return row


def make_ger40(
    db: Session, account: Account, symbol: str = "GER40.cash", **changes: Any
) -> SymbolSpec:
    # Synthetic GER40-like: 60 ticks (30 index points) = 150 per lot.
    values: dict[str, Any] = {
        "contract_size": D("1"),
        "point": D("0.1"),
        "tick_size": D("0.5"),
        "tick_value": D("2.5"),
        "tick_value_loss": D("2.5"),
        "digits": 1,
    }
    return make_spec(db, account, symbol, **(values | changes))


def make_margin_request(db: Session, account: Account, **changes: Any) -> CalculatorMarginRequest:
    values: dict[str, Any] = {
        "account_id": account.id,
        "symbol": "GER40.cash",
        "direction": "buy",
        "volume": D("0.10"),
        "entry": D("19100.5"),
        "currency": "USD",
        "status": "done",
        "margin": D("2000"),
        "created_at": T0,
        "started_at": T0 + timedelta(seconds=1),
        "finished_at": T0 + timedelta(seconds=2),
        "expires_at": T0 + timedelta(minutes=1),
    }
    row = CalculatorMarginRequest(**(values | changes))
    db.add(row)
    db.commit()
    return row


def later_times(offset: timedelta) -> dict[str, Any]:
    return {
        "created_at": T0 + offset,
        "started_at": T0 + offset,
        "finished_at": T0 + offset + timedelta(seconds=1),
        "expires_at": T0 + offset + timedelta(minutes=1),
    }


@pytest.fixture
def test_symbols_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    yield use_test_config(tmp_path, monkeypatch)
    reload_config()


@pytest.fixture
def account(db_session: Session) -> Account:
    return make_account(db_session)


@pytest.fixture
def eurusd(db_session: Session, account: Account) -> SymbolSpec:
    return make_spec(db_session, account, "EURUSD")


@pytest.fixture
def ger40(db_session: Session, account: Account) -> SymbolSpec:
    return make_ger40(db_session, account)


def eurusd_body(account: Account, **changes: Any) -> dict[str, Any]:
    # Synthetic: 200 ticks to SL = 200 per lot; 1% of 10000 = 100 -> 0.50 lot.
    body: dict[str, Any] = {
        "account_id": account.id,
        "symbol": "EURUSD",
        "direction": "buy",
        "entry": "1.10000",
        "sl_price": "1.09800",
    }
    return body | changes


def ger40_body(account: Account, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "account_id": account.id,
        "symbol": "GER40.cash",
        "direction": "buy",
        "entry": "19000",
        "sl_price": "18970",
    }
    return body | changes


def calculate(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post("/api/calculator/calculate", json=body)


def calculate_raw(client: TestClient, body: dict[str, Any]) -> Any:
    # ASCII-escaped JSON, so NUL and lone surrogates travel as \u escapes like a real client.
    return client.post(
        "/api/calculator/calculate",
        content=json.dumps(body, ensure_ascii=True),
        headers={"Content-Type": "application/json"},
    )


def ok(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = calculate(client, body)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def error_of(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == code
    return error


def parse_utc(value: str) -> datetime:
    assert value.endswith("Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def request_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(CalculatorMarginRequest)) or 0


# --- GET /api/accounts/{id}/symbol-specs ---


def test_symbol_specs_items_have_exact_shape_and_symbols_yaml_order(
    client: TestClient,
    db_session: Session,
    account: Account,
    test_symbols_config: Path,  # fixed symbols.yaml: EURUSD is a configured name
) -> None:
    # M5-08: symbols.yaml names first (EURUSD), then the others by name.
    make_ger40(db_session, account, "GER40.cash")
    make_spec(db_session, account, "EURUSD")
    make_spec(db_session, account, "AUDUSD")

    response = client.get(f"/api/accounts/{account.id}/symbol-specs")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["symbol"] for item in items] == ["EURUSD", "AUDUSD", "GER40.cash"]
    assert set(items[0]) == SPEC_KEYS
    eurusd = items[0]
    assert eurusd["broker_symbol"] == "EURUSD"
    assert D(eurusd["tick_size"]) == D("0.00001")
    assert D(eurusd["point"]) == D("0.00001")
    assert D(eurusd["tick_value_loss"]) == D("1")
    assert D(eurusd["volume_min"]) == D("0.01")
    assert D(eurusd["volume_max"]) == D("100")
    assert eurusd["digits"] == 5
    assert eurusd["currency_profit"] == "USD"
    assert eurusd["currency_margin"] == "USD"
    assert isinstance(eurusd["contract_size"], str)
    assert parse_utc(eurusd["synced_at"]) == SYNCED_AT


def test_symbol_specs_not_yet_synced_point_and_loss_tick_value_are_null(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "EURUSD", point=None, tick_value_loss=None)

    items = client.get(f"/api/accounts/{account.id}/symbol-specs").json()["items"]

    assert items[0]["point"] is None
    assert items[0]["tick_value_loss"] is None


def test_symbol_specs_account_without_specs_returns_empty_list(
    client: TestClient, account: Account
) -> None:
    response = client.get(f"/api/accounts/{account.id}/symbol-specs")

    assert response.status_code == 200
    # M5-08: never synced (no rows at all) -> nothing reported missing; the UI shows its hint.
    assert response.json() == {"items": [], "missing": []}


def test_symbol_specs_missing_account_is_404(client: TestClient) -> None:
    response = client.get("/api/accounts/999999/symbol-specs")

    error = error_of(response, 404, "not_found")

    assert error["details"]["account_id"] == 999999


def test_symbol_specs_of_another_account_are_not_returned(
    client: TestClient, db_session: Session, account: Account
) -> None:
    other = make_account(db_session)
    make_spec(db_session, other, "EURUSD")
    make_spec(db_session, account, "GBPUSD")

    items = client.get(f"/api/accounts/{account.id}/symbol-specs").json()["items"]

    assert [item["symbol"] for item in items] == ["GBPUSD"]


# --- calculate: happy paths ---


@pytest.mark.usefixtures("eurusd")
def test_default_risk_is_one_percent_and_response_has_the_exact_keys(
    client: TestClient, account: Account
) -> None:
    data = ok(client, eurusd_body(account))

    assert set(data) == RESULT_KEYS
    assert data["account_id"] == account.id
    assert data["symbol"] == "EURUSD"
    assert data["direction"] == "buy"
    assert D(data["entry"]) == D("1.1")
    assert D(data["sl_price"]) == D("1.098")
    assert D(data["sl_distance"]) == D("0.002")
    assert D(data["sl_points"]) == D("200")
    assert D(data["risk_percent"]) == D("1")
    assert data["risk_amount"] is None
    assert D(data["risk_budget"]) == D("100")
    assert D(data["volume"]) == D("0.5")
    assert D(data["actual_risk"]) == D("100")
    assert D(data["actual_risk_percent"]) == D("1")
    assert data["currency"] == "USD"
    assert parse_utc(data["specs_at"]) == SYNCED_AT


@pytest.mark.usefixtures("eurusd")
def test_explicit_risk_percent_is_used_and_risk_amount_is_null(
    client: TestClient, account: Account
) -> None:
    data = ok(client, eurusd_body(account, risk_percent="0.5"))

    assert D(data["risk_percent"]) == D("0.5")
    assert data["risk_amount"] is None
    assert D(data["risk_budget"]) == D("50")
    assert D(data["volume"]) == D("0.25")


@pytest.mark.usefixtures("eurusd")
def test_risk_amount_mode_returns_amount_and_null_percent(
    client: TestClient, account: Account
) -> None:
    data = ok(client, eurusd_body(account, risk_amount="100"))

    assert data["risk_percent"] is None
    assert D(data["risk_amount"]) == D("100")
    assert D(data["risk_budget"]) == D("100")
    assert D(data["volume"]) == D("0.5")


@pytest.mark.usefixtures("ger40")
@pytest.mark.parametrize("sl_points", [300, "300"])
def test_sl_points_input_accepts_json_integer_or_string(
    client: TestClient, account: Account, sl_points: int | str
) -> None:
    body = ger40_body(account, sl_points=sl_points)
    del body["sl_price"]

    data = ok(client, body)

    assert D(data["sl_price"]) == D("18970")
    assert D(data["sl_distance"]) == D("30")
    assert D(data["sl_points"]) == D("300")
    assert D(data["volume"]) == D("0.66")
    assert D(data["actual_risk"]) == D("99")


@pytest.mark.usefixtures("ger40")
def test_sl_price_input_derives_sl_points_from_the_broker_point(
    client: TestClient, account: Account
) -> None:
    data = ok(client, ger40_body(account))

    assert D(data["sl_points"]) == D("300")  # 30 index points / point 0.1
    assert D(data["volume"]) == D("0.66")


@pytest.mark.usefixtures("eurusd")
def test_sell_direction_mirrors_stop_and_targets(client: TestClient, account: Account) -> None:
    data = ok(client, eurusd_body(account, direction="sell", sl_price="1.10200"))

    assert data["direction"] == "sell"
    assert D(data["sl_price"]) == D("1.102")
    assert D(data["tp_1_5"]) == D("1.097")
    assert D(data["tp_2"]) == D("1.096")
    assert D(data["tp_3"]) == D("1.094")


@pytest.mark.usefixtures("eurusd")
def test_buy_targets_use_rr_1_5_2_and_3(client: TestClient, account: Account) -> None:
    data = ok(client, eurusd_body(account))

    assert D(data["tp_1_5"]) == D("1.103")
    assert D(data["tp_2"]) == D("1.104")
    assert D(data["tp_3"]) == D("1.106")


@pytest.mark.usefixtures("eurusd")
def test_volume_is_floored_to_step_and_actual_risk_never_exceeds_budget(
    client: TestClient, account: Account
) -> None:
    data = ok(client, eurusd_body(account, risk_amount="119"))  # 119 / 200 = 0.595

    assert D(data["volume"]) == D("0.59")
    assert D(data["actual_risk"]) == D("118")
    assert D(data["actual_risk"]) <= D(data["risk_budget"])


@pytest.mark.usefixtures("eurusd")
def test_reference_balance_is_preferred_over_synced_balance(
    client: TestClient, db_session: Session, account: Account
) -> None:
    account.balance = D("20000.00")
    account.balance_synced_at = BALANCE_AT
    db_session.commit()

    data = ok(client, eurusd_body(account))

    assert data["balance"] == "10000.00"
    assert data["balance_source"] == "reference"
    assert data["balance_synced_at"] is None
    assert D(data["volume"]) == D("0.5")


def test_synced_balance_is_used_without_reference_balance(
    client: TestClient, db_session: Session
) -> None:
    account = make_account(
        db_session, reference_balance=None, balance=D("20000.00"), balance_synced_at=BALANCE_AT
    )
    make_spec(db_session, account, "EURUSD")

    data = ok(client, eurusd_body(account))

    assert data["balance"] == "20000.00"
    assert data["balance_source"] == "synced"
    assert parse_utc(data["balance_synced_at"]) == BALANCE_AT
    assert D(data["volume"]) == D("1")


def test_money_and_price_strings_use_plain_notation_without_exponent(
    client: TestClient, db_session: Session, account: Account
) -> None:
    # Synthetic 7-digit symbol: a one-tick distance of 1E-7 must not serialize as "1E-7".
    make_spec(
        db_session,
        account,
        "TINY",
        point=D("0.0000001"),
        tick_size=D("0.0000001"),
        tick_value_loss=D("0.0000001"),
        digits=7,
    )
    body = eurusd_body(account, symbol="TINY", entry="1.1000000", sl_price="1.0999999")

    data = ok(client, body)

    assert D(data["sl_distance"]) == D("0.0000001")
    for key in (
        "entry",
        "sl_price",
        "sl_distance",
        "sl_points",
        "balance",
        "risk_budget",
        "volume",
        "actual_risk",
        "actual_risk_percent",
        "tp_1_5",
        "tp_2",
        "tp_3",
    ):
        assert isinstance(data[key], str), key
        assert "e" not in data[key].lower(), (key, data[key])


def test_non_terminating_sl_points_is_plain_with_160_significant_digits(
    client: TestClient, db_session: Session, account: Account
) -> None:
    # Synthetic: distance 0.1 / point 0.3 = 1/3 broker point.
    make_spec(
        db_session,
        account,
        "THIRD",
        point=D("0.3"),
        tick_size=D("0.1"),
        tick_value_loss=D("1"),
        digits=1,
    )
    body = eurusd_body(account, symbol="THIRD", entry="100.0", sl_price="99.9")

    data = ok(client, body)

    assert data["sl_points"] == "0." + "3" * 160


# --- calculate: validation (422 validation_error) ---


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"entry": 1.1}, "entry"),  # JSON float
        ({"entry": True}, "entry"),
        ({"entry": "NaN"}, "entry"),
        ({"entry": "Infinity"}, "entry"),
        ({"entry": None}, "entry"),
        ({"entry": "0"}, "entry"),
        ({"entry": "-1.1"}, "entry"),
        ({"entry": "1" * 65}, "entry"),  # over 64 coefficient digits
        ({"entry": "0." + "0" * 64 + "1"}, "entry"),  # exponent below -64
        ({"sl_price": 1.098}, "sl_price"),
        ({"sl_price": "0"}, "sl_price"),
        ({"risk_percent": 1.0}, "risk_percent"),
        ({"risk_percent": "0"}, "risk_percent"),
        ({"risk_percent": "-1"}, "risk_percent"),
        ({"risk_percent": None}, "risk_percent"),  # null is not "not supplied"
        ({"risk_amount": False}, "risk_amount"),
        ({"risk_amount": "0"}, "risk_amount"),
        ({"direction": "hold"}, "direction"),
        ({"bogus": 1}, "bogus"),  # unknown key
    ],
)
def test_invalid_field_is_422_validation_error_naming_the_field(
    client: TestClient, account: Account, changes: dict[str, Any], field: str
) -> None:
    error = error_of(calculate(client, eurusd_body(account, **changes)), 422, "validation_error")

    assert field in error["details"]["fields"]


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    ("changes", "removed", "named"),
    [
        ({"sl_points": "200"}, [], {"sl_price", "sl_points"}),  # both sl fields
        ({}, ["sl_price"], {"sl_price", "sl_points"}),  # neither sl field
        ({"risk_percent": "1", "risk_amount": "100"}, [], {"risk_percent", "risk_amount"}),
    ],
)
def test_sl_and_risk_field_combinations_are_422_validation_error(
    client: TestClient,
    account: Account,
    changes: dict[str, Any],
    removed: list[str],
    named: set[str],
) -> None:
    body = eurusd_body(account, **changes)
    for key in removed:
        del body[key]

    error = error_of(calculate(client, body), 422, "validation_error")

    assert set(error["details"]["fields"]) & named


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize("missing", ["account_id", "symbol", "direction", "entry"])
def test_missing_required_field_is_422_validation_error(
    client: TestClient, account: Account, missing: str
) -> None:
    body = eurusd_body(account)
    del body[missing]

    error = error_of(calculate(client, body), 422, "validation_error")

    assert missing in error["details"]["fields"]


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(  # reversed pair: stays two lone surrogates after decoding
    "symbol", ["\u0000", "EUR\u0000USD", "\ud800", "EUR\udfffUSD", "\udc00\udbff"]
)
def test_symbol_with_nul_or_surrogate_is_422_naming_symbol(
    client: TestClient, account: Account, symbol: str
) -> None:
    response = calculate_raw(client, eurusd_body(account, symbol=symbol))

    error = error_of(response, 422, "validation_error")

    assert "symbol" in error["details"]["fields"]


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize("symbol", [" EURUSD", "EURUSD ", "eurusd"])
def test_symbol_is_not_stripped_or_case_folded(
    client: TestClient, account: Account, symbol: str
) -> None:
    error = error_of(calculate(client, eurusd_body(account, symbol=symbol)), 404, "not_found")

    assert error["details"]["symbol"] == symbol


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize("account_id", [True, "1"])
def test_account_id_bool_or_string_is_422(
    client: TestClient, account: Account, account_id: Any
) -> None:
    body = eurusd_body(account, account_id=account_id)

    error = error_of(calculate(client, body), 422, "validation_error")

    assert "account_id" in error["details"]["fields"]


def test_core_validation_error_always_has_a_fields_object() -> None:
    # The working-precision guard is unreachable within the API limits; test the mapping.
    spec = CoreSpec(
        point=D("0.1"),
        tick_size=D("0.5"),
        tick_value_loss=D("2.5"),
        volume_min=D("0.01"),
        volume_step=D("0.01"),
        volume_max=D("100"),
    )
    no_fields = PositionSizeError("too precise", "validation_error")
    named = PositionSizeError("entry is bad", "validation_error", ("entry",))

    assert error_details(no_fields, spec) == {"fields": {}}
    assert error_details(named, spec) == {"fields": {"entry": "entry is bad"}}


# --- calculate: not found, balance, specs ---


def test_missing_account_is_404_with_account_id(client: TestClient) -> None:
    body = {
        "account_id": 999999,
        "symbol": "EURUSD",
        "direction": "buy",
        "entry": "1.1",
        "sl_price": "1.09",
    }

    error = error_of(calculate(client, body), 404, "not_found")

    assert error["details"]["account_id"] == 999999


@pytest.mark.usefixtures("eurusd")
def test_unknown_symbol_is_404_with_symbol(client: TestClient, account: Account) -> None:
    error = error_of(calculate(client, eurusd_body(account, symbol="GBPUSD")), 404, "not_found")

    assert error["details"]["symbol"] == "GBPUSD"


def test_symbol_is_never_prefix_matched(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "EURUSD.raw")

    error = error_of(calculate(client, eurusd_body(account)), 404, "not_found")

    assert error["details"]["symbol"] == "EURUSD"


def test_symbol_of_another_account_is_404(client: TestClient, db_session: Session) -> None:
    owner = make_account(db_session)
    make_spec(db_session, owner, "EURUSD")
    other = make_account(db_session)

    error = error_of(calculate(client, eurusd_body(other)), 404, "not_found")

    assert error["details"]["symbol"] == "EURUSD"


def test_no_reference_and_no_synced_balance_is_409_balance_unavailable(
    client: TestClient, db_session: Session
) -> None:
    # starting_balance is set (99999) and must not be used as an implicit fallback.
    account = make_account(db_session, reference_balance=None, balance=None)
    make_spec(db_session, account, "EURUSD")

    error_of(calculate(client, eurusd_body(account)), 409, "balance_unavailable")


@pytest.mark.parametrize(
    "changes",
    [
        {"reference_balance": D("0")},
        {"reference_balance": D("-1.00")},
        {"reference_balance": None, "balance": D("0"), "balance_synced_at": BALANCE_AT},
    ],
)
def test_nonpositive_effective_balance_is_409_balance_unavailable(
    client: TestClient, db_session: Session, changes: dict[str, Any]
) -> None:
    account = make_account(db_session, **changes)
    make_spec(db_session, account, "EURUSD")

    error_of(calculate(client, eurusd_body(account)), 409, "balance_unavailable")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE accounts SET reference_balance = 'NaN' WHERE id = :id",
        "UPDATE accounts SET balance = 'NaN' WHERE id = :id",
    ],
)
def test_nan_effective_balance_is_409_balance_unavailable(
    client: TestClient, db_session: Session, statement: str
) -> None:
    account = make_account(db_session, reference_balance=None, balance_synced_at=BALANCE_AT)
    make_spec(db_session, account, "EURUSD")
    # Postgres NUMERIC accepts NaN and the accounts columns have no CHECK against it.
    db_session.execute(text(statement), {"id": account.id})
    db_session.commit()

    error_of(calculate(client, eurusd_body(account)), 409, "balance_unavailable")


def test_nan_sizing_spec_is_409_specs_incomplete(
    client: TestClient, db_session: Session, account: Account
) -> None:
    spec = make_spec(db_session, account, "EURUSD")
    db_session.execute(
        text("UPDATE symbol_specs SET tick_value_loss = 'NaN' WHERE id = :id"), {"id": spec.id}
    )
    db_session.commit()

    error = error_of(calculate(client, eurusd_body(account)), 409, "specs_incomplete")

    assert error["details"]["missing"] == ["tick_value_loss"]


@pytest.mark.parametrize(
    ("changes", "missing"),
    [
        ({"point": None}, ["point"]),
        ({"point": None, "tick_value_loss": None}, ["point", "tick_value_loss"]),
        ({"tick_value_loss": D("0")}, ["tick_value_loss"]),
    ],
)
def test_null_or_nonpositive_specs_are_409_specs_incomplete_listing_the_keys(
    client: TestClient,
    db_session: Session,
    account: Account,
    changes: dict[str, Any],
    missing: list[str],
) -> None:
    make_spec(db_session, account, "EURUSD", **changes)

    error = error_of(calculate(client, eurusd_body(account)), 409, "specs_incomplete")

    assert sorted(error["details"]["missing"]) == sorted(missing)


def test_incomplete_specs_are_reported_even_with_sl_points_input(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "EURUSD", point=None)
    body = eurusd_body(account, sl_points="200")
    del body["sl_price"]

    error = error_of(calculate(client, body), 409, "specs_incomplete")

    assert error["details"]["missing"] == ["point"]


def test_volume_limits_off_the_step_grid_are_409_specs_invalid(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "EURUSD", volume_min=D("0.03"), volume_step=D("0.02"))

    error_of(calculate(client, eurusd_body(account)), 409, "specs_invalid")


# --- calculate: domain rejections ---


@pytest.mark.usefixtures("eurusd")
@pytest.mark.parametrize(
    ("direction", "sl_price"),
    [("buy", "1.10200"), ("buy", "1.10000"), ("sell", "1.09800")],
)
def test_stop_on_the_wrong_side_is_422_invalid_stop(
    client: TestClient, account: Account, direction: str, sl_price: str
) -> None:
    body = eurusd_body(account, direction=direction, sl_price=sl_price)

    error_of(calculate(client, body), 422, "invalid_stop")


@pytest.mark.usefixtures("eurusd")
def test_sl_points_beyond_zero_price_is_422_invalid_stop(
    client: TestClient, account: Account
) -> None:
    body = eurusd_body(account, sl_points="110001")  # 1.10001 of distance from entry 1.1
    del body["sl_price"]

    error_of(calculate(client, body), 422, "invalid_stop")


@pytest.mark.usefixtures("ger40")
@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        ({"entry": "19000.25"}, ["entry"]),
        ({"sl_price": "18970.25"}, ["sl_price"]),
        ({"entry": "19000.25", "sl_price": "18970.25"}, ["entry", "sl_price"]),
    ],
)
def test_prices_off_the_tick_grid_are_422_off_tick_grid_naming_the_fields(
    client: TestClient, account: Account, changes: dict[str, Any], fields: list[str]
) -> None:
    error = error_of(calculate(client, ger40_body(account, **changes)), 422, "off_tick_grid")

    assert sorted(error["details"]["fields"]) == sorted(fields)


@pytest.mark.usefixtures("eurusd")
def test_budget_below_minimum_volume_is_422_with_volume_min_and_min_volume_risk(
    client: TestClient, account: Account
) -> None:
    error = error_of(
        calculate(client, eurusd_body(account, risk_amount="1")), 422, "below_min_volume"
    )

    assert D(error["details"]["volume_min"]) == D("0.01")
    assert D(error["details"]["min_volume_risk"]) == D("2")  # 0.01 lot * 200 per lot


def test_sell_target_at_or_below_zero_is_422_invalid_targets(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(
        db_session,
        account,
        "SYNTH",
        point=D("0.01"),
        tick_size=D("0.01"),
        tick_value_loss=D("1"),
        digits=2,
    )
    body = eurusd_body(account, symbol="SYNTH", direction="sell", entry="1", sl_price="2")

    error_of(calculate(client, body), 422, "invalid_targets")


# --- calculate: margin metadata ---


@pytest.mark.usefixtures("ger40")
def test_without_a_done_request_margin_is_unavailable_never_zero(
    client: TestClient, account: Account
) -> None:
    margin = ok(client, ger40_body(account))["margin"]

    assert set(margin) == MARGIN_KEYS
    assert margin["source"] == "unavailable"
    assert margin["amount"] is None
    assert margin["reason"] == "no_cached_margin"
    assert margin["calculated_at"] is None
    assert margin["sample_price"] is None
    assert margin["sample_volume"] is None


@pytest.mark.usefixtures("ger40")
def test_latest_done_request_is_scaled_linearly_by_volume(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_margin_request(db_session, account)  # 2000 USD for 0.10 lot at 19100.5

    data = ok(client, ger40_body(account))  # sized volume 0.66

    margin = data["margin"]
    assert set(margin) == MARGIN_KEYS
    assert margin["source"] == "cached_estimate"
    assert margin["reason"] is None
    assert isinstance(margin["amount"], str)
    assert D(margin["amount"]) == D("13200")  # 2000 * 0.66 / 0.10
    assert margin["currency"] == "USD"
    assert parse_utc(margin["calculated_at"]) == T0 + timedelta(seconds=2)
    assert D(margin["sample_price"]) == D("19100.5")
    assert D(margin["sample_volume"]) == D("0.1")
    assert D(data["volume"]) == D("0.66")


@pytest.mark.usefixtures("ger40")
def test_margin_estimate_is_not_rounded_at_the_default_28_digit_context(
    client: TestClient, db_session: Session, account: Account
) -> None:
    sample_margin = D("12345678901234567890.12345678")  # 28 digits, fits NUMERIC(28,8)
    make_margin_request(db_session, account, margin=sample_margin, volume=D("0.10"))

    data = ok(client, ger40_body(account))  # sized volume 0.66

    with localcontext() as context:
        context.prec = 200
        exact = sample_margin * D(data["volume"]) / D("0.10")
    assert D(data["volume"]) == D("0.66")
    assert exact == D("81481480748148148074.814814748")
    assert D(data["margin"]["amount"]) == exact


@pytest.mark.usefixtures("ger40")
def test_most_recently_finished_done_request_wins(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_margin_request(db_session, account, margin=D("1000"), entry=D("18000"))
    newest = later_times(timedelta(hours=1))
    make_margin_request(db_session, account, margin=D("3000"), entry=D("19200"), **newest)

    margin = ok(client, ger40_body(account))["margin"]

    assert D(margin["amount"]) == D("19800")  # 3000 * 0.66 / 0.10
    assert D(margin["sample_price"]) == D("19200")
    assert parse_utc(margin["calculated_at"]) == newest["finished_at"]


@pytest.mark.usefixtures("ger40")
def test_finished_at_tie_is_broken_by_the_higher_id(
    client: TestClient, db_session: Session, account: Account
) -> None:
    older = make_margin_request(db_session, account, margin=D("1000"))
    newer = make_margin_request(db_session, account, margin=D("3000"))  # same finished_at

    margin = ok(client, ger40_body(account))["margin"]

    assert newer.id > older.id
    assert newer.finished_at == older.finished_at
    assert D(margin["amount"]) == D("19800")  # 3000 * 0.66 / 0.10


@pytest.mark.usefixtures("ger40")
@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending", "margin": None, "started_at": None, "finished_at": None},
        {"status": "processing", "margin": None, "finished_at": None},
        {"status": "failed", "margin": None, "error_code": "mt5_error"},
        {"status": "expired", "margin": None, "started_at": None, "error_code": "request_expired"},
        {"direction": "sell"},
        {"symbol": "GER40"},  # exact symbol only, no prefix match either way
    ],
)
def test_non_matching_rows_never_produce_an_estimate(
    client: TestClient, db_session: Session, account: Account, changes: dict[str, Any]
) -> None:
    make_margin_request(db_session, account, **changes)

    margin = ok(client, ger40_body(account))["margin"]

    assert margin["source"] == "unavailable"
    assert margin["amount"] is None
    assert margin["reason"] == "no_cached_margin"


@pytest.mark.usefixtures("ger40")
def test_done_request_of_another_account_is_ignored(
    client: TestClient, db_session: Session, account: Account
) -> None:
    other = make_account(db_session)
    make_margin_request(db_session, other)

    margin = ok(client, ger40_body(account))["margin"]

    assert margin["source"] == "unavailable"


@pytest.mark.usefixtures("ger40")
def test_newer_unusable_rows_do_not_hide_an_older_matching_done_request(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_margin_request(db_session, account)
    newer = later_times(timedelta(hours=2))
    make_margin_request(
        db_session, account, status="failed", margin=None, error_code="mt5_error", **newer
    )
    make_margin_request(db_session, account, direction="sell", margin=D("9999"), **newer)

    margin = ok(client, ger40_body(account))["margin"]

    assert margin["source"] == "cached_estimate"
    assert D(margin["amount"]) == D("13200")


@pytest.mark.usefixtures("ger40")
@pytest.mark.parametrize("with_done_request", [False, True])
def test_calculate_never_creates_a_margin_request(
    client: TestClient, db_session: Session, account: Account, with_done_request: bool
) -> None:
    if with_done_request:
        make_margin_request(db_session, account)
    before = request_count(db_session)

    ok(client, ger40_body(account))

    assert request_count(db_session) == before


@pytest.mark.usefixtures("eurusd")
def test_rejected_calculation_never_creates_a_margin_request(
    client: TestClient, db_session: Session, account: Account
) -> None:
    before = request_count(db_session)

    calculate(client, eurusd_body(account, sl_price="1.10200"))  # invalid_stop

    assert request_count(db_session) == before
