"""cTrader phase c4: the calculator works unchanged on the specs of a cTrader account.

The specs go through the c1 mapping and writer, then `POST /api/calculator/calculate` must give
the same sizing as for an MT5 account with identical specs. Live margin stays refused.
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

from app.config_files import get_symbols_config, reload_config
from app.ctrader.specs import spec_from_symbol
from app.models import Account, FxRate
from app.services.ctrader_specs import write_ctrader_specs
from tests.ctrader_fakes import make_ctrader_account
from tests.ctrader_history_fakes import load
from tests.symbols_fixture import use_test_config
from tests.test_calculator_api import calculate, eurusd_body, make_account, make_spec, ok

D = Decimal
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
SAME_KEYS = (
    "symbol",
    "entry",
    "sl_price",
    "sl_distance",
    "sl_points",
    "balance",
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
    "margin",
    "loss_per_tick",
    "conversion",
)


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


def write_from_fixture(db: Session, account: Account, symbol_id: int) -> None:
    """The fixture symbol through the c1 mapping and writer (as the worker does it)."""
    data = load("symbols.json")
    assets = {int(a["assetId"]): a["name"] for a in load("assets.json")["asset"]}
    light = next(s for s in data["list"]["symbol"] if s["symbolId"] == symbol_id)
    full = next(s for s in data["byId"]["symbol"] if s["symbolId"] == symbol_id)
    spec = spec_from_symbol(light, full, assets)
    assert spec is not None
    write_ctrader_specs(db, account, {spec.name: spec}, get_symbols_config(), NOW)
    db.commit()


def make_rate(db: Session, account: Account) -> None:
    at = datetime.now(UTC) - timedelta(minutes=5)
    db.add(
        FxRate(
            account_id=account.id,
            from_currency="EUR",
            to_currency="USD",
            pair="EURUSD",
            inverted=False,
            bid=D("1.08034"),
            ask=D("1.08044"),
            rate=D("1.08044"),
            rate_at=at,
            synced_at=at,
        )
    )
    db.commit()


def same(left: dict[str, Any], right: dict[str, Any]) -> None:
    assert {k: left[k] for k in SAME_KEYS} == {k: right[k] for k in SAME_KEYS}


def test_same_currency_lot_equals_the_mt5_lot(client: TestClient, db_session: Session) -> None:
    ct = make_ctrader_account(db_session, reference_balance=D("10000.00"))
    mt5 = make_account(db_session, reference_balance=D("10000.00"))
    write_from_fixture(db_session, ct, 1)
    make_spec(
        db_session,
        mt5,
        "EURUSD",
        currency_margin="EUR",
        canonical_symbol="EURUSD",
        volume_max=D("1000"),
    )
    # 170 ticks to the SL x 1.00 USD: 1 % of 10000 = 100 -> 0.588 lot, rounded DOWN to 0.58
    changes = {"sl_price": "1.09830"}

    from_ct = ok(client, eurusd_body(ct, **changes))
    from_mt5 = ok(client, eurusd_body(mt5, **changes))

    assert D(from_ct["volume"]) == D("0.58")
    assert D(from_ct["loss_per_tick"]) == D("1")
    assert from_ct["conversion"] is None
    same(from_ct, from_mt5)


def test_cross_currency_lot_uses_the_fx_rate_like_mt5(
    client: TestClient, db_session: Session
) -> None:
    ct = make_ctrader_account(db_session, reference_balance=D("10000.00"))
    mt5 = make_account(db_session, reference_balance=D("10000.00"))
    write_from_fixture(db_session, ct, 2)  # DE40 = GER40, profit currency EUR, account USD
    make_spec(
        db_session,
        mt5,
        "DE40",
        canonical_symbol="GER40",
        contract_size=D("1"),
        tick_size=D("0.1"),
        tick_value=D("0.1"),
        tick_value_loss=D("0.1"),
        point=D("0.1"),
        digits=1,
        volume_min=D("0.1"),
        volume_step=D("0.1"),
        volume_max=D("1000"),
        currency_profit="EUR",
        currency_margin="DE40",
    )
    make_rate(db_session, ct)
    make_rate(db_session, mt5)
    body = {"symbol": "GER40", "direction": "buy", "entry": "19500", "sl_price": "19480"}

    from_ct = ok(client, {"account_id": ct.id} | body)
    from_mt5 = ok(client, {"account_id": mt5.id} | body)

    # 200 ticks x 0.1 x 1 x 1.08044 = 21.6088 per lot; 100 / 21.6088 = 4.63 -> 4.6 lot
    assert D(from_ct["loss_per_tick"]) == D("0.108044")
    assert D(from_ct["volume"]) == D("4.6")
    assert from_ct["conversion"]["source"] == "rate"
    same(from_ct, from_mt5)


def test_cross_currency_without_a_rate_is_409_for_ctrader_too(
    client: TestClient, db_session: Session
) -> None:
    ct = make_ctrader_account(db_session, reference_balance=D("10000.00"))
    write_from_fixture(db_session, ct, 2)
    response = calculate(
        client,
        {
            "account_id": ct.id,
            "symbol": "GER40",
            "direction": "buy",
            "entry": "19500",
            "sl_price": "19480",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversion_rate_unavailable"


def test_symbol_specs_of_a_ctrader_account_list_canonical_and_broker_names(
    client: TestClient, db_session: Session
) -> None:
    ct = make_ctrader_account(db_session)
    write_from_fixture(db_session, ct, 1)
    write_from_fixture(db_session, ct, 2)

    items = client.get(f"/api/accounts/{ct.id}/symbol-specs").json()["items"]

    assert [(i["symbol"], i["broker_symbol"]) for i in items] == [
        ("EURUSD", "EURUSD"),
        ("GER40", "DE40"),
    ]


def test_live_margin_request_for_ctrader_stays_409(client: TestClient, db_session: Session) -> None:
    ct = make_ctrader_account(db_session, reference_balance=D("10000.00"))
    write_from_fixture(db_session, ct, 1)
    response = client.post(
        "/api/calculator/margin-requests",
        json={
            "account_id": ct.id,
            "symbol": "EURUSD",
            "direction": "buy",
            "entry": "1.1",
            "sl_points": "10",
            "risk_percent": "1",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "margin_unsupported_platform"
