"""One synthetic fixture -> bias -> mocked extraction -> journal -> analytics flow."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.ai import get_model_client, get_usage_log
from app.clock import utc_now
from app.config_files import get_rules
from app.db import get_db
from app.main import create_app
from app.models import SymbolSpec, Trade
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, reply
from tests.test_journal_api import COMPLETE_FIELDS, SNAP
from tests.test_sync import WEEK_LOGIN, WEEK_NOW, add_account, run, source


def test_fixture_to_persistent_journal_and_analytics(
    app: FastAPI,
    client: TestClient,
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    app.dependency_overrides[utc_now] = lambda: WEEK_NOW
    with Session(db_engine) as db:
        account = add_account(db, WEEK_LOGIN, name="SYNTHETIC M7-07")
        account_id = account.id
        log = run(db, account, source("basic_week.json"), get_rules(), WEEK_NOW)
        assert log.ok
        assert log.trades_created == 7
        assert log.open_positions == 1

    bias = client.post(
        "/api/bias/notes",
        json={
            "kind": "pre_london",
            "period_date": "2026-10-19",
            "raw_text": "Синтетичний план",
            "entries": [{"symbol": "EURUSD", "direction": "bullish", "confidence": 2}],
        },
    )
    assert bias.status_code == 201, bias.text
    response = client.get(
        "/api/trades",
        params={
            "account_id": account_id,
            "symbol": "EURUSD",
            "sort": "close_time",
            "order": "desc",
        },
    )
    assert response.status_code == 200
    rows = response.json()["items"]
    assert rows
    assert all(row["symbol"] == "EURUSD" for row in rows)
    trade = next(row for row in rows if str(row["position_id"]) == "2000101")
    trade_id = trade["id"]
    assert trade["bias_alignment"] == "aligned"

    model = FakeClient(
        [
            reply(
                {
                    "entry_model": {"value": "ifvg_m5", "evidence": "IFVG M5"},
                    "exit_reason": {"value": "tp", "evidence": "тейку"},
                }
            )
        ]
    )
    audit = UsageLog(tmp_path / "ai_usage.jsonl")
    app.dependency_overrides[get_model_client] = lambda: model
    app.dependency_overrides[get_usage_log] = lambda: audit
    extracted = client.post(
        f"/api/trades/{trade_id}/extract", json={"text": "IFVG M5, вихід по тейку"}
    )
    assert extracted.status_code == 200, extracted.text
    assert extracted.json()["fields"]["entry_model"] == "ifvg_m5"
    assert len(model.requests) == 1
    assert len(audit.path.read_text(encoding="utf-8").splitlines()) == 1

    saved = client.put(
        f"/api/trades/{trade_id}/journal",
        json={
            "fields": COMPLETE_FIELDS,
            "chart_links": [{"kind": "before", "url": SNAP}],
            "raw_text": "SYNTHETIC: опис збережено",
            "complete": True,
            "ai_filled_fields": ["entry_model", "exit_reason"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "complete"
    assert client.get("/api/dashboard").status_code == 200
    calculation = client.post(
        "/api/calculator/calculate",
        json={
            "account_id": account_id,
            "symbol": "EURUSD",
            "direction": "buy",
            "entry": "1.16500",
            "sl_price": "1.16200",
            "risk_percent": "1",
        },
    )
    # The older sync fixture predates M5 sizing metadata. Refuse safely, then use
    # explicit complete synthetic cached specs; never alter MT5/financial code.
    assert calculation.status_code == 409
    assert calculation.json()["error"]["code"] == "specs_incomplete"
    with Session(db_engine) as db:
        spec = db.scalar(
            select(SymbolSpec).where(
                SymbolSpec.account_id == account_id, SymbolSpec.symbol == "EURUSD"
            )
        )
        assert spec is not None
        spec.point = Decimal("0.00001")
        spec.tick_value_loss = Decimal("1")
        db.commit()
    calculation = client.post(
        "/api/calculator/calculate",
        json={
            "account_id": account_id,
            "symbol": "EURUSD",
            "direction": "buy",
            "entry": "1.16500",
            "sl_price": "1.16200",
            "risk_percent": "1",
        },
    )
    assert calculation.status_code == 200, calculation.text
    digest = client.post("/api/digests", json={"kind": "weekly", "date": "2026-10-19"})
    assert digest.status_code in {200, 201}, digest.text
    assert client.get("/api/backups/status").status_code == 200

    with Session(db_engine) as db:
        stored = db.get(Trade, trade_id)
        assert stored is not None
        assert stored.raw_text == "SYNTHETIC: опис збережено"
        assert stored.status == "complete"
    # A new API instance/session sees the same persisted values, not a client cache.
    restarted = create_app()
    restarted.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    fresh = TestClient(restarted, base_url="http://127.0.0.1")
    assert fresh.get(f"/api/trades/{trade_id}").json()["raw_text"] == "SYNTHETIC: опис збережено"
