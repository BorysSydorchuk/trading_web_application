"""M8-01: exclude a trade from strategy statistics (docs/api.md "M8-01").

An excluded trade leaves every strategy number (inbox, digest metrics, norm, breakdowns,
rules/bias sections, charts, digest list) but stays in money and risk (dashboard P&L, stops,
rules engine). The flag, reason and history survive a re-sync. Revert restores everything.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config_files import get_rules
from app.db import make_session_factory
from app.models import Account, RuleViolation, Trade
from app.services.trade_rules import recompute_rules
from tests.test_trades_api import add_account, add_trade

D = Decimal
# Thu 2026-11-12 14:00 UTC = 15:00 Brussels. Week Mon 9 - Sun 15 Nov.
NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
TODAY = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
WED = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
WEEK = "2026-11-09"
REASON = "перевірка торгівлі на новому рахунку"


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts, digests, bias_notes RESTART IDENTITY CASCADE"))

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


@pytest.fixture(autouse=True)
def _now(app: FastAPI) -> None:
    app.dependency_overrides[utc_now] = lambda: NOW


def closed(
    db: Session, account: Account, close: datetime, pnl: str, r: str | None, **kw: Any
) -> Trade:
    fields: dict[str, Any] = {
        "open_time": close - timedelta(minutes=30),
        "close_time": close,
        "net_pnl": D(pnl),
        "r_multiple": None if r is None else D(r),
        "status": "complete",
        "symbol": "EURUSD",
    }
    return add_trade(db, account, **(fields | kw))


@pytest.fixture
def account(session: Session) -> Account:
    return add_account(session, "Alpha", 1, reference_balance=D("10000.00"))


@pytest.fixture
def week(session: Session, account: Account) -> dict[str, Trade]:
    """Strategy: +200 (2R) and -100 (-1R) today; the XAUUSD test trade -50 (-0.5R) on Wed."""
    return {
        "win": closed(session, account, TODAY, "200.00", "2.0"),
        "loss": closed(session, account, TODAY + timedelta(hours=1), "-100.00", "-1.0"),
        "test": closed(
            session, account, WED, "-50.00", "-0.5", symbol="XAUUSD", status="needs_description"
        ),
    }


def exclude(client: TestClient, trade_id: int, reason: Any = REASON) -> Any:
    body = {} if reason is None else {"reason": reason}
    return client.post(f"/api/trades/{trade_id}/exclude", json=body)


def include(client: TestClient, trade_id: int, reason: str | None = None) -> Any:
    return client.post(f"/api/trades/{trade_id}/include", json={"reason": reason})


def ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def digest(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/digests", json={"kind": "weekly", "date": WEEK})
    assert response.status_code in (200, 201), response.text
    metrics: dict[str, Any] = response.json()["metrics"]
    return metrics


def value(metrics: dict[str, Any], name: str) -> Any:
    return metrics["combined"]["metrics"][name]["value"]


# --- API -------------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_missing_or_blank_reason_is_422(
    client: TestClient, week: dict[str, Trade], reason: Any
) -> None:
    response = exclude(client, week["test"].id, reason)

    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert "reason" in response.json()["error"]["details"]["fields"]
    assert ok(client.get(f"/api/trades/{week['test'].id}"))["excluded_from_stats"] is False


def test_too_long_or_nul_reason_is_422(client: TestClient, week: dict[str, Trade]) -> None:
    assert exclude(client, week["test"].id, "x" * 1001).status_code == 422
    assert exclude(client, week["test"].id, "bad\x00reason").status_code == 422


def test_exclude_sets_flag_reason_time_and_history(
    client: TestClient, week: dict[str, Trade]
) -> None:
    body = ok(exclude(client, week["test"].id, f"  {REASON}  "))

    assert body["excluded_from_stats"] is True
    assert body["excluded_reason"] == REASON
    assert body["excluded_at"] == "2026-11-12T14:00:00Z"
    assert body["exclusion_history"] == [
        {"action": "exclude", "reason": REASON, "at": "2026-11-12T14:00:00Z"}
    ]


def test_exclude_twice_is_409_and_unknown_trade_is_404(
    client: TestClient, week: dict[str, Trade]
) -> None:
    ok(exclude(client, week["test"].id))

    again = exclude(client, week["test"].id, "інша причина")
    assert again.status_code == 409
    assert error_code(again) == "already_excluded"
    assert exclude(client, 999999).status_code == 404


def test_include_not_excluded_is_409(client: TestClient, week: dict[str, Trade]) -> None:
    response = include(client, week["test"].id)

    assert response.status_code == 409
    assert error_code(response) == "not_excluded"


def test_revert_clears_flag_and_keeps_both_history_rows(
    client: TestClient, week: dict[str, Trade]
) -> None:
    ok(exclude(client, week["test"].id))

    body = ok(include(client, week["test"].id, "  помилково  "))

    assert body["excluded_from_stats"] is False
    assert body["excluded_reason"] is None
    assert body["excluded_at"] is None
    assert [(h["action"], h["reason"]) for h in body["exclusion_history"]] == [
        ("exclude", REASON),
        ("include", "помилково"),
    ]
    # A blank revert reason is stored as none; the trade can be excluded again.
    ok(exclude(client, week["test"].id, "знову"))
    final = ok(include(client, week["test"].id, "  "))
    assert [h["reason"] for h in final["exclusion_history"]] == [REASON, "помилково", "знову", None]


def test_list_filter_and_row_fields(client: TestClient, week: dict[str, Trade]) -> None:
    ok(exclude(client, week["test"].id))

    every = ok(client.get("/api/trades"))
    only = ok(client.get("/api/trades", params={"excluded": "true"}))
    counted = ok(client.get("/api/trades", params={"excluded": "false"}))

    assert every["total"] == 3
    assert [t["id"] for t in only["items"]] == [week["test"].id]
    assert only["items"][0]["excluded_reason"] == REASON
    assert {t["id"] for t in counted["items"]} == {week["win"].id, week["loss"].id}
    assert all(t["excluded_from_stats"] is False for t in counted["items"])


def test_excluded_trade_leaves_the_inbox_and_revert_brings_it_back(
    client: TestClient, week: dict[str, Trade]
) -> None:
    assert ok(client.get("/api/inbox/counts"))["needs_description"] == 1

    ok(exclude(client, week["test"].id))
    assert ok(client.get("/api/inbox/counts"))["needs_description"] == 0
    assert ok(client.get("/api/dashboard"))["inbox"]["needs_description"] == 0

    ok(include(client, week["test"].id))
    assert ok(client.get("/api/inbox/counts"))["needs_description"] == 1


def test_excluded_trade_without_sl_stays_in_needs_sl(
    client: TestClient, session: Session, account: Account
) -> None:
    """The risk rules need the initial SL, so «Потрібен SL» still asks for it."""
    trade = closed(session, account, TODAY, "-10.00", None, status="needs_sl")
    ok(exclude(client, trade.id))

    assert ok(client.get("/api/inbox/counts"))["needs_sl"] == 1


def test_open_trade_can_be_excluded_and_stays_excluded_when_it_closes(
    client: TestClient, session: Session, account: Account
) -> None:
    trade = add_trade(session, account, status="open", close_time=None, net_pnl=None)
    ok(exclude(client, trade.id))

    trade.status, trade.close_time, trade.net_pnl = "needs_description", TODAY, D("5.00")
    session.commit()
    session.refresh(trade)

    assert (trade.excluded_from_stats, trade.excluded_reason) == (True, REASON)
    assert ok(client.get("/api/inbox/counts"))["needs_description"] == 0


# --- money and risk stay ---------------------------------------------------------------------


def test_dashboard_pnl_and_limits_include_the_excluded_trade(
    client: TestClient, week: dict[str, Trade]
) -> None:
    before = ok(client.get("/api/dashboard"))["accounts"][0]

    ok(exclude(client, week["test"].id))
    after = ok(client.get("/api/dashboard"))["accounts"][0]

    assert after["week"]["pnl"] == before["week"]["pnl"] == "50.00"
    assert after["week"] == before["week"]
    assert after["today"] == before["today"]
    assert after["week_state"] == before["week_state"]


def test_rules_engine_still_counts_the_excluded_trade(session: Session, account: Account) -> None:
    rules = get_rules()
    trades = [
        closed(session, account, WED + timedelta(minutes=10 * i), "10.00", "0.1") for i in range(11)
    ]
    trades[0].excluded_from_stats = True
    trades[0].excluded_reason = REASON
    trades[0].excluded_at = NOW
    session.commit()

    recompute_rules(session, account.id, WED, rules)
    session.commit()

    eleventh = session.scalars(
        select(RuleViolation.rule_key).where(RuleViolation.trade_id == trades[10].id)
    ).all()
    assert "max_trades_per_week" in eleventh


# --- digests ---------------------------------------------------------------------------------


def test_digest_strategy_metrics_skip_the_excluded_trade(
    client: TestClient, week: dict[str, Trade]
) -> None:
    ok(exclude(client, week["test"].id))

    metrics = digest(client)

    assert value(metrics, "trades") == 2
    assert value(metrics, "net_pnl") == "100.00"
    assert value(metrics, "win_rate") == "50.0000"
    assert value(metrics, "total_r") == "1.0000"
    assert metrics["combined"]["metrics"]["total_r"]["n"] == 2
    assert metrics["by_account"][0]["metrics"]["trades"]["value"] == 2
    assert metrics["trade_ids"] == sorted([week["win"].id, week["loss"].id])
    symbols = {g["key"] for g in metrics["breakdowns"]["symbol"]["groups"]}
    assert symbols == {"EURUSD"}
    assert metrics["charts"]["equity"]["combined"][-1]["cum_pnl"] == "100.00"
    assert metrics["combined"]["worst_trade"]["trade_id"] == week["loss"].id


def test_digest_excluded_block_reconciles_with_the_account(
    client: TestClient, week: dict[str, Trade]
) -> None:
    ok(exclude(client, week["test"].id))

    excluded = digest(client)["excluded"]

    assert excluded["trades"] == 1
    assert excluded["net_pnl"] == "-50.00"
    assert excluded["account_net_pnl"] == "50.00"
    assert excluded["items"] == [
        {
            "trade_id": week["test"].id,
            "account_id": week["test"].account_id,
            "account_name": "Alpha",
            "symbol": "XAUUSD",
            "close_time": "2026-11-11T09:00:00Z",
            "net_pnl": "-50.00",
            "reason": REASON,
        }
    ]


def test_digest_without_exclusions_has_an_empty_block(
    client: TestClient, week: dict[str, Trade]
) -> None:
    metrics = digest(client)

    assert value(metrics, "trades") == 3
    assert metrics["excluded"] == {
        "trades": 0,
        "net_pnl": "0.00",
        "account_net_pnl": "50.00",
        "account_net_pnl_pct": "0.5000",
        "items": [],
    }


def test_revert_restores_every_digest_metric(client: TestClient, week: dict[str, Trade]) -> None:
    baseline = digest(client)
    ok(exclude(client, week["test"].id))
    assert digest(client) != baseline

    ok(include(client, week["test"].id))

    assert digest(client) == baseline


def test_norm_window_skips_excluded_trades(
    client: TestClient, session: Session, account: Account
) -> None:
    """A huge excluded loss in the history must not move the norm."""
    for weeks_back in range(1, 9):
        closed(session, account, TODAY - timedelta(weeks=weeks_back), "100.00", "1.0")
    big = closed(session, account, TODAY - timedelta(weeks=2, hours=1), "-5000.00", "-50.0")
    closed(session, account, TODAY, "100.00", "1.0")
    counted = digest(client)["combined"]["metrics"]["net_pnl"]["norm_mean"]

    ok(exclude(client, big.id))

    assert counted != "100.00"
    assert digest(client)["combined"]["metrics"]["net_pnl"]["norm_mean"] == "100.00"


def test_bias_and_rules_sections_skip_the_excluded_trade(
    client: TestClient, session: Session, week: dict[str, Trade]
) -> None:
    test_trade = week["test"]
    test_trade.bias_alignment = "aligned"
    session.add(RuleViolation(trade_id=test_trade.id, rule_key="outside_session", source="auto"))
    session.commit()
    ok(exclude(client, test_trade.id))

    metrics = digest(client)

    assert metrics["rules"]["violated_trades"] == 0
    assert metrics["bias"]["daily"]["aligned"]["trades"] == 0


def test_digest_list_rows_skip_the_excluded_trade(
    client: TestClient, week: dict[str, Trade]
) -> None:
    ok(exclude(client, week["test"].id))

    rows = ok(client.get("/api/digests", params={"kind": "weekly"}))["items"]

    virtual = next(r for r in rows if r["period_start"] == WEEK)
    assert virtual["id"] is None
    assert (virtual["trades"], virtual["net_pnl"]) == (2, "100.00")


# --- data model ------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", [None, "   "])
def test_db_rejects_an_inconsistent_flag(
    session: Session, account: Account, reason: str | None
) -> None:
    trade = closed(session, account, TODAY, "1.00", None)
    trade.excluded_from_stats = True
    trade.excluded_reason = reason
    trade.excluded_at = NOW
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_new_trades_are_counted_by_default(session: Session, account: Account) -> None:
    trade = closed(session, account, TODAY, "1.00", None)
    session.refresh(trade)

    assert (trade.excluded_from_stats, trade.excluded_reason, trade.excluded_at) == (
        False,
        None,
        None,
    )


# --- re-sync ---------------------------------------------------------------------------------


def test_exclusion_survives_resync_and_partial_close_update(
    client: TestClient, session: Session
) -> None:
    from tests.test_exit_reason_sync import PARTIAL_PID, resync, synced

    rules = get_rules()
    account_id, trades = synced(session, rules)
    target = trades[PARTIAL_PID]
    ok(exclude(client, target.id))
    pnl_before = target.net_pnl

    after = resync(session, account_id, rules)[PARTIAL_PID]
    detail = ok(client.get(f"/api/trades/{target.id}"))

    assert after.id == target.id
    assert after.net_pnl == pnl_before
    assert (after.excluded_from_stats, after.excluded_reason) == (True, REASON)
    assert after.excluded_at is not None
    assert [h["action"] for h in detail["exclusion_history"]] == ["exclude"]
    assert len(detail["exit_deals"]) == 2
