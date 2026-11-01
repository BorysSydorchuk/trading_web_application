"""Trades read API, PATCH initial_sl, inbox counts, symbols (docs/api.md M1 "Trades")."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from app.db import make_session_factory
from app.models import Account, RuleViolation, SymbolSpec, Trade, TradeExitDeal
from app.models.enums import AccountPhase, AccountStatus, TradeStatus

# Wed 2026-11-04; Brussels is UTC+1.
T0 = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)


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


def add_account(session: Session, name: str, login: int, **kw: Any) -> Account:
    account = Account(
        name=name,
        firm="FundedNext",
        program="Stellar 2-Step",
        phase=AccountPhase.PHASE_1.value,
        login=login,
        server="FundedNext-Server",
        starting_balance=Decimal("100000.00"),
        currency="USD",
        **kw,
    )
    session.add(account)
    session.commit()
    return account


_position = iter(range(1000, 100000))


def add_trade(session: Session, account: Account, **kw: Any) -> Trade:
    fields: dict[str, Any] = {
        "account_id": account.id,
        "position_id": next(_position),
        "symbol": "XAUUSD",
        "direction": "buy",
        "status": TradeStatus.NEEDS_DESCRIPTION.value,
        "open_time": T0,
        "close_time": T0 + timedelta(minutes=30),
        "duration_seconds": 1800,
        "entry_price": Decimal("2650.00"),
        "exit_price": Decimal("2660.00"),
        "volume": Decimal("0.50"),
        "tp": Decimal("2670.00"),
        "commission": Decimal("-3.50"),
        "gross_pnl": Decimal("500.00"),
        "net_pnl": Decimal("496.50"),
        "balance_at_open": Decimal("100000.00"),
    }
    trade = Trade(**(fields | kw))
    session.add(trade)
    session.commit()
    return trade


def add_exit(session: Session, trade: Trade, ticket: int, **kw: Any) -> None:
    fields: dict[str, Any] = {
        "trade_id": trade.id,
        "account_id": trade.account_id,
        "ticket": ticket,
        "time": trade.close_time,
        "price": trade.exit_price,
        "volume": trade.volume,
        "profit": trade.gross_pnl,
        "commission": Decimal("-1.75"),
        "reason": "tp",
    }
    session.add(TradeExitDeal(**(fields | kw)))
    session.commit()


def add_violation(session: Session, trade: Trade, key: str, source: str = "auto") -> None:
    session.add(RuleViolation(trade_id=trade.id, rule_key=key, source=source, details="x"))
    session.commit()


@dataclass
class Seed:
    a: Account
    b: Account
    archived: Account
    trades: dict[str, Trade]


@pytest.fixture
def seed(session: Session) -> Seed:
    a = add_account(session, "Alpha", 1)
    b = add_account(session, "Beta", 2)
    archived = add_account(session, "Old", 3, status=AccountStatus.ARCHIVED.value)
    t: dict[str, Trade] = {}
    t["needs_sl"] = add_trade(
        session, a, status="needs_sl", symbol="GER40", close_time=T0 + timedelta(hours=1)
    )
    t["described"] = add_trade(
        session,
        a,
        net_pnl=Decimal("-120.00"),
        r_multiple=Decimal("-0.5000"),
        close_time=T0 + timedelta(hours=2),
    )
    t["draft"] = add_trade(
        session, b, status="draft", net_pnl=Decimal("50.00"), close_time=T0 + timedelta(hours=3)
    )
    t["open"] = add_trade(
        session,
        b,
        status="open",
        open_time=T0 + timedelta(hours=4),
        close_time=None,
        exit_price=None,
        gross_pnl=None,
        net_pnl=None,
        duration_seconds=None,
    )
    t["old_day"] = add_trade(
        session,
        a,
        open_time=T0 - timedelta(days=2),
        close_time=T0 - timedelta(days=2) + timedelta(minutes=5),
        net_pnl=Decimal("10.00"),
    )
    t["archived"] = add_trade(session, archived, status="needs_sl", symbol="EURUSD")
    add_violation(session, t["described"], "min_planned_rr")
    add_violation(session, t["described"], "max_risk_pct", "user")
    add_violation(session, t["draft"], "entry_session")
    return Seed(a, b, archived, t)


def ids(response: Any) -> list[int]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def fields_of(response: Any) -> dict[str, str]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields: dict[str, str] = error["details"]["fields"]
    return fields


# --- list ---


def test_list_default_sort_close_time_desc_open_last(client: TestClient, seed: Seed) -> None:
    t = seed.trades
    response = client.get("/api/trades")
    assert ids(response) == [
        t["draft"].id,  # T0+3h
        t["described"].id,  # T0+2h
        t["needs_sl"].id,  # T0+1h
        t["archived"].id,  # T0+30m (archived accounts' trades stay in the list)
        t["old_day"].id,  # 2 days earlier
        t["open"].id,  # no close_time: nulls last
    ]
    assert response.json()["total"] == 6


def test_row_shape(client: TestClient, seed: Seed) -> None:
    items = client.get("/api/trades").json()["items"]
    row = next(i for i in items if i["id"] == seed.trades["described"].id)
    assert row["account_name"] == "Alpha"
    assert row["entry_price"] == "2650.00000000"
    assert row["volume"] == "0.50000000"
    assert row["net_pnl"] == "-120.00"
    assert row["r_multiple"] == "-0.5000"
    assert row["open_time"] == "2026-11-04T08:00:00Z"
    assert row["close_time"] == "2026-11-04T10:00:00Z"
    assert row["violations"] == ["max_risk_pct", "min_planned_rr"]
    assert row["is_reentry"] is False
    assert "exit_deals" not in row
    open_row = next(i for i in items if i["id"] == seed.trades["open"].id)
    assert open_row["close_time"] is None
    assert open_row["violations"] == []


def test_filter_account_repeatable(client: TestClient, seed: Seed) -> None:
    only_b = ids(client.get("/api/trades", params={"account_id": seed.b.id}))
    assert set(only_b) == {seed.trades["draft"].id, seed.trades["open"].id}
    both = client.get("/api/trades", params=[("account_id", seed.a.id), ("account_id", seed.b.id)])
    assert both.json()["total"] == 5


def test_filter_symbol_and_status(client: TestClient, seed: Seed) -> None:
    assert ids(client.get("/api/trades", params={"symbol": "GER40"})) == [
        seed.trades["needs_sl"].id
    ]
    response = client.get("/api/trades", params=[("status", "needs_sl"), ("status", "draft")])
    assert set(ids(response)) == {
        seed.trades["needs_sl"].id,
        seed.trades["draft"].id,
        seed.trades["archived"].id,
    }


def test_filter_dates_brussels_days(client: TestClient, seed: Seed) -> None:
    t = seed.trades
    # 2026-11-04 Brussels = 2026-11-03T23:00Z .. 2026-11-04T23:00Z; open trade by open_time.
    day = ids(client.get("/api/trades", params={"from": "2026-11-04", "to": "2026-11-04"}))
    assert set(day) == {
        t["needs_sl"].id,
        t["described"].id,
        t["draft"].id,
        t["open"].id,
        t["archived"].id,
    }
    old = ids(client.get("/api/trades", params={"to": "2026-11-02"}))
    assert old == [t["old_day"].id]


def test_filter_datetimes(client: TestClient, seed: Seed) -> None:
    t = seed.trades
    response = client.get(
        "/api/trades", params={"from": "2026-11-04T09:00:00Z", "to": "2026-11-04T10:00:00Z"}
    )
    # closes at 09:00 and 10:00 are inclusive on both ends
    assert set(ids(response)) == {t["needs_sl"].id, t["described"].id}
    naive = client.get("/api/trades", params={"from": "2026-11-04T11:00:00"})
    assert set(ids(naive)) == {t["draft"].id, t["open"].id}


def test_sort_and_order(client: TestClient, seed: Seed) -> None:
    t = seed.trades
    response = client.get("/api/trades", params={"sort": "net_pnl", "order": "asc"})
    assert ids(response) == [
        t["described"].id,  # -120
        t["old_day"].id,  # 10
        t["draft"].id,  # 50
        t["needs_sl"].id,  # 496.50 (lower id first on ties)
        t["archived"].id,  # 496.50
        t["open"].id,  # null last
    ]


def test_pagination(client: TestClient, seed: Seed) -> None:
    first = client.get("/api/trades", params={"limit": 2})
    second = client.get("/api/trades", params={"limit": 2, "offset": 2})
    assert first.json()["total"] == second.json()["total"] == 6
    assert len(ids(first)) == 2
    assert set(ids(first)).isdisjoint(ids(second))


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"sort": "account_name"}, "sort"),
        ({"sort": "id; drop table trades"}, "sort"),
        ({"order": "up"}, "order"),
        ({"limit": 0}, "limit"),
        ({"limit": 501}, "limit"),
        ({"offset": -1}, "offset"),
        ({"status": "deleted"}, "status.0"),
        ({"account_id": "x"}, "account_id.0"),
        ({"from": "yesterday"}, "from"),
        ({"to": "2026-13-01"}, "to"),
    ],
)
def test_list_validation(client: TestClient, params: dict[str, Any], field: str) -> None:
    assert field in fields_of(client.get("/api/trades", params=params))


def test_list_runs_two_queries_plus_count(
    client: TestClient, seed: Seed, db_engine: Engine
) -> None:
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(str(args[2]))

    event.listen(db_engine, "before_cursor_execute", count)
    try:
        assert client.get("/api/trades").status_code == 200
    finally:
        event.remove(db_engine, "before_cursor_execute", count)
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 3  # count, page, violations: no N+1


# --- symbols, inbox ---


def test_symbols_distinct_sorted(client: TestClient, seed: Seed) -> None:
    assert client.get("/api/trades/symbols").json() == {"items": ["EURUSD", "GER40", "XAUUSD"]}


def test_inbox_counts_skip_archived_accounts(client: TestClient, seed: Seed) -> None:
    assert client.get("/api/inbox/counts").json() == {
        "needs_sl": 1,
        "needs_description": 2,
        "draft": 1,
    }


def test_inbox_counts_empty(client: TestClient) -> None:
    assert client.get("/api/inbox/counts").json() == {
        "needs_sl": 0,
        "needs_description": 0,
        "draft": 0,
    }


# --- detail ---


def test_detail(client: TestClient, session: Session, seed: Seed) -> None:
    trade = seed.trades["described"]
    add_exit(session, trade, 9002, time=T0 + timedelta(hours=2), volume=Decimal("0.20"))
    add_exit(session, trade, 9001, time=T0 + timedelta(hours=1), volume=Decimal("0.30"))
    data = client.get(f"/api/trades/{trade.id}").json()
    assert data["id"] == trade.id
    assert data["account_name"] == "Alpha"
    assert data["initial_sl_source"] is None
    assert [d["ticket"] for d in data["exit_deals"]] == [9001, 9002]  # by time
    assert data["exit_deals"][0] == {
        "ticket": 9001,
        "time": "2026-11-04T09:00:00Z",
        "price": "2660.00000000",
        "volume": "0.30000000",
        "profit": "500.00",
        "commission": "-1.75",
        "swap": "0.00",
        "reason": "tp",
    }
    assert data["rule_violations"] == [
        {"rule_key": "max_risk_pct", "source": "user", "details": "x"},
        {"rule_key": "min_planned_rr", "source": "auto", "details": "x"},
    ]
    assert data["violations"] == ["max_risk_pct", "min_planned_rr"]
    for key in ("setup_context", "entry_model", "followed_plan", "quality_rating", "lesson"):
        assert data[key] is None
    assert data["ai_filled_fields"] == []
    assert data["extra"] == {}
    assert data["described_at"] is None


def test_detail_404(client: TestClient) -> None:
    response = client.get("/api/trades/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- PATCH initial_sl ---


def test_patch_sets_sl_and_recomputes(client: TestClient, session: Session, seed: Seed) -> None:
    trade = seed.trades["needs_sl"]
    add_exit(session, trade, 7001)
    response = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "2645.00"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["initial_sl"] == "2645.00000000"
    assert data["initial_sl_source"] == "user"
    assert data["status"] == "needs_description"
    # realised conversion: 500 * 5 / 10
    assert data["risk_amount"] == "250.00"
    assert data["risk_pct"] == "0.2500"
    assert data["r_multiple"] == "1.9860"  # 496.50 / 250
    assert data["planned_rr"] == "4.0000"  # 20 / 5
    assert len(data["exit_deals"]) == 1
    assert client.get("/api/inbox/counts").json()["needs_sl"] == 0


def test_patch_breakeven_uses_symbol_spec(client: TestClient, session: Session, seed: Seed) -> None:
    trade = add_trade(
        session,
        seed.a,
        status="needs_sl",
        exit_price=Decimal("2650.00"),
        gross_pnl=Decimal("0.00"),
        net_pnl=Decimal("-3.50"),
        tp=None,
    )
    session.add(
        SymbolSpec(
            account_id=seed.a.id,
            symbol="XAUUSD",
            contract_size=Decimal(100),
            tick_size=Decimal("0.01"),
            tick_value=Decimal("1.00"),
            volume_min=Decimal("0.01"),
            volume_step=Decimal("0.01"),
            volume_max=Decimal(100),
            digits=2,
            currency_profit="USD",
            currency_margin="USD",
            synced_at=T0,
        )
    )
    session.commit()
    data = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "2645"}).json()
    assert data["risk_amount"] == "250.00"  # 5 / 0.01 * 1.00 * 0.5
    assert data["r_multiple"] == "-0.0140"
    assert data["planned_rr"] is None  # no TP


def test_patch_without_spec_or_move_leaves_risk_null(
    client: TestClient, session: Session, seed: Seed
) -> None:
    trade = add_trade(
        session, seed.a, status="needs_sl", exit_price=Decimal("2650.00"), gross_pnl=Decimal(0)
    )
    data = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "2645"}).json()
    assert data["status"] == "needs_description"
    assert data["risk_amount"] is None
    assert data["r_multiple"] is None


def test_patch_correction_keeps_draft_and_violations(client: TestClient, seed: Seed) -> None:
    trade = seed.trades["draft"]
    data = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "2640.00"}).json()
    assert data["status"] == "draft"
    assert data["risk_amount"] == "500.00"
    assert data["violations"] == ["entry_session"]  # rules engine not run here


def test_patch_sell_side(client: TestClient, session: Session, seed: Seed) -> None:
    trade = add_trade(
        session, seed.a, status="needs_sl", direction="sell", exit_price=Decimal("2640.00")
    )
    response = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "2655.00"})
    assert response.status_code == 200, response.text
    assert response.json()["risk_amount"] == "250.00"


def test_patch_open_trade_is_409(client: TestClient, seed: Seed) -> None:
    response = client.patch(f"/api/trades/{seed.trades['open'].id}", json={"initial_sl": "2600"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "trade_open"


def test_patch_404(client: TestClient) -> None:
    assert client.patch("/api/trades/999999", json={"initial_sl": "1"}).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"initial_sl": None},
        {"initial_sl": "0"},
        {"initial_sl": "-1"},
        {"initial_sl": 2645.5},
        {"initial_sl": "abc"},
        {"initial_sl": "2645.123456789"},
        {"initial_sl": "2650.00"},  # equals entry
        {"initial_sl": "2655.00"},  # above entry for a buy
        {"initial_sl": "2645", "setup_context": "yes"},
    ],
)
def test_patch_validation(client: TestClient, seed: Seed, body: dict[str, Any]) -> None:
    trade = seed.trades["needs_sl"]
    fields = fields_of(client.patch(f"/api/trades/{trade.id}", json=body))
    assert set(fields) & {"initial_sl", "setup_context"}
    assert client.get(f"/api/trades/{trade.id}").json()["status"] == "needs_sl"
