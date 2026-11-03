"""The MT5 sync never changes a described trade's journal (docs/api.md "Journal save").

Journal saved through the API, then the fixture source advances and the sync service runs
again: status, journal values (column + extra), raw_text, ai_filled_fields, user violations
and chart links must be unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.models import Trade
from tests.test_sync import (
    WEEK_LOGIN,
    WEEK_NOW,
    WEEK_STEP1_NOW,
    add_account,
    run,
    source,
    trades_by_pid,
)

SNAP = "https://www.tradingview.com/x/AbCd1234/"
FIELDS: dict[str, Any] = {
    "setup_context": "yes",
    "poi_type": "other",
    "poi_type_other": "OB H4",
    "fvg_kind": "na",
    "entry_model": "ifvg_m5",
    "exit_reason": "tp",
    "followed_plan": True,
    "emotion_before": "calm",
    "emotion_after": "calm",
    "quality_rating": 5,
    "lesson": "patience",
    "rule_violations": ["no_breakeven"],
}
# Parts of TradeDetail the sync must not change.
JOURNAL_PARTS = ("status", "journal", "chart_links", "raw_text", "ai_filled_fields")


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


def save(client: TestClient, trade: Trade, complete: bool) -> dict[str, Any]:
    response = client.put(
        f"/api/trades/{trade.id}/journal",
        json={
            "fields": FIELDS,
            "chart_links": [{"url": SNAP, "kind": "before"}],
            "raw_text": "опис",
            "ai_filled_fields": ["setup_context", "lesson"],
            "complete": complete,
        },
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return {k: data[k] for k in JOURNAL_PARTS} | {"sources": data["rule_violations"]}


def test_sync_keeps_described_trades(
    client: TestClient, session: Session, rules: RulesConfig
) -> None:
    account = add_account(session, WEEK_LOGIN)
    src = source("basic_week.json")
    run(session, account, src, rules, WEEK_NOW)
    trades = trades_by_pid(session, account.id)
    complete, draft = trades[2000101], trades[2000301]

    before = {"complete": save(client, complete, True), "draft": save(client, draft, False)}
    assert before["complete"]["status"] == "complete"
    assert before["draft"]["status"] == "draft"

    src.advance()
    log = run(session, account, src, rules, WEEK_STEP1_NOW)
    assert log.ok is True, log.error_message
    session.expire_all()

    for name, trade in (("complete", complete), ("draft", draft)):
        data = client.get(f"/api/trades/{trade.id}").json()
        after = {k: data[k] for k in JOURNAL_PARTS} | {"sources": data["rule_violations"]}
        assert after == before[name], name
    assert ("no_breakeven", "user") in {
        (v["rule_key"], v["source"]) for v in before["complete"]["sources"]
    }
