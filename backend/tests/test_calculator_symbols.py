"""Calculator with canonical symbols (docs/api.md "M5-08 Canonical symbols").

`symbol` in calculate / margin-requests bodies is the canonical name; the spec is found by
(account, canonical_symbol). Specs list: items carry `broker_symbol`, `missing` lists
symbols.yaml names without a spec row, items in symbols.yaml order then others by name.
All specs are SYNTHETIC (GER40-like values under the broker name GER30).
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.models import Account
from app.models.account import SymbolSpec
from app.models.calculator import CalculatorMarginRequest
from tests.symbols_fixture import TEST_NAMES, use_test_config
from tests.test_calculator_api import (
    error_of,
    ger40_body,
    make_account,
    make_ger40,
    make_margin_request,
    make_spec,
)
from tests.test_margin_job import add_account as add_mt5_account
from tests.test_margin_job import add_request, fixture_source, load, run

D = Decimal
GER30_MARGINS = {"GER30": {"buy": "4800.00", "sell": "4799.50"}}


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture(autouse=True)
def _symbols_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Fixed test symbols.yaml (tests/symbols_fixture.py), not the editable real file."""
    yield use_test_config(tmp_path, monkeypatch)
    reload_config()


@pytest.fixture
def account(db_session: Session) -> Account:
    return make_account(db_session)


def make_ger30(db: Session, account: Account) -> SymbolSpec:
    """The FundedNext DAX: broker name GER30, canonical GER40 (as sync/re-apply store it)."""
    spec = make_ger40(db, account, "GER30")
    spec.canonical_symbol = "GER40"
    db.commit()
    return spec


def specs(client: TestClient, account: Account) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account.id}/symbol-specs")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- GET /api/accounts/{id}/symbol-specs ---


def test_specs_list_has_broker_symbol_and_symbols_yaml_order(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "AUDUSD")
    make_ger30(db_session, account)
    make_spec(db_session, account, "EURUSD")
    make_spec(db_session, account, "CADJPY")

    body = specs(client, account)

    assert set(body) == {"items", "missing"}
    items = body["items"]
    assert [(i["symbol"], i["broker_symbol"]) for i in items] == [
        ("EURUSD", "EURUSD"),
        ("GER40", "GER30"),
        ("AUDUSD", "AUDUSD"),
        ("CADJPY", "CADJPY"),
    ]
    assert body["missing"] == ["GBPUSD", "XAUUSD"]


def test_account_without_a_dax_symbol_lists_ger40_as_missing(
    client: TestClient, db_session: Session, account: Account
) -> None:
    for symbol in ("EURUSD", "GBPUSD", "XAUUSD"):
        make_spec(db_session, account, symbol)

    assert specs(client, account)["missing"] == ["GER40"]


def test_never_synced_account_has_no_missing_symbols(client: TestClient, account: Account) -> None:
    """No spec rows at all = not synced yet: the UI shows its sync hint, not four
    "symbol not found at the broker" options (review M5-08)."""
    assert specs(client, account) == {"items": [], "missing": []}


def test_one_synced_symbol_lists_every_other_configured_name_as_missing(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_spec(db_session, account, "XAUUSD")

    assert specs(client, account)["missing"] == [n for n in TEST_NAMES if n != "XAUUSD"]


def test_missing_is_per_account(client: TestClient, db_session: Session, account: Account) -> None:
    make_spec(db_session, account, "EURUSD")
    other = make_account(db_session)
    make_ger30(db_session, other)

    assert "GER40" in specs(client, account)["missing"]
    assert "GER40" not in specs(client, other)["missing"]


def test_stale_spec_row_is_listed_not_missing(
    client: TestClient, db_session: Session, account: Account
) -> None:
    """A spec with null point is an item (UI: «потрібна синхронізація»), never `missing`."""
    spec = make_ger30(db_session, account)
    spec.point = None
    spec.tick_value_loss = None
    db_session.commit()

    body = specs(client, account)

    (item,) = [i for i in body["items"] if i["symbol"] == "GER40"]
    assert (item["point"], item["tick_value_loss"], item["broker_symbol"]) == (None, None, "GER30")
    assert "GER40" not in body["missing"]


# --- calculate ---


def test_calculate_canonical_ger40_uses_the_ger30_spec(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)

    response = client.post("/api/calculator/calculate", json=ger40_body(account, symbol="GER40"))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["symbol"] == "GER40"
    assert D(data["volume"]) == D("0.66")  # same synthetic GER40-like spec as the M5-04c tests
    assert D(data["sl_points"]) == D("300")


@pytest.mark.parametrize("symbol", ["GER30", "ger40", "GER4", "GER40.cash"])
def test_calculate_accepts_only_the_exact_canonical_name(
    client: TestClient, db_session: Session, account: Account, symbol: str
) -> None:
    """Canonical only: the broker name, another case or a prefix is 404 not_found."""
    make_ger30(db_session, account)

    response = client.post("/api/calculator/calculate", json=ger40_body(account, symbol=symbol))

    error = error_of(response, 404, "not_found")
    assert error["details"]["symbol"] == symbol


def test_cached_estimate_is_keyed_by_the_canonical_symbol(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_margin_request(db_session, account, symbol="GER40", broker_symbol="GER30")

    margin = client.post(
        "/api/calculator/calculate", json=ger40_body(account, symbol="GER40")
    ).json()["margin"]

    assert margin["source"] == "cached_estimate"
    assert D(margin["amount"]) == D("13200")  # 2000 * 0.66 / 0.10


def test_cached_estimate_ignores_a_request_stored_under_another_canonical_name(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    make_margin_request(db_session, account, symbol="GER30", broker_symbol="GER30")

    margin = client.post(
        "/api/calculator/calculate", json=ger40_body(account, symbol="GER40")
    ).json()["margin"]

    assert margin["source"] == "unavailable"


# --- margin requests ---


def test_margin_request_stores_canonical_and_broker_symbol(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)

    response = client.post(
        "/api/calculator/margin-requests", json=ger40_body(account, symbol="GER40")
    )

    assert response.status_code == 202, response.text
    item = response.json()
    assert item["symbol"] == "GER40"
    db_session.expire_all()
    row = db_session.get(CalculatorMarginRequest, item["id"])
    assert row is not None
    assert (row.symbol, row.broker_symbol) == ("GER40", "GER30")


def test_margin_request_with_the_broker_name_is_404(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)

    response = client.post(
        "/api/calculator/margin-requests", json=ger40_body(account, symbol="GER30")
    )

    error_of(response, 404, "not_found")
    assert db_session.scalars(select(CalculatorMarginRequest)).all() == []


def test_identical_canonical_request_is_deduplicated(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)
    body = ger40_body(account, symbol="GER40")

    first = client.post("/api/calculator/margin-requests", json=body).json()
    second = client.post("/api/calculator/margin-requests", json=body).json()

    assert first["id"] == second["id"]


# --- worker: MT5 is called with the broker name ---


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


def test_margin_worker_calls_mt5_with_the_broker_symbol(
    factory: sessionmaker[Session], db_session: Session
) -> None:
    account = add_mt5_account(db_session)
    request_id = add_request(db_session, account, symbol="GER40", broker_symbol="GER30")
    src = fixture_source(margins=GER30_MARGINS)

    assert run(factory, src, threading.Lock()) == request_id

    assert [args[1] for args in src.margin_args] == ["GER30"]
    row = load(db_session, request_id)
    assert row.status == "done", row.error_code
    assert row.margin == D("2400.00")  # 4800.00 per lot * 0.50
    assert (row.symbol, row.broker_symbol) == ("GER40", "GER30")


# --- two broker rows with one canonical name: the resolver's pick, deterministically ---


def _dax_rows(db: Session, account: Account) -> None:
    """GER40.cash (tick value 5.0) and GER30 (2.5), both canonical GER40."""
    cash = make_ger40(db, account, "GER40.cash")
    cash.tick_value = D("5")
    cash.tick_value_loss = D("5")
    cash.canonical_symbol = "GER40"
    make_ger30(db, account)
    db.commit()


@pytest.mark.parametrize(
    ("firm", "broker", "volume"),
    [
        ("FundedNext", "GER30", "0.66"),  # firm override: only GER30
        ("Other firm", "GER30", "0.66"),  # GER40, GER30, GER40.cash, DE40: GER30 is exact first
    ],
)
def test_two_rows_one_canonical_follow_the_resolver(
    client: TestClient, db_session: Session, firm: str, broker: str, volume: str
) -> None:
    account = make_account(db_session, firm=firm)
    _dax_rows(db_session, account)

    items = specs(client, account)["items"]
    data = client.post("/api/calculator/calculate", json=ger40_body(account, symbol="GER40")).json()
    queued = client.post(
        "/api/calculator/margin-requests", json=ger40_body(account, symbol="GER40")
    ).json()

    assert [(i["symbol"], i["broker_symbol"]) for i in items] == [("GER40", broker)]
    assert D(data["volume"]) == D(volume)
    db_session.expire_all()
    row = db_session.get(CalculatorMarginRequest, queued["id"])
    assert row is not None
    assert row.broker_symbol == broker


def test_without_an_exact_candidate_the_first_candidate_prefix_wins(
    client: TestClient, db_session: Session
) -> None:
    """Rows DE40 and GER40.cash (no GER30): GER40.cash comes before DE40 in the candidates."""
    account = make_account(db_session, firm="Other firm")
    cash = make_ger40(db_session, account, "GER40.cash")
    cash.canonical_symbol = "GER40"
    de40 = make_ger40(db_session, account, "DE40")
    de40.tick_value_loss = D("5")
    de40.canonical_symbol = "GER40"
    db_session.commit()

    for _ in range(3):  # stable across calls
        items = specs(client, account)["items"]
        assert [(i["symbol"], i["broker_symbol"]) for i in items] == [("GER40", "GER40.cash")]
    data = client.post("/api/calculator/calculate", json=ger40_body(account, symbol="GER40")).json()
    assert D(data["volume"]) == D("0.66")  # the GER40.cash spec (2.5 per tick)


# --- a broken symbols.yaml is visible, like a broken rules.yaml ---


@pytest.fixture
def broken_symbols(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", target)
    (target / "symbols.yaml").write_text("symbols: [\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(target))
    reload_config()
    yield target
    reload_config()


@pytest.mark.usefixtures("broken_symbols")
def test_specs_list_with_broken_symbols_yaml_is_500_config_error(
    client: TestClient, account: Account
) -> None:
    response = client.get(f"/api/accounts/{account.id}/symbol-specs")

    error = error_of(response, 500, "config_error")
    assert error["details"]["file"] == "symbols.yaml"
    assert error["details"]["problems"]


@pytest.mark.usefixtures("broken_symbols")
def test_calculate_with_broken_symbols_yaml_is_500_config_error(
    client: TestClient, db_session: Session, account: Account
) -> None:
    make_ger30(db_session, account)

    response = client.post("/api/calculator/calculate", json=ger40_body(account, symbol="GER40"))

    assert error_of(response, 500, "config_error")["details"]["file"] == "symbols.yaml"
