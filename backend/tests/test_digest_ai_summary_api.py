"""POST /api/digests/{id}/ai-summary (docs/api.md "M6", task M6-07). Fake model only."""

# ruff: noqa: RUF001 - Ukrainian sample texts

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api.ai import get_usage_log
from app.clock import utc_now
from app.config import get_settings
from app.db import make_session_factory
from app.models import Digest, Trade
from app.services.ai.client import AiCallError, ModelRequest
from app.services.ai.digest_summary import MAX_SUMMARY_CHARS, PURPOSE, summary_text
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, reply
from tests.test_ai_api import error, use_model
from tests.test_digests_api import NOW, closed, digest
from tests.test_trades_api import add_account

OBSERVATIONS = [
    "  За тиждень 2 угоди, чистий результат 150.00 USD.  ",
    "",
    "Обидві помилки стосуються раннього входу.",
    "   ",
    "Сума R 1.5000 вища за норму.",
]


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


@pytest.fixture
def usage_log(app: FastAPI, tmp_path: Path) -> UsageLog:
    log = UsageLog(tmp_path / "ai_usage.jsonl")
    app.dependency_overrides[get_usage_log] = lambda: log
    return log


@pytest.fixture
def set_now(app: FastAPI) -> Callable[[datetime], None]:
    def _set(value: datetime) -> None:
        app.dependency_overrides[utc_now] = lambda: value

    _set(NOW)
    return _set


@pytest.fixture
def week(session: Session, set_now: Callable[..., None]) -> dict[str, Trade]:
    """Two trades in the week of 9 Nov 2026 (with journal texts) and one the week before."""
    account = add_account(session, "Alpha", 1)
    inside = closed(
        session,
        account,
        datetime(2026, 11, 10, 9, tzinfo=UTC),
        "100.00",
        "1.0",
        mistakes="Ранній вхід до підтвердження",
        lesson="Чекати закриття свічки M5",
        raw_text="Зайшов по IFVG M5 зарано.",
    )
    quiet = closed(session, account, datetime(2026, 11, 11, 9, tzinfo=UTC), "50.00", "0.5")
    before = closed(
        session,
        account,
        datetime(2026, 11, 4, 9, tzinfo=UTC),
        "-80.00",
        "-1.0",
        mistakes="ІНША_ПОМИЛКА_МИНУЛОГО_ТИЖНЯ",
    )
    return {"inside": inside, "quiet": quiet, "before": before}


def answer(observations: list[str] = OBSERVATIONS, **kwargs: Any) -> Any:
    return reply(text=json.dumps({"observations": observations}, ensure_ascii=False), **kwargs)


def summarise(client: TestClient, digest_id: int) -> Any:
    return client.post(f"/api/digests/{digest_id}/ai-summary")


def lines(log: UsageLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


def stored_summary(session: Session, digest_id: int) -> str | None:
    session.expire_all()
    row = session.get(Digest, digest_id)
    assert row is not None
    return row.ai_summary


def user_payload(request: ModelRequest) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(request.user_text)
    return payload


def test_summary_is_stored_and_returned_with_the_full_digest(
    app: FastAPI,
    client: TestClient,
    session: Session,
    week: dict[str, Trade],
    usage_log: UsageLog,
) -> None:
    created = digest(client)
    model = use_model(app, FakeClient([answer(model="claude-opus-5-5")]))

    response = summarise(client, created["id"])

    assert response.status_code == 200, response.text
    data = response.json()
    expected = (
        "За тиждень 2 угоди, чистий результат 150.00 USD.\n"
        "Обидві помилки стосуються раннього входу.\n"
        "Сума R 1.5000 вища за норму."
    )
    assert data["ai_summary"] == expected
    assert stored_summary(session, created["id"]) == expected
    assert data == client.get(f"/api/digests/{created['id']}").json()
    assert data["metrics"] == created["metrics"]
    [request] = model.requests
    settings = get_settings()
    assert request.model == settings.anthropic_model_summary
    assert request.model != settings.anthropic_model_extraction
    assert "3 to 7 observations" in request.system
    [line] = lines(usage_log)
    assert (line["purpose"], line["trade_id"], line["ok"]) == (PURPOSE, None, True)
    assert line["purpose"] == "digest_summary"
    assert line["requested_model"] == settings.anthropic_model_summary


def test_input_has_the_period_numbers_and_only_the_period_journal_texts(
    app: FastAPI, client: TestClient, week: dict[str, Trade], usage_log: UsageLog
) -> None:
    created = digest(client)
    model = use_model(app, FakeClient([answer()]))

    assert summarise(client, created["id"]).status_code == 200

    payload = user_payload(model.requests[0])
    assert payload["period"] == {"kind": "weekly", "start": "2026-11-09", "end": "2026-11-15"}
    snapshot = payload["snapshot"]
    assert snapshot["combined"] == created["metrics"]["combined"]
    assert snapshot["combined"]["metrics"]["trades"]["value"] == 2
    assert snapshot["combined"]["metrics"]["net_pnl"]["value"] == "150.00"
    assert snapshot["by_account"] == created["metrics"]["by_account"]
    assert {"breakdowns", "rules", "bias", "currency"} <= snapshot.keys()
    assert "charts" not in snapshot
    assert payload["trades"] == [
        {
            "id": week["inside"].id,
            "symbol": "XAUUSD",
            "net_pnl": "100.00",
            "r_multiple": "1.0000",
            "mistakes": "Ранній вхід до підтвердження",
            "lesson": "Чекати закриття свічки M5",
            "raw_text": "Зайшов по IFVG M5 зарано.",
        }
    ]
    assert "ІНША_ПОМИЛКА_МИНУЛОГО_ТИЖНЯ" not in model.requests[0].user_text


def test_without_key_is_ai_not_configured_and_makes_no_call(
    client: TestClient, session: Session, week: dict[str, Trade], usage_log: UsageLog
) -> None:
    created = digest(client)
    error(summarise(client, created["id"]), 503, "ai_not_configured")
    assert stored_summary(session, created["id"]) is None
    assert not usage_log.path.exists()


def test_api_error_is_ai_error_and_keeps_the_previous_summary(
    app: FastAPI,
    client: TestClient,
    session: Session,
    week: dict[str, Trade],
    usage_log: UsageLog,
) -> None:
    created = digest(client)
    session.execute(text("UPDATE digests SET ai_summary = 'old summary'"))
    session.commit()
    use_model(app, FakeClient([AiCallError("rate_limit", "RateLimitError HTTP 429")]))

    err = error(summarise(client, created["id"]), 502, "ai_error")

    assert err["details"] == {"kind": "rate_limit"}
    assert stored_summary(session, created["id"]) == "old summary"
    [line] = lines(usage_log)
    assert (line["purpose"], line["ok"], line["error_kind"]) == (PURPOSE, False, "rate_limit")


@pytest.mark.parametrize(
    "bad",
    [
        answer([]),
        answer(["", "   ", "\n"]),
        reply(text=json.dumps({"observations": "один рядок"}, ensure_ascii=False)),
        reply(text="not json"),
    ],
)
def test_empty_or_malformed_output_is_invalid_output(
    app: FastAPI,
    client: TestClient,
    session: Session,
    week: dict[str, Trade],
    usage_log: UsageLog,
    bad: Any,
) -> None:
    created = digest(client)
    use_model(app, FakeClient([bad]))

    err = error(summarise(client, created["id"]), 502, "ai_error")

    assert err["details"] == {"kind": "invalid_output"}
    assert stored_summary(session, created["id"]) is None


def test_unknown_digest_is_404_without_a_call(
    app: FastAPI, client: TestClient, usage_log: UsageLog
) -> None:
    model = use_model(app, FakeClient([]))
    error(summarise(client, 999), 404, "not_found")
    assert model.requests == []


def test_output_guard_caps_lines_and_length() -> None:
    many = [f"Спостереження {i}." for i in range(10)]
    assert summary_text({"observations": many}).splitlines() == many[:7]
    long = summary_text({"observations": ["x" * 5000]})
    assert len(long) == MAX_SUMMARY_CHARS
    assert summary_text({"observations": ["  a\n b  "]}) == "a b"
