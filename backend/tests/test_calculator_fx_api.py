"""Calculator with cross-currency specs (docs/api.md "M5-09 Cross-currency loss value").

The real FundedNext case from the owner check: GER30 (canonical GER40), profit currency EUR,
account USD, tick 0.01, contract 10, MT5 tick_value_loss 0.12 (stale) but the real P&L uses
EURUSD 1.1091 -> 0.11091 USD per tick per lot. Buy 26478.80, SL 26414.20 = 6460 ticks:
budget 104.02 -> 0.14 lot (0.13 with the stale 0.12), budget 100 -> 0.13 lot.

Assumed ORM model: ``app.models.FxRate`` (table ``fx_rates``) with columns account_id,
from_currency, to_currency, pair, inverted, bid, ask, rate, rate_at, synced_at, and
``SymbolSpec.mt5_loss_per_tick`` / ``mt5_loss_per_tick_at``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config_files import reload_config
from app.models import Account, FxRate
from app.models.account import SymbolSpec
from app.schemas.calculator import CalculateInput
from app.services import calculator
from tests.symbols_fixture import use_test_config
from tests.test_calculator_api import (
    calculate,
    error_of,
    eurusd_body,
    make_account,
    make_spec,
    ok,
    parse_utc,
    request_count,
)

D = Decimal
URL_MARGIN = "/api/calculator/margin-requests"
CONVERSION_KEYS = {
    "pair",
    "from_currency",
    "to_currency",
    "rate",
    "side",
    "inverted",
    "rate_at",
    "stale",
    "source",
    "rate_loss_per_tick",
    "mt5_loss_per_tick",
    "mt5_checked_at",
}


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture(autouse=True)
def _symbols(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    yield use_test_config(tmp_path, monkeypatch)
    reload_config()


@pytest.fixture
def account(db_session: Session) -> Account:
    return make_account(db_session, reference_balance=D("10401.70"))


def make_ger30(db: Session, account: Account, **changes: Any) -> SymbolSpec:
    values: dict[str, Any] = {
        "canonical_symbol": "GER40",
        "contract_size": D("10"),
        "tick_size": D("0.01"),
        "tick_value": D("0.12"),
        "tick_value_loss": D("0.12"),
        "point": D("0.01"),
        "digits": 2,
        "currency_profit": "EUR",
        "currency_margin": "EUR",
    }
    return make_spec(db, account, "GER30", **(values | changes))


def make_fx_rate(db: Session, account: Account, **changes: Any) -> FxRate:
    rate_at = datetime.now(UTC) - timedelta(minutes=5)
    values: dict[str, Any] = {
        "account_id": account.id,
        "from_currency": "EUR",
        "to_currency": "USD",
        "pair": "EURUSD",
        "inverted": False,
        "bid": D("1.10905"),
        "ask": D("1.1091"),
        "rate": D("1.1091"),
        "rate_at": rate_at,
        "synced_at": rate_at,
    }
    row = FxRate(**(values | changes))
    db.add(row)
    db.commit()
    return row


def ger30_body(account: Account, **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "account_id": account.id,
        "symbol": "GER40",
        "direction": "buy",
        "entry": "26478.80",
        "sl_price": "26414.20",
        "risk_amount": "104.02",
    }
    return body | changes


# --- the real case ------------------------------------------------------------------------------


def test_real_ger30_case_sizes_014_lot_from_the_rate(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_fx_rate(db_session, account)

    data = ok(client, ger30_body(account))

    assert D(data["volume"]) == D("0.14")
    assert D(data["loss_per_tick"]) == D("0.11091")
    assert D(data["actual_risk"]) == D("0.14") * 6460 * D("0.11091")  # 100.30... <= 104.02
    assert D(data["risk_budget"]) == D("104.02")
    assert D(data["sl_points"]) == D("6460")


def test_budget_100_gives_013_lot(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_fx_rate(db_session, account)

    data = ok(client, ger30_body(account, risk_amount="100"))

    assert D(data["volume"]) == D("0.13")
    assert D(data["loss_per_tick"]) == D("0.11091")


def test_the_stale_tick_value_is_never_used_for_cross_currency_sizing(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account, tick_value=D("0.12"), tick_value_loss=D("0.12"))
    make_fx_rate(db_session, account)

    data = ok(client, ger30_body(account))

    # With 0.12 the answer would be 0.13 lot (104.02 / 775.2).
    assert D(data["volume"]) == D("0.14")
    assert D(data["loss_per_tick"]) != D("0.12")


def test_conversion_object_has_the_contract_shape(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    row = make_fx_rate(db_session, account)

    conversion = ok(client, ger30_body(account))["conversion"]

    assert set(conversion) == CONVERSION_KEYS
    assert conversion["pair"] == "EURUSD"
    assert (conversion["from_currency"], conversion["to_currency"]) == ("EUR", "USD")
    assert D(conversion["rate"]) == D("1.1091")
    assert conversion["side"] == "ask"
    assert conversion["inverted"] is False
    assert parse_utc(conversion["rate_at"]) == row.rate_at
    assert conversion["stale"] is False
    assert conversion["source"] == "rate"
    assert D(conversion["rate_loss_per_tick"]) == D("0.11091")
    assert conversion["mt5_loss_per_tick"] is None
    assert conversion["mt5_checked_at"] is None


def test_inverse_pair_is_reported_with_the_bid_side(
    client: TestClient, db_session: Session, account: Account
) -> None:
    # Swiss-franc index: profit CHF, USDCHF 0.8 -> 1 CHF = 1.25 USD; tick 1, contract 1.
    make_spec(
        db_session,
        account,
        "SWI20",
        canonical_symbol="SWI20",
        contract_size=D("1"),
        tick_size=D("1"),
        tick_value=D("1"),
        tick_value_loss=D("1"),
        point=D("1"),
        digits=0,
        currency_profit="CHF",
        currency_margin="CHF",
    )
    make_fx_rate(
        db_session,
        account,
        from_currency="CHF",
        pair="USDCHF",
        inverted=True,
        bid=D("0.8"),
        ask=D("0.8002"),
        rate=D("1.25"),
    )

    data = ok(
        client,
        {
            "account_id": account.id,
            "symbol": "SWI20",
            "direction": "buy",
            "entry": "11000",
            "sl_price": "10950",
            "risk_amount": "125",
        },
    )

    assert D(data["loss_per_tick"]) == D("1.25")
    assert D(data["volume"]) == D("2")  # 125 / (50 ticks * 1.25)
    assert data["conversion"]["inverted"] is True
    assert data["conversion"]["side"] == "bid"
    assert data["conversion"]["pair"] == "USDCHF"


def test_profit_currency_comparison_ignores_case(client: TestClient, db_session: Session) -> None:
    usd_account = make_account(db_session, currency="usd", reference_balance=D("10000"))
    make_spec(db_session, usd_account, "EURUSD", currency_profit="USD")

    data = ok(client, eurusd_body(usd_account))

    assert data["conversion"] is None


def test_rate_lookup_upper_cases_both_currencies(client: TestClient, db_session: Session) -> None:
    lower = make_account(db_session, currency="usd", reference_balance=D("10401.70"))
    make_ger30(db_session, lower, currency_profit="eur")
    make_fx_rate(db_session, lower)  # stored upper-case by the sync

    data = ok(client, ger30_body(lower))

    assert D(data["volume"]) == D("0.14")
    assert (data["conversion"]["from_currency"], data["conversion"]["to_currency"]) == (
        "EUR",
        "USD",
    )


def test_missing_rate_details_are_upper_case(client: TestClient, db_session: Session) -> None:
    lower = make_account(db_session, currency="usd", reference_balance=D("10401.70"))
    make_ger30(db_session, lower, currency_profit="eur")

    error = error_of(calculate(client, ger30_body(lower)), 409, "conversion_rate_unavailable")

    assert error["details"] == {"from_currency": "EUR", "to_currency": "USD"}


# --- stale flag ---------------------------------------------------------------------------------


def test_a_two_hour_old_rate_is_flagged_stale_but_still_used(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    old = datetime.now(UTC) - timedelta(hours=2)
    make_fx_rate(db_session, account, rate_at=old, synced_at=old)

    data = ok(client, ger30_body(account))

    assert data["conversion"]["stale"] is True
    assert D(data["volume"]) == D("0.14")


def test_a_fresh_rate_is_not_stale(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_fx_rate(db_session, account, rate_at=datetime.now(UTC) - timedelta(minutes=59))

    assert ok(client, ger30_body(account))["conversion"]["stale"] is False


# --- MT5 check ----------------------------------------------------------------------------------


def test_check_differing_by_more_than_half_a_percent_is_used(
    client: TestClient, db_session: Session, account: Account
) -> None:
    checked_at = datetime.now(UTC) - timedelta(minutes=3)
    make_ger30(db_session, account, mt5_loss_per_tick=D("0.118"), mt5_loss_per_tick_at=checked_at)
    make_fx_rate(db_session, account)

    data = ok(client, ger30_body(account))

    conversion = data["conversion"]
    assert conversion["source"] == "mt5_check"
    assert D(data["loss_per_tick"]) == D("0.118")
    assert D(conversion["mt5_loss_per_tick"]) == D("0.118")
    assert parse_utc(conversion["mt5_checked_at"]) == checked_at
    assert D(conversion["rate_loss_per_tick"]) == D("0.11091")
    assert D(conversion["rate"]) == D("1.1091")
    assert D(data["volume"]) == D("0.13")  # 104.02 / (6460 * 0.118) = 0.1364


def test_check_within_half_a_percent_keeps_the_rate(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(
        db_session,
        account,
        mt5_loss_per_tick=D("0.11120"),  # +0.26 %
        mt5_loss_per_tick_at=datetime.now(UTC),
    )
    make_fx_rate(db_session, account)

    data = ok(client, ger30_body(account))

    assert data["conversion"]["source"] == "rate"
    assert D(data["loss_per_tick"]) == D("0.11091")
    assert D(data["conversion"]["mt5_loss_per_tick"]) == D("0.11120")
    assert D(data["volume"]) == D("0.14")


# --- no rate ------------------------------------------------------------------------------------


def test_cross_currency_spec_without_a_rate_row_is_409(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)

    error = error_of(calculate(client, ger30_body(account)), 409, "conversion_rate_unavailable")

    assert error["details"] == {"from_currency": "EUR", "to_currency": "USD"}


def test_a_rate_row_of_another_account_does_not_count(
    client: TestClient, db_session: Session, account: Account
) -> None:
    other = make_account(db_session, reference_balance=D("5000"))
    make_ger30(db_session, account)
    make_fx_rate(db_session, other)

    error_of(calculate(client, ger30_body(account)), 409, "conversion_rate_unavailable")


def test_a_rate_row_for_another_currency_does_not_count(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_fx_rate(db_session, account, from_currency="GBP", pair="GBPUSD")

    error_of(calculate(client, ger30_body(account)), 409, "conversion_rate_unavailable")


def test_no_rate_never_falls_back_to_tick_value_even_with_a_check_value(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(
        db_session, account, mt5_loss_per_tick=D("0.11"), mt5_loss_per_tick_at=datetime.now(UTC)
    )

    error_of(calculate(client, ger30_body(account)), 409, "conversion_rate_unavailable")


# --- same-currency specs are unchanged ----------------------------------------------------------


def test_same_currency_spec_has_no_conversion_and_uses_tick_value_loss(
    client: TestClient, db_session: Session
) -> None:
    usd_account = make_account(db_session)  # reference balance 10000 as in eurusd_body
    make_spec(db_session, usd_account, "EURUSD")  # profit USD, account USD

    data = ok(client, eurusd_body(usd_account))

    assert data["conversion"] is None
    assert D(data["loss_per_tick"]) == D("1")
    assert D(data["volume"]) == D("0.50")  # same as before M5-09


def test_xauusd_style_usd_spec_is_unchanged(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(
        db_session,
        account,
        "XAUUSD",
        contract_size=D("100"),
        tick_size=D("0.01"),
        point=D("0.01"),
        tick_value=D("1"),
        tick_value_loss=D("1"),
        digits=2,
    )
    # An unrelated rate row must not change a same-currency spec.
    make_fx_rate(db_session, account)

    data = ok(
        client,
        {
            "account_id": account.id,
            "symbol": "XAUUSD",
            "direction": "buy",
            "entry": "2650.00",
            "sl_price": "2649.00",
            "risk_amount": "100",
        },
    )

    assert data["conversion"] is None
    assert D(data["loss_per_tick"]) == D("1")
    assert D(data["volume"]) == D("1")  # 100 ticks * 1 per lot = 100


def test_same_currency_spec_ignores_a_stored_check_value(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(
        db_session,
        account,
        "EURUSD",
        mt5_loss_per_tick=D("2"),
        mt5_loss_per_tick_at=datetime.now(UTC),
    )

    data = ok(client, eurusd_body(account))

    assert data["conversion"] is None
    assert D(data["loss_per_tick"]) == D("1")


# --- margin requests use the same sizing --------------------------------------------------------


def test_margin_request_post_sizes_with_the_rate(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_fx_rate(db_session, account)

    response = client.post(URL_MARGIN, json=ger30_body(account))

    assert response.status_code == 202, response.text
    item = response.json()
    assert D(item["volume"]) == D("0.14")
    assert item["symbol"] == "GER40"


def test_margin_request_post_without_a_rate_is_409_and_creates_no_row(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)

    response = client.post(URL_MARGIN, json=ger30_body(account))

    error = error_of(response, 409, "conversion_rate_unavailable")
    assert error["details"] == {"from_currency": "EUR", "to_currency": "USD"}
    assert request_count(db_session) == 0


# --- review MEDIUM: injectable clock, contract_size validated separately -----------------------

FIXED_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def sized_conversion(db: Session, account: Account, now: datetime) -> Any:
    body = CalculateInput.model_validate(ger30_body(account), strict=False)
    return calculator.size(db, body, now=now).context.conversion


def test_stale_flag_uses_the_injected_clock(db_session: Session, account: Account) -> None:
    make_ger30(db_session, account)
    make_fx_rate(db_session, account, rate_at=FIXED_NOW - timedelta(hours=1))

    assert sized_conversion(db_session, account, FIXED_NOW).stale is False  # exactly 1 h
    later = FIXED_NOW + timedelta(seconds=1)
    assert sized_conversion(db_session, account, later).stale is True


@pytest.mark.parametrize("bad", [D("0"), D("-10")])
def test_cross_currency_spec_without_a_positive_contract_size_is_specs_incomplete(
    client: TestClient, db_session: Session, account: Account, bad: Decimal
) -> None:
    make_ger30(db_session, account, contract_size=bad)
    make_fx_rate(db_session, account)

    response = calculate(client, ger30_body(account))

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "specs_incomplete"
    assert error["details"]["missing"] == ["contract_size"]


def test_same_currency_spec_does_not_need_a_contract_size(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "EURUSD", contract_size=D("0"))

    assert calculate(client, eurusd_body(account)).status_code == 200
