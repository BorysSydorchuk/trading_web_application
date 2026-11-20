"""M8-14: GET /api/dashboard/charts (Home charts)."""

# ruff: noqa: F811  (pytest fixtures imported from test_trade_exclusion)
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
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


# --- review fixes ----------------------------------------------------------------------------


def test_all_accounts_in_two_currencies_are_refused_like_the_digest(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade]
) -> None:
    euro = add_account(session, "Euro", 3)
    euro.currency = "EUR"
    session.commit()
    closed(session, euro, TODAY, "10.00", "0.1")

    response = client.get("/api/dashboard/charts", params={"from": WEEK_FROM, "to": WEEK_TO})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mixed_currency"
    assert charts(client, account_id=euro.id)["currency"] == "EUR"  # one account works


@pytest.mark.parametrize("size", ["0", "NaN"])
def test_a_traded_account_without_a_usable_size_gives_no_percent(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade], size: str
) -> None:
    other = add_account(session, "Beta", 2, reference_balance=Decimal(size))
    closed(session, other, TODAY, "-25.00", "-0.25")

    data = charts(client)

    assert data["account_size"] is None
    assert data["equity"][-1]["cum_pct"] is None
    assert data["equity"][-1]["cum_pnl"] == "25.00"


@pytest.mark.parametrize(("start", "end"), [("0001-01-01", WEEK_TO), (WEEK_FROM, "9999-12-31")])
def test_dates_outside_the_supported_window_are_422(
    client: TestClient, account: Account, start: str, end: str
) -> None:
    response = client.get("/api/dashboard/charts", params={"from": start, "to": end})
    assert response.status_code == 422


def test_a_range_across_the_dst_change_uses_brussels_midnights(
    client: TestClient, session: Session, account: Account
) -> None:
    # Brussels leaves summer time on Sun 2026-10-25 (03:00 -> 02:00).
    closed(session, account, datetime(2026, 10, 25, 22, 30, tzinfo=UTC), "10.00", "0.1")
    closed(session, account, datetime(2026, 10, 25, 23, 30, tzinfo=UTC), "20.00", "0.2")  # 26.10

    data = charts(client, **{"from": "2026-10-25", "to": "2026-10-25"})

    assert data["trades"] == 1  # 25.10 22:30 UTC = 23:30 Brussels (winter time)
    assert data["equity"][0]["time"] == "2026-10-24T22:00:00Z"  # 00:00 summer time


# --- M8-10b fixes: one period P&L / % definition (PM 2026-11-20) -----------------------------


def monthly_digest(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/digests", json={"kind": "monthly", "date": "2026-11-01"})
    assert response.status_code in (200, 201), response.text
    metrics: dict[str, Any] = response.json()["metrics"]
    return metrics


def test_home_month_equals_the_digest_month_for_the_same_selection(
    client: TestClient, session: Session
) -> None:
    """November: strategy trades on two accounts, the third has only an excluded trade."""
    size = {"reference_balance": Decimal("10000.00")}
    one, two, three = (add_account(session, f"Acc {n}", n, **size) for n in (1, 2, 3))
    closed(session, one, WED, "1000.00", "2.0")
    closed(session, two, TODAY, "457.57", "1.0")
    closed(session, three, TODAY, "-13.95", "-0.2", excluded_from_stats=True,
           excluded_reason="test", excluded_at=TODAY)  # fmt: skip

    metrics = monthly_digest(client)
    month = {"from": "2026-11-01", "to": "2026-11-30"}
    every = charts(client, **month)
    only_one = charts(client, account_id=one.id, **month)

    combined = metrics["combined"]["metrics"]
    assert combined["net_pnl"]["value"] == "1457.57"  # strategy money
    assert combined["net_pnl_pct"]["value"] == "4.8586"  # / 30000 (3 accounts traded)
    excluded = metrics["excluded"]
    assert (excluded["account_net_pnl"], excluded["account_net_pnl_pct"]) == (
        "1443.62",
        "4.8121",
    )
    assert every["account_size"] == "30000.00"
    last = every["equity"][-1]
    assert (last["cum_pnl"], last["cum_pct"]) == (
        excluded["account_net_pnl"],
        excluded["account_net_pnl_pct"],
    )
    [block] = [b for b in metrics["by_account"] if b["account_id"] == one.id]
    last_one = only_one["equity"][-1]
    assert (
        (last_one["cum_pnl"], last_one["cum_pct"])
        == (
            block["metrics"]["net_pnl"]["value"],
            block["metrics"]["net_pnl_pct"]["value"],
        )
        == ("1000.00", "10.0000")
    )
