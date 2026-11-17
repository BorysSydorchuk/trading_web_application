"""M8-09: the sync prefills exit_reason from the MT5 deal reason; owner values survive.

One in-memory fixture with a position per case (EURUSD, buy 1.16500, SL 1.16200, TP 1.17000,
tick 0.00001). Server time = UTC+3 (summer), like basic_week.json.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import Trade, TradeExitDeal
from app.mt5.fixture import FixtureMt5Source
from app.services.exit_reason import prefill_exit_reason
from app.tools.backfill_exit_reason import backfill
from tests.test_sync import WEEK_LOGIN, WEEK_NOW, add_account, run, trades_by_pid

# 2026-10-20 09:00 server time (06:00 UTC); positions are 1 h apart.
BASE = 1792486800
EURUSD = {
    "name": "EURUSD",
    "digits": 5,
    "contract_size": "100000",
    "tick_size": "0.00001",
    "tick_value": "1",
    "volume_min": "0.01",
    "volume_step": "0.01",
    "volume_max": "50",
    "currency_profit": "USD",
    "currency_margin": "EUR",
}
SL_PID, TP_PID, MANUAL_PID, PARTIAL_PID = 3000001, 3000002, 3000003, 3000004
NEAR_SL_PID, NO_MATCH_PID, STOP_OUT_PID, NEAR_TP_PID = 3000005, 3000006, 3000007, 3000008
# position -> exit deals: (price, MT5 reason code or None = field missing, volume)
EXITS: dict[int, list[tuple[str, int | None, str]]] = {
    SL_PID: [("1.162", 4, "1")],
    TP_PID: [("1.17", 5, "1")],
    MANUAL_PID: [("1.168", 0, "1")],
    PARTIAL_PID: [("1.168", 0, "0.5"), ("1.162", 4, "0.5")],
    NEAR_SL_PID: [("1.16201", None, "1")],
    NO_MATCH_PID: [("1.166", None, "1")],
    STOP_OUT_PID: [("1.161", 6, "1")],
    NEAR_TP_PID: [("1.16999", None, "1")],
}


def _deal(ticket: int, pid: int, time: int, entry: int, price: str, volume: str) -> dict[str, Any]:
    return {
        "ticket": ticket,
        "order": ticket,
        "position_id": pid,
        "time": time,
        "time_msc": time * 1000,
        "type": 0 if entry == 0 else 1,
        "entry": entry,
        "volume": volume,
        "price": price,
        "profit": "0",
        "commission": "0",
        "swap": "0",
        "fee": "0",
        "symbol": "EURUSD",
        "sl": "1.162",
        "tp": "1.17",
    }


def fixture_data() -> dict[str, Any]:
    deals: list[dict[str, Any]] = [
        _deal(1, 0, BASE - 86400, 0, "0", "0")
        | {"type": 2, "profit": "100000", "symbol": "", "reason": 0}
    ]
    for i, (pid, exits) in enumerate(EXITS.items()):
        opened = BASE + i * 3600
        deals.append(_deal(pid * 10, pid, opened, 0, "1.165", "1") | {"reason": 0})
        for j, (price, reason, volume) in enumerate(exits, start=1):
            out = _deal(pid * 10 + j, pid, opened + j * 600, 1, price, volume)
            if reason is not None:
                out["reason"] = reason
            deals.append(out)
    return {
        "format": 1,
        "account": {
            "login": WEEK_LOGIN,
            "server": "FundedNext-Server",
            "balance": "100000",
            "equity": "100000",
            "currency": "USD",
        },
        "ticks": {"EURUSD": 1792760400},
        "symbols": [EURUSD],
        "deals": deals,
        "orders": [],
        "positions": [],
    }


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


@pytest.fixture
def rules() -> RulesConfig:
    return get_rules()


def synced(session: Session, rules: RulesConfig) -> tuple[int, dict[int, Trade]]:
    account = add_account(session, WEEK_LOGIN)
    log = run(session, account, FixtureMt5Source(fixture_data()), rules, WEEK_NOW)
    assert log.ok is True, log.error_message
    return account.id, trades_by_pid(session, account.id)


def resync(session: Session, account_id: int, rules: RulesConfig) -> dict[int, Trade]:
    from app.models import Account

    account = session.get(Account, account_id)
    assert account is not None
    log = run(session, account, FixtureMt5Source(fixture_data()), rules, WEEK_NOW)
    assert log.ok is True, log.error_message
    return trades_by_pid(session, account_id)


def reason_of(trade: Trade) -> tuple[str | None, str | None]:
    return trade.exit_reason, trade.exit_reason_source


EXPECTED = {
    SL_PID: ("sl", "mt5_reason"),
    TP_PID: ("tp", "mt5_reason"),
    MANUAL_PID: (None, None),
    PARTIAL_PID: ("sl", "mt5_reason"),
    NEAR_SL_PID: ("sl", "price_match"),
    NO_MATCH_PID: (None, None),
    STOP_OUT_PID: ("stop_out", "mt5_reason"),
    NEAR_TP_PID: ("tp", "price_match"),
}


def test_sync_prefills_exit_reason(session: Session, rules: RulesConfig) -> None:
    _, trades = synced(session, rules)
    assert {pid: reason_of(t) for pid, t in trades.items()} == EXPECTED


def test_sync_stores_raw_and_mapped_reason_per_deal(session: Session, rules: RulesConfig) -> None:
    _, trades = synced(session, rules)
    rows = session.scalars(
        select(TradeExitDeal)
        .where(TradeExitDeal.trade_id == trades[PARTIAL_PID].id)
        .order_by(TradeExitDeal.time)
    ).all()
    assert [(r.reason, r.reason_code) for r in rows] == [("client", 0), ("sl", 4)]
    missing = session.scalars(
        select(TradeExitDeal).where(TradeExitDeal.trade_id == trades[NEAR_SL_PID].id)
    ).one()
    assert (missing.reason, missing.reason_code) == (None, None)


def put_journal(
    client: TestClient,
    trade: Trade,
    exit_reason: str | None,
    *,
    complete: bool = False,
    ai_filled: list[str] | None = None,
) -> Any:
    return client.put(
        f"/api/trades/{trade.id}/journal",
        json={
            "fields": {"exit_reason": exit_reason},
            "chart_links": [],
            "raw_text": None,
            "ai_filled_fields": ai_filled or [],
            "complete": complete,
        },
    )


def save(client: TestClient, trade: Trade, exit_reason: str | None) -> dict[str, Any]:
    response = put_journal(client, trade, exit_reason)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def test_owner_value_survives_resync(
    client: TestClient, session: Session, rules: RulesConfig
) -> None:
    account_id, trades = synced(session, rules)
    changed = save(client, trades[SL_PID], "fractal_update")
    assert changed["journal"]["exit_reason"] == "fractal_update"
    assert changed["exit_reason_source"] == "owner"
    cleared = save(client, trades[TP_PID], None)
    assert cleared["exit_reason_source"] == "owner"
    kept = save(client, trades[STOP_OUT_PID], "stop_out")  # saved unchanged: still MT5's
    assert kept["exit_reason_source"] == "mt5_reason"
    manual = save(client, trades[MANUAL_PID], "point_b")
    assert manual["exit_reason_source"] == "owner"

    after = resync(session, account_id, rules)
    assert reason_of(after[SL_PID]) == ("fractal_update", "owner")
    assert reason_of(after[TP_PID]) == (None, "owner")
    assert reason_of(after[STOP_OUT_PID]) == ("stop_out", "mt5_reason")
    assert reason_of(after[MANUAL_PID]) == ("point_b", "owner")
    assert reason_of(after[PARTIAL_PID]) == ("sl", "mt5_reason")


def test_value_from_before_m809_is_never_overwritten(session: Session, rules: RulesConfig) -> None:
    account_id, trades = synced(session, rules)
    session.execute(
        update(Trade)
        .where(Trade.id == trades[SL_PID].id)
        .values(exit_reason="point_b", exit_reason_source=None)
    )
    session.commit()
    after = resync(session, account_id, rules)
    assert reason_of(after[SL_PID]) == ("point_b", None)


def test_detail_marks_the_prefill_source(
    client: TestClient, session: Session, rules: RulesConfig
) -> None:
    _, trades = synced(session, rules)
    data = client.get(f"/api/trades/{trades[NEAR_SL_PID].id}").json()
    assert data["journal"]["exit_reason"] == "sl"
    assert data["exit_reason_source"] == "price_match"
    partial = client.get(f"/api/trades/{trades[PARTIAL_PID].id}").json()
    assert [d["reason"] for d in partial["exit_deals"]] == ["client", "sl"]


def test_backfill_fills_only_empty_reasons(session: Session, rules: RulesConfig) -> None:
    _, trades = synced(session, rules)
    # Pre-M8-09 state: nothing prefilled; one trade already described by the owner.
    session.execute(update(Trade).values(exit_reason=None, exit_reason_source=None))
    session.execute(
        update(Trade).where(Trade.id == trades[TP_PID].id).values(exit_reason="point_b")
    )
    session.commit()

    dry = backfill(session, apply=False)
    assert dry.filled == {"mt5_reason": 3, "price_match": 2}
    session.expire_all()
    assert session.scalar(select(Trade.exit_reason).where(Trade.id == trades[SL_PID].id)) is None

    result = backfill(session, apply=True)
    assert result.filled == {"mt5_reason": 3, "price_match": 2}
    assert result.checked == 7  # every closed trade with an empty reason
    after = trades_by_pid(session, trades[SL_PID].account_id)
    assert reason_of(after[TP_PID]) == ("point_b", None)
    assert reason_of(after[SL_PID]) == ("sl", "mt5_reason")
    assert reason_of(after[NEAR_TP_PID]) == ("tp", "price_match")
    assert reason_of(after[MANUAL_PID]) == (None, None)
    again = backfill(session, apply=True)
    assert again.filled == {}


def test_owner_value_saved_meanwhile_wins(
    db_engine: Engine, session: Session, rules: RulesConfig
) -> None:
    """Sync/backfill read an empty reason, the owner saves one before they write: kept."""
    _, trades = synced(session, rules)
    trade_id = trades[SL_PID].id
    session.execute(
        update(Trade).where(Trade.id == trade_id).values(exit_reason=None, exit_reason_source=None)
    )
    session.commit()
    stale = session.get(Trade, trade_id)
    assert stale is not None
    assert stale.exit_reason is None
    deals = list(stale.exit_deals)

    with make_session_factory(db_engine)() as owner:  # another connection commits first
        owner.execute(
            update(Trade)
            .where(Trade.id == trade_id)
            .values(exit_reason="fractal_update", exit_reason_source="owner")
        )
        owner.commit()

    assert prefill_exit_reason(session, stale, deals, Decimal("0.00001")) is None
    session.commit()
    after = trades_by_pid(session, stale.account_id)
    assert reason_of(after[SL_PID]) == ("fractal_update", "owner")


def test_rejected_complete_save_keeps_the_prefill(
    client: TestClient, session: Session, rules: RulesConfig
) -> None:
    _, trades = synced(session, rules)
    response = put_journal(client, trades[SL_PID], "fractal_update", complete=True)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "journal_incomplete"
    data = client.get(f"/api/trades/{trades[SL_PID].id}").json()
    assert data["journal"]["exit_reason"] == "sl"
    assert data["exit_reason_source"] == "mt5_reason"


def test_ai_filled_exit_reason_saved_by_the_owner_is_owner(
    client: TestClient, session: Session, rules: RulesConfig
) -> None:
    _, trades = synced(session, rules)
    response = put_journal(client, trades[MANUAL_PID], "point_b", ai_filled=["exit_reason"])
    assert response.status_code == 200, response.text
    assert response.json()["exit_reason_source"] == "owner"
    assert response.json()["ai_filled_fields"] == ["exit_reason"]
