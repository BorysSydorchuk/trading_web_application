"""M8-14: GET /api/dashboard/charts (Home charts)."""

# ruff: noqa: F811  (pytest fixtures imported from test_trade_exclusion)
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Account, Trade
from tests.test_trade_exclusion import (  # noqa: F401 (fixtures)
    TODAY,
    WED,
    _clean,
    _now,
    account,
    closed,
    digest,
    exclude,
    ok,
    session,
    week,
)
from tests.test_trades_api import add_account

WEEK_FROM, WEEK_TO = "2026-11-09", "2026-11-15"


def charts(client: TestClient, **params: Any) -> dict[str, Any]:
    query = {"from": WEEK_FROM, "to": WEEK_TO} | params
    return ok(client.get("/api/dashboard/charts", params=query))


def test_equity_and_daily_pnl_match_the_digest_account_pnl(
    client: TestClient, week: dict[str, Trade]
) -> None:
    ok(exclude(client, week["test"].id))  # excluded: still real money

    data = charts(client)
    metrics = digest(client)

    assert data["equity"][-1]["cum_pnl"] == metrics["excluded"]["account_net_pnl"] == "50.00"
    assert data["equity"][0]["cum_pnl"] == "0.00"
    assert [(d["day"], d["net_pnl"], d["trades"]) for d in data["daily"]] == [
        ("2026-11-11", "-50.00", 1),
        ("2026-11-12", "100.00", 2),
    ]
    assert data["account_size"] == "10000.00"
    assert data["equity"][-1]["cum_pct"] == "0.5000"
    assert (data["currency"], data["trades"], data["rolling_window"]) == ("USD", 3, 20)


def test_rolling_skips_excluded_trades(client: TestClient, week: dict[str, Trade]) -> None:
    ok(exclude(client, week["test"].id))

    rolling = charts(client)["rolling"]

    assert [p["n"] for p in rolling] == [1, 2]  # the two strategy trades only
    assert rolling[-1]["win_rate"] == "50.0000"
    assert rolling[-1]["avg_r"] == "0.5000"


def test_the_rolling_window_reaches_back_before_the_range(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade]
) -> None:
    closed(session, account, WED - timedelta(days=10), "300.00", "3.0")  # outside the range

    rolling = charts(client)["rolling"]

    assert [p["n"] for p in rolling] == [2, 3, 4]  # the older trade is in every window
    assert len(charts(client)["daily"]) == 2


def test_one_account_and_percent_of_its_size(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade]
) -> None:
    other = add_account(session, "Beta", 2, reference_balance="5000.00")
    closed(session, other, TODAY, "-25.00", "-0.25")

    every = charts(client)
    beta = charts(client, account_id=other.id)

    assert every["account_size"] == "15000.00"  # both accounts traded in the range
    assert beta["account_size"] == "5000.00"
    assert beta["equity"][-1]["cum_pnl"] == "-25.00"
    assert beta["equity"][-1]["cum_pct"] == "-0.5000"


def test_empty_range_and_errors(client: TestClient, account: Account) -> None:
    empty = charts(client)
    assert (empty["trades"], empty["daily"], empty["rolling"]) == (0, [], [])
    assert empty["equity"] == [{"time": "2026-11-08T23:00:00Z", "cum_pnl": "0.00", "cum_pct": None}]

    bad = client.get("/api/dashboard/charts", params={"from": WEEK_TO, "to": WEEK_FROM})
    assert bad.status_code == 422
    missing = client.get(
        "/api/dashboard/charts", params={"from": WEEK_FROM, "to": WEEK_TO, "account_id": 999}
    )
    assert missing.status_code == 404


def test_archived_accounts_are_left_out(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade]
) -> None:
    account.status = "archived"
    session.commit()

    assert charts(client)["trades"] == 0
