"""POST /api/trades/{id}/extract and GET /api/ai/usage (docs/api.md M2). Fake model only."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.api.ai import get_model_client, get_usage_log
from app.config import get_settings
from app.db import make_session_factory
from app.models import Account, Trade
from app.models.enums import TradeStatus
from app.services.ai.client import AiCallError
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, overloaded, reply
from tests.test_trades_api import add_account, add_trade

TEXT = "Вхід по IFVG M5, закрив по тейку."
OUTPUT = {
    "entry_model": {"value": "ifvg_m5", "evidence": "Вхід по IFVG M5"},
    "exit_reason": {"value": "tp", "evidence": "закрив по тейку"},
    "followed_plan": {"value": True, "evidence": "все по плану"},
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
def account(session: Session) -> Account:
    return add_account(session, "Alpha", 1)


@pytest.fixture
def usage_log(app: FastAPI, tmp_path: Path) -> UsageLog:
    log = UsageLog(tmp_path / "ai_usage.jsonl")
    app.dependency_overrides[get_usage_log] = lambda: log
    return log


def use_model(app: FastAPI, client: FakeClient) -> FakeClient:
    app.dependency_overrides[get_model_client] = lambda: client
    return client


def extract(client: TestClient, trade_id: int, body: Any = None) -> Any:
    return client.post(f"/api/trades/{trade_id}/extract", json=body or {"text": TEXT})


def error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    err: dict[str, Any] = response.json()["error"]
    assert err["code"] == code
    return err


def test_extract_returns_guarded_fields_and_saves_nothing(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    trade = add_trade(session, account)
    model = use_model(app, FakeClient([reply(OUTPUT)]))

    response = extract(client, trade.id)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["fields"] == {"entry_model": "ifvg_m5", "exit_reason": "tp"}
    assert data["ai_filled_fields"] == ["entry_model", "exit_reason"]
    assert data["dropped"] == [{"key": "followed_plan", "reason": "evidence_not_in_text"}]
    assert data["missing_required"][-1] == "chart_links"
    assert "entry_model" not in data["missing_required"]
    assert data["usage"] == {
        "model": "claude-sonnet-5-5",
        "fallback_used": False,
        "input_tokens": 1830,
        "output_tokens": 210,
        "cost_usd": "0.0058",
        "duration_ms": data["usage"]["duration_ms"],
    }
    assert model.requests[0].user_text == TEXT
    session.expire_all()
    stored = session.scalars(select(Trade).where(Trade.id == trade.id)).one()
    assert (stored.entry_model, stored.raw_text, stored.status) == (
        None,
        None,
        TradeStatus.NEEDS_DESCRIPTION.value,
    )
    assert len(usage_log.path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("status", ["draft", "complete"])
def test_extract_allowed_for_draft_and_complete(
    app: FastAPI,
    client: TestClient,
    session: Session,
    account: Account,
    usage_log: UsageLog,
    status: str,
) -> None:
    trade = add_trade(session, account, status=status)
    use_model(app, FakeClient([reply(OUTPUT)]))
    assert extract(client, trade.id).status_code == 200


def test_extract_needs_sl_and_open_trade(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    use_model(app, FakeClient([]))
    needs_sl = add_trade(session, account, status=TradeStatus.NEEDS_SL.value)
    open_trade = add_trade(
        session, account, status=TradeStatus.OPEN.value, close_time=None, exit_price=None
    )
    error(extract(client, needs_sl.id), 409, "needs_sl")
    error(extract(client, open_trade.id), 409, "trade_open")
    error(extract(client, 999999), 404, "not_found")
    assert not usage_log.path.exists()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"text": ""}, "text"),
        ({"text": "   \n"}, "text"),
        ({"text": "x" * 20001}, "text"),
        ({"text": 5}, "text"),
        ({}, "text"),
        ({"text": "ok", "model": "x"}, "model"),
    ],
)
def test_extract_validation(
    app: FastAPI,
    client: TestClient,
    session: Session,
    account: Account,
    body: dict[str, Any],
    field: str,
) -> None:
    trade = add_trade(session, account)
    use_model(app, FakeClient([]))
    err = error(client.post(f"/api/trades/{trade.id}/extract", json=body), 422, "validation_error")
    assert field in err["details"]["fields"]


def test_extract_max_length_text_is_accepted(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    trade = add_trade(session, account)
    use_model(app, FakeClient([reply({})]))
    assert extract(client, trade.id, {"text": "x" * 20000}).status_code == 200


def test_extract_without_key_is_ai_not_configured(
    client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    assert not get_settings().ai_configured  # conftest empties ANTHROPIC_API_KEY
    trade = add_trade(session, account)
    error(extract(client, trade.id), 503, "ai_not_configured")


@pytest.mark.parametrize(
    ("script", "kind"),
    [
        ([AiCallError("auth", "AuthenticationError HTTP 401")], "auth"),
        ([AiCallError("rate_limit", "RateLimitError HTTP 429")], "rate_limit"),
        ([overloaded(), overloaded()], "overloaded"),
        ([reply(text="", stop_reason="refusal")], "refusal"),
        ([reply(text="nope")], "invalid_output"),
    ],
)
def test_extract_ai_errors(
    app: FastAPI,
    client: TestClient,
    session: Session,
    account: Account,
    usage_log: UsageLog,
    script: list[Any],
    kind: str,
) -> None:
    trade = add_trade(session, account)
    use_model(app, FakeClient(script))
    err = error(extract(client, trade.id), 502, "ai_error")
    assert err["details"] == {"kind": kind}
    assert len(usage_log.path.read_text(encoding="utf-8").splitlines()) == len(script)


def test_extract_fallback_reported_in_usage(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    trade = add_trade(session, account)
    use_model(app, FakeClient([overloaded(), reply(OUTPUT, model="claude-opus-5-5")]))
    usage = extract(client, trade.id).json()["usage"]
    assert (usage["model"], usage["fallback_used"]) == ("claude-opus-5-5", True)
    assert len(usage_log.path.read_text(encoding="utf-8").splitlines()) == 2


# --- usage ---


def test_ai_usage_month_to_date(
    client: TestClient, usage_log: UsageLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rows = [
        {"ts": now, "ok": True, "cost_usd": "0.0058", "input_tokens": 1830, "output_tokens": 210},
        {"ts": now, "ok": False, "cost_usd": "0.0000", "input_tokens": 0, "output_tokens": 0},
        {"ts": now, "ok": True, "cost_usd": None, "input_tokens": 10, "output_tokens": 1},
        {
            "ts": "2020-01-01T00:00:00Z",
            "ok": True,
            "cost_usd": "9.0",
            "input_tokens": 1,
            "output_tokens": 1,
        },
    ]
    usage_log.path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n{broken\n", encoding="utf-8"
    )
    monkeypatch.setenv("ANTHROPIC_MODEL_EXTRACTION", "claude-sonnet-5-5")
    get_settings.cache_clear()
    try:
        data = client.get("/api/ai/usage").json()
    finally:
        get_settings.cache_clear()
    assert data == {
        "month": data["month"],
        "cost_usd": "0.0058",
        "calls": 3,
        "failed_calls": 1,
        "unpriced_calls": 1,
        "input_tokens": 1840,
        "output_tokens": 211,
        "configured": False,
        "extraction_model": "claude-sonnet-5-5",
    }


def test_ai_usage_configured_flag(
    client: TestClient, usage_log: UsageLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    get_settings.cache_clear()
    try:
        data = client.get("/api/ai/usage").json()
    finally:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        get_settings.cache_clear()
    assert data["configured"] is True
    assert (data["calls"], data["cost_usd"]) == (0, "0.0000")


def test_get_model_client_is_none_without_key() -> None:
    assert get_model_client() is None


def test_app_starts_without_key_and_health_works(client: TestClient) -> None:
    assert not get_settings().ai_configured
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
