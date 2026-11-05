"""New required fields (docs/api.md M3 "New required fields", PM 2026-11-04): a field made
required applies only to trades closed after the change; complete trades stay complete."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.api.ai import get_model_client, get_usage_log
from app.config import REPO_ROOT
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.models import Account, ChartLink, Trade
from app.services.ai.usage_log import UsageLog
from app.services.journal_requirements import INITIAL_REQUIRED_SINCE, load_requirements
from tests.services.ai_fakes import FakeClient, reply
from tests.test_trades_api import add_account, add_trade

SNAP = "https://www.tradingview.com/x/AbCd1234/"
COMPLETE: dict[str, Any] = {
    "setup_context": "yes",
    "poi_type": "fvg_h4",
    "fvg_kind": "na",
    "entry_model": "ifvg_m5",
    "exit_reason": "tp",
    "followed_plan": True,
    "emotion_before": "calm",
    "emotion_after": "confidence",
    "quality_rating": 4,
}
MISTAKES_OPTIONAL = '  - key: mistakes\n    label: "Помилки"\n    type: text\n    required: false'
MISTAKES_REQUIRED = MISTAKES_OPTIONAL.replace("required: false", "required: true")


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
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name in (
        "rules.yaml",
        "journal_fields.yaml",
        "ai_pricing.yaml",
        "extraction.yaml",
        "transcription.yaml",
        "transcript_glossary.yaml",
    ):
        shutil.copy(REPO_ROOT / "config" / name, tmp_path / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def edit_yaml(cfg_dir: Path, old: str, new: str) -> None:
    path = cfg_dir / "journal_fields.yaml"
    content = path.read_text(encoding="utf-8")
    assert old in content
    path.write_text(content.replace(old, new), encoding="utf-8")
    reload_config()


def detail(client: TestClient, trade_id: int) -> dict[str, Any]:
    response = client.get(f"/api/trades/{trade_id}")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def closed(session: Session, account: Account, close_time: datetime, **kw: Any) -> Trade:
    return add_trade(
        session, account, open_time=close_time - timedelta(minutes=30), close_time=close_time, **kw
    )


def with_before_link(session: Session, trade: Trade) -> Trade:
    session.add(ChartLink(trade_id=trade.id, url=SNAP, kind="before"))
    session.commit()
    return trade


def journal_body(fields: dict[str, Any], *, complete: bool) -> dict[str, Any]:
    return {
        "fields": fields,
        "chart_links": [{"url": SNAP, "kind": "before"}],
        "raw_text": None,
        "ai_filled_fields": [],
        "complete": complete,
    }


@pytest.fixture
def made_required(
    client: TestClient, session: Session, account: Account, cfg_dir: Path
) -> datetime:
    """First sync (1970 for today's required fields), then `mistakes` becomes required."""
    seed = closed(session, account, datetime.now(UTC) - timedelta(days=30))
    detail(client, seed.id)  # first fill
    before = datetime.now(UTC)
    edit_yaml(cfg_dir, MISTAKES_OPTIONAL, MISTAKES_REQUIRED)
    detail(client, seed.id)  # picks up the change without a restart
    since = load_requirements(session)["mistakes"]
    assert before <= since <= datetime.now(UTC)
    assert load_requirements(session)["setup_context"] == INITIAL_REQUIRED_SINCE
    return since


def test_first_read_fills_1970_and_counts_everything(
    client: TestClient, session: Session, account: Account
) -> None:
    trade = closed(session, account, datetime(2020, 1, 1, tzinfo=UTC))
    data = detail(client, trade.id)
    assert data["missing_new_fields"] == []
    assert data["missing_required"][0] == "setup_context"
    assert data["missing_required"][-1] == "chart_links"
    assert set(load_requirements(session).values()) == {INITIAL_REQUIRED_SINCE}


def test_complete_trade_stays_complete_and_shows_new_field(
    client: TestClient, session: Session, account: Account, cfg_dir: Path
) -> None:
    old = with_before_link(
        session,
        closed(
            session, account, datetime.now(UTC) - timedelta(days=1), status="complete", **COMPLETE
        ),
    )
    assert detail(client, old.id)["missing_required"] == []
    edit_yaml(cfg_dir, MISTAKES_OPTIONAL, MISTAKES_REQUIRED)

    data = detail(client, old.id)
    assert data["status"] == "complete"
    assert data["missing_required"] == []
    assert data["missing_new_fields"] == ["mistakes"]


def test_save_complete_on_old_trade_without_new_field(
    client: TestClient, session: Session, account: Account, made_required: datetime
) -> None:
    old = closed(session, account, made_required - timedelta(seconds=1))
    response = client.put(
        f"/api/trades/{old.id}/journal", json=journal_body(COMPLETE, complete=True)
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "complete"
    assert data["missing_new_fields"] == ["mistakes"]


def test_save_complete_on_new_trade_needs_new_field(
    client: TestClient, session: Session, account: Account, made_required: datetime
) -> None:
    boundary = closed(session, account, made_required)  # close_time == required_since counts
    response = client.put(
        f"/api/trades/{boundary.id}/journal", json=journal_body(COMPLETE, complete=True)
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["missing"] == ["mistakes"]
    data = detail(client, boundary.id)
    assert "mistakes" in data["missing_required"]
    assert data["missing_new_fields"] == []

    fields = COMPLETE | {"mistakes": "рано"}
    response = client.put(
        f"/api/trades/{boundary.id}/journal", json=journal_body(fields, complete=True)
    )
    assert response.status_code == 200, response.text


def test_filled_new_field_is_not_listed(
    client: TestClient, session: Session, account: Account, made_required: datetime
) -> None:
    old = closed(session, account, made_required - timedelta(days=1), mistakes="рано")
    assert detail(client, old.id)["missing_new_fields"] == []


def test_open_trade_has_no_new_fields(
    client: TestClient, session: Session, account: Account, made_required: datetime
) -> None:
    trade = add_trade(session, account, status="open", close_time=None, duration_seconds=None)
    data = detail(client, trade.id)
    assert data["missing_new_fields"] == []
    assert "mistakes" in data["missing_required"]


def test_unrequire_deletes_row_and_clears_new_fields(
    client: TestClient, session: Session, account: Account, cfg_dir: Path, made_required: datetime
) -> None:
    old = closed(session, account, made_required - timedelta(days=1))
    assert detail(client, old.id)["missing_new_fields"] == ["mistakes"]
    edit_yaml(cfg_dir, MISTAKES_REQUIRED, MISTAKES_OPTIONAL)
    assert detail(client, old.id)["missing_new_fields"] == []
    assert "mistakes" not in load_requirements(session)


def test_broken_yaml_leaves_table_alone(
    client: TestClient, session: Session, account: Account, cfg_dir: Path, made_required: datetime
) -> None:
    rows = load_requirements(session)
    trade = closed(session, account, made_required - timedelta(days=1))
    (cfg_dir / "journal_fields.yaml").write_text("fields: []\n", encoding="utf-8")
    reload_config()
    for response in (
        client.get(f"/api/trades/{trade.id}"),
        client.get("/api/trades?missing_new_fields=true"),
    ):
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "config_error"
    session.expire_all()
    assert load_requirements(session) == rows


# --- extraction ---


def test_extraction_missing_required_follows_required_since(
    app: FastAPI,
    client: TestClient,
    session: Session,
    account: Account,
    made_required: datetime,
    tmp_path: Path,
) -> None:
    app.dependency_overrides[get_usage_log] = lambda: UsageLog(tmp_path / "usage.jsonl")
    output = {"entry_model": {"value": "ifvg_m5", "evidence": "Вхід по IFVG M5"}}
    app.dependency_overrides[get_model_client] = lambda: FakeClient([reply(output), reply(output)])
    old = closed(session, account, made_required - timedelta(days=1))
    new = closed(session, account, made_required + timedelta(seconds=1))

    results = {}
    for trade in (old, new):
        response = client.post(f"/api/trades/{trade.id}/extract", json={"text": "Вхід по IFVG M5"})
        assert response.status_code == 200, response.text
        results[trade.id] = response.json()["missing_required"]
    assert "mistakes" not in results[old.id]
    assert "mistakes" in results[new.id]
    expected_new = list(results[old.id])
    expected_new.insert(expected_new.index("quality_rating"), "mistakes")  # YAML order
    assert results[new.id] == expected_new


# --- list filter ---


def _list(client: TestClient, query: str) -> dict[str, Any]:
    response = client.get(f"/api/trades?{query}")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def test_list_filter_with_pagination_and_other_filters(
    client: TestClient, session: Session, account: Account, made_required: datetime
) -> None:
    seeds = list(session.scalars(select(Trade)))  # the fixture's old trade also matches
    assert len(seeds) == 1
    other = add_account(session, "Beta", 2)
    base = made_required - timedelta(days=10)
    hits = [closed(session, account, base + timedelta(hours=i)) for i in range(5)]
    closed(session, account, base, mistakes="записано")  # filled
    closed(session, account, made_required + timedelta(minutes=1))  # closed after: not new
    add_trade(session, account, status="open", close_time=None, duration_seconds=None)
    beta_hit = closed(session, other, base)
    matching = [*seeds, *hits, beta_hit]
    newest_first = sorted(matching, key=lambda t: (t.close_time, t.id), reverse=True)

    page1 = _list(client, "missing_new_fields=true&limit=4")
    page2 = _list(client, "missing_new_fields=true&limit=4&offset=4")
    assert page1["total"] == page2["total"] == 7
    assert [r["id"] for r in page1["items"] + page2["items"]] == [t.id for t in newest_first]

    query = f"missing_new_fields=true&account_id={account.id}&sort=close_time&order=asc"
    only_alpha = _list(client, query)
    assert only_alpha["total"] == 6
    assert [r["id"] for r in only_alpha["items"]] == [t.id for t in [*seeds, *hits]]

    assert _list(client, "missing_new_fields=false")["total"] == 10
    assert _list(client, "")["total"] == 10
    assert _list(client, "missing_new_fields=true&status=complete")["total"] == 0


def test_list_filter_without_new_fields_is_empty(
    client: TestClient, session: Session, account: Account
) -> None:
    closed(session, account, datetime(2020, 1, 1, tzinfo=UTC))
    assert _list(client, "missing_new_fields=true") == {"items": [], "total": 0}


def test_list_filter_rejects_non_boolean(client: TestClient) -> None:
    response = client.get("/api/trades?missing_new_fields=maybe")
    assert response.status_code == 422
