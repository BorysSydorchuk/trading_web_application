"""Bias notes / entries / status API (docs/api.md M4, M4-05)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import REPO_ROOT, Settings, get_settings
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.models import Account, AudioNote, BiasEntry, ChartLink, Trade
from app.services import bias_notes
from tests.services.test_bias_alignment_service import truncate_all
from tests.test_trades_api import add_account, add_trade

SNAP = "https://www.tradingview.com/x/AbCd1234/"
SNAP_PREVIEW = "https://s3.tradingview.com/snapshots/a/AbCd1234.png"
CHART = "https://www.tradingview.com/chart/Xy12ab/"
THU = "2026-11-05"  # winter time, UTC+1
WEBM = b"\x1aE\xdf\xa3fake-webm-bytes"


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    truncate_all(db_engine)
    yield
    truncate_all(db_engine)


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


def set_now(app: FastAPI, moment: datetime) -> None:
    app.dependency_overrides[utc_now] = lambda: moment


def entry(symbol: str = "XAUUSD", direction: str = "bullish", **kw: Any) -> dict[str, Any]:
    return {"symbol": symbol, "direction": direction} | kw


def note_body(
    kind: str = "pre_ny", period_date: str = THU, entries: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "kind": kind,
        "period_date": period_date,
        "raw_text": "золото вгору",
        "entries": [entry()] if entries is None else entries,
    }


def ok(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    data: dict[str, Any] = response.json()
    return data


def create(client: TestClient, **kw: Any) -> dict[str, Any]:
    return ok(client.post("/api/bias/notes", json=note_body(**kw)), 201)


def field_errors(response: Any) -> dict[str, str]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields: dict[str, str] = error["details"]["fields"]
    return fields


def trade_detail(client: TestClient, trade_id: int) -> dict[str, Any]:
    return ok(client.get(f"/api/trades/{trade_id}"))


# --- create ---


def test_create_shape(client: TestClient) -> None:
    data = create(
        client,
        entries=[
            entry("GER40", "bearish", key_levels="  18500 POI  ", confidence=2),
            entry(
                "EURUSD",
                "neutral",
                narrative="",
                chart_links=[{"url": SNAP}, {"url": CHART}],
                ai_filled_fields=["direction", "narrative", "direction"],
            ),
        ],
    )
    assert data["kind"] == "pre_ny"
    assert data["period_date"] == THU
    assert data["raw_text"] == "золото вгору"
    assert data["audio_notes"] == []
    assert data["created_at"].endswith("Z")
    assert [e["symbol"] for e in data["entries"]] == ["EURUSD", "GER40"]  # bias.yaml order
    eur, ger = data["entries"]
    assert ger["key_levels"] == "18500 POI"
    assert ger["confidence"] == 2
    assert eur["narrative"] is None
    assert eur["ai_filled_fields"] == ["direction"]  # empty narrative dropped, dupes dropped
    assert [(c["url"], c["kind"], c["preview_url"]) for c in eur["chart_links"]] == [
        (SNAP, "bias", SNAP_PREVIEW),
        (CHART, "bias", None),
    ]
    assert (ger["was_correct"], ger["was_correct_source"]) == (None, None)


def test_create_without_entries(client: TestClient) -> None:
    data = create(client, entries=[])
    assert data["entries"] == []


@pytest.mark.parametrize(
    ("kind", "given", "stored"),
    [("weekly", "2026-11-05", "2026-11-02"), ("monthly", "2026-11-05", "2026-11-01")],
)
def test_create_normalizes_period(client: TestClient, kind: str, given: str, stored: str) -> None:
    assert create(client, kind=kind, period_date=given)["period_date"] == stored


def test_create_conflict(client: TestClient) -> None:
    first = create(client, kind="weekly", period_date="2026-11-02")
    response = client.post("/api/bias/notes", json=note_body("weekly", "2026-11-06"))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "bias_note_exists"
    assert error["details"] == {"id": first["id"]}


@pytest.mark.parametrize(
    ("entries", "key"),
    [
        ([entry("US30")], "entries.0.symbol"),
        ([entry("xauusd")], "entries.0.symbol"),
        ([entry(), entry("GER40"), entry()], "entries.2.symbol"),
        ([entry(direction="up")], "entries.0.direction"),
        ([{"symbol": "XAUUSD"}], "entries.0.direction"),
        ([entry(confidence=4)], "entries.0.confidence"),
        ([entry(confidence=0)], "entries.0.confidence"),
        ([entry(confidence="2")], "entries.0.confidence"),
        ([entry(key_levels=5)], "entries.0.key_levels"),
        ([entry(chart_links=[{"url": "https://example.com/x/1"}])], "entries.0.chart_links.0.url"),
        (
            [entry(), entry("GER40", chart_links=[{"url": SNAP}, {"url": SNAP + "?a=1"}])],
            "entries.1.chart_links.1.url",
        ),
        ([entry(chart_links=[{"url": SNAP, "kind": "bias"}])], "entries.0.chart_links.0.kind"),
        ([entry(ai_filled_fields=["was_correct"])], "entries.0.ai_filled_fields.0"),
        ([entry(extra=1)], "entries.0.extra"),
    ],
)
def test_create_entry_validation(
    client: TestClient, entries: list[dict[str, Any]], key: str
) -> None:
    errors = field_errors(client.post("/api/bias/notes", json=note_body(entries=entries)))
    assert key in errors, errors


@pytest.mark.parametrize(
    ("change", "key"),
    [
        ({"kind": "daily"}, "kind"),
        ({"period_date": "05.11.2026"}, "period_date"),
        ({"period_date": 1793750400}, "period_date"),
        ({"raw_text": 1}, "raw_text"),
        ({"other": True}, "other"),
    ],
)
def test_create_note_validation(client: TestClient, change: dict[str, Any], key: str) -> None:
    errors = field_errors(client.post("/api/bias/notes", json=note_body() | change))
    assert key in errors, errors


def test_create_requires_entries(client: TestClient) -> None:
    body = note_body()
    del body["entries"]
    assert "entries" in field_errors(client.post("/api/bias/notes", json=body))


# --- read ---


def test_get_one_and_404(client: TestClient) -> None:
    created = create(client)
    assert ok(client.get(f"/api/bias/notes/{created['id']}")) == created
    response = client.get("/api/bias/notes/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_by_period(client: TestClient) -> None:
    monthly = create(client, kind="monthly", period_date="2026-11-01")
    found = ok(client.get("/api/bias/notes/by-period", params={"kind": "monthly", "date": THU}))
    assert found["id"] == monthly["id"]
    missing = client.get("/api/bias/notes/by-period", params={"kind": "pre_ny", "date": THU})
    assert missing.status_code == 404
    bad = client.get("/api/bias/notes/by-period", params={"kind": "x", "date": THU})
    assert "kind" in field_errors(bad)


def test_list_default_range_order_and_filter(app: FastAPI, client: TestClient) -> None:
    set_now(app, datetime(2026, 11, 5, 23, 30, tzinfo=UTC))  # Fri 00:30 in Brussels
    friday = create(client, kind="pre_london", period_date="2026-11-06")
    ny = create(client, kind="pre_ny", period_date=THU)
    london = create(client, kind="pre_london", period_date=THU)
    weekly = create(client, kind="weekly", period_date="2026-11-02")
    oldest_in = create(client, kind="pre_ny", period_date="2026-10-08")  # today - 29
    create(client, kind="pre_ny", period_date="2026-10-07")  # today - 30: outside
    create(client, kind="pre_ny", period_date="2026-11-07")  # future: outside

    items = ok(client.get("/api/bias/notes"))["items"]
    assert [n["id"] for n in items] == [
        friday["id"],
        ny["id"],
        london["id"],
        weekly["id"],
        oldest_in["id"],
    ]

    only = ok(client.get("/api/bias/notes", params={"kind": ["pre_london", "weekly"]}))["items"]
    assert [n["id"] for n in only] == [friday["id"], london["id"], weekly["id"]]

    window = ok(client.get("/api/bias/notes", params={"from": "2026-11-02", "to": THU}))
    assert [n["id"] for n in window["items"]] == [ny["id"], london["id"], weekly["id"]]

    from_only = ok(client.get("/api/bias/notes", params={"from": "2026-11-06"}))["items"]
    assert [n["period_date"] for n in from_only] == ["2026-11-07", "2026-11-06"]

    assert "from" in field_errors(
        client.get("/api/bias/notes", params={"from": "2026-11-06", "to": THU})
    )
    assert "to" in field_errors(client.get("/api/bias/notes", params={"to": "soon"}))


# --- update ---


def test_put_replaces_entries_by_symbol(client: TestClient, session: Session) -> None:
    created = create(
        client,
        entries=[entry("XAUUSD", chart_links=[{"url": SNAP}]), entry("GER40", "bearish")],
    )
    xau_id = created["entries"][0]["id"]  # XAUUSD before GER40 in bias.yaml
    ok(client.patch(f"/api/bias/entries/{xau_id}/result", json={"was_correct": True}))

    updated = ok(
        client.put(
            f"/api/bias/notes/{created['id']}",
            json=note_body(
                entries=[entry("EURUSD", "bearish"), entry("XAUUSD", "neutral", confidence=3)]
            ),
        )
    )
    assert [e["symbol"] for e in updated["entries"]] == ["EURUSD", "XAUUSD"]
    xau = updated["entries"][1]
    assert xau["id"] == xau_id  # updated in place
    assert (xau["direction"], xau["confidence"], xau["chart_links"]) == ("neutral", 3, [])
    assert (xau["was_correct"], xau["was_correct_source"]) == (True, "manual")
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(BiasEntry)) == 2
    assert session.scalar(select(func.count()).select_from(ChartLink)) == 0


def test_put_changes_kind_and_period_and_conflicts(client: TestClient) -> None:
    note = create(client, kind="pre_london")
    other = create(client, kind="weekly", period_date="2026-11-02")
    moved = ok(client.put(f"/api/bias/notes/{note['id']}", json=note_body("monthly", "2026-11-20")))
    assert (moved["kind"], moved["period_date"]) == ("monthly", "2026-11-01")
    clash = client.put(f"/api/bias/notes/{note['id']}", json=note_body("weekly", THU))
    assert clash.status_code == 409
    assert clash.json()["error"]["details"] == {"id": other["id"]}
    same = client.put(f"/api/bias/notes/{other['id']}", json=note_body("weekly", THU))
    assert same.status_code == 200  # its own period is not a clash
    missing = client.put("/api/bias/notes/999", json=note_body())
    assert missing.status_code == 404


def test_put_validation(client: TestClient) -> None:
    note = create(client)
    errors = field_errors(
        client.put(f"/api/bias/notes/{note['id']}", json=note_body(entries=[entry("NAS100")]))
    )
    assert "entries.0.symbol" in errors


# --- delete ---


def test_delete_keeps_audio_file(client: TestClient, data_dir: Path) -> None:
    note = create(client)
    audio = ok(
        client.post(
            f"/api/bias/notes/{note['id']}/audio",
            content=WEBM,
            headers={"Content-Type": "audio/webm"},
        ),
        201,
    )
    assert client.delete(f"/api/bias/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/bias/notes/{note['id']}").status_code == 404
    assert client.get(f"/api/audio/{audio['id']}").status_code == 404
    assert len([p for p in data_dir.rglob("*") if p.is_file()]) == 1
    assert client.delete(f"/api/bias/notes/{note['id']}").status_code == 404


# --- result ---


def test_result_mark_and_clear(client: TestClient) -> None:
    entry_id = create(client)["entries"][0]["id"]
    url = f"/api/bias/entries/{entry_id}/result"
    marked = ok(client.patch(url, json={"was_correct": False}))
    assert (marked["was_correct"], marked["was_correct_source"]) == (False, "manual")
    assert marked["id"] == entry_id
    cleared = ok(client.patch(url, json={"was_correct": None}))
    assert (cleared["was_correct"], cleared["was_correct_source"]) == (None, None)
    assert "was_correct" in field_errors(client.patch(url, json={"was_correct": "true"}))
    assert "was_correct" in field_errors(client.patch(url, json={}))
    missing = client.patch("/api/bias/entries/999/result", json={"was_correct": True})
    assert missing.status_code == 404


# --- audio ---


@pytest.fixture
def data_dir(tmp_path: Path, app: FastAPI, settings: Settings) -> Path:
    custom = settings.model_copy(update={"data_dir": tmp_path.resolve()})
    app.dependency_overrides[get_settings] = lambda: custom
    return tmp_path.resolve()


def test_bias_audio_upload(client: TestClient, session: Session, data_dir: Path) -> None:
    note = create(client)
    response = client.post(
        f"/api/bias/notes/{note['id']}/audio", content=WEBM, headers={"Content-Type": "audio/ogg"}
    )
    audio = ok(response, 201)
    assert (audio["trade_id"], audio["bias_note_id"]) == (None, note["id"])
    assert audio["status"] == "pending"
    assert audio["mime_type"] == "audio/ogg"
    row = session.get(AudioNote, audio["id"])
    assert row is not None
    assert (data_dir / row.file_path).read_bytes() == WEBM
    listed = ok(client.get(f"/api/bias/notes/{note['id']}"))["audio_notes"]
    assert [a["id"] for a in listed] == [audio["id"]]


def test_bias_audio_errors(client: TestClient, data_dir: Path) -> None:
    note = create(client)
    url = f"/api/bias/notes/{note['id']}/audio"
    assert client.post(url, content=WEBM, headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post(url, content=b"", headers={"Content-Type": "audio/webm"}).status_code == 422
    unknown = client.post(
        "/api/bias/notes/999/audio", content=WEBM, headers={"Content-Type": "audio/webm"}
    )
    assert unknown.status_code == 404
    assert [p for p in data_dir.rglob("*") if p.is_file()] == []


# --- alignment through the API (acceptance) ---


def test_alignment_follows_notes(client: TestClient, session: Session, account: Account) -> None:
    london = add_trade(  # 09:30 Brussels, sell
        session,
        account,
        symbol="XAUUSD.r",
        direction="sell",
        open_time=datetime(2026, 11, 5, 8, 30, tzinfo=UTC),
        close_time=datetime(2026, 11, 5, 9, 0, tzinfo=UTC),
    )
    ny = add_trade(  # 14:30 Brussels, buy, still open
        session,
        account,
        symbol="XAUUSD.r",
        direction="buy",
        status="open",
        open_time=datetime(2026, 11, 5, 13, 30, tzinfo=UTC),
        close_time=None,
    )
    pre_london = create(client, kind="pre_london", entries=[entry("XAUUSD", "bearish")])
    pre_ny = create(client, kind="pre_ny", entries=[entry("XAUUSD", "bearish")])
    weekly = create(
        client, kind="weekly", period_date="2026-11-02", entries=[entry("XAUUSD", "bullish")]
    )

    first = trade_detail(client, london.id)
    assert (first["bias_alignment"], first["journal"]["bias_alignment"]) == ("aligned", "aligned")
    assert (first["bias_alignment_weekly"], first["bias_alignment_monthly"]) == (
        "counter",
        "no_bias",
    )
    assert first["bias_note_ids"] == {
        "daily": pre_london["id"],
        "weekly": weekly["id"],
        "monthly": None,
    }
    second = trade_detail(client, ny.id)
    assert (second["bias_alignment"], second["bias_alignment_weekly"]) == ("counter", "aligned")
    assert second["bias_note_ids"]["daily"] == pre_ny["id"]

    rows = {r["id"]: r for r in ok(client.get("/api/trades"))["items"]}
    assert rows[london.id]["bias_alignment"] == "aligned"
    assert rows[ny.id]["bias_alignment_weekly"] == "aligned"

    # Edit: the pre-NY note drops XAUUSD -> the NY trade falls back to pre_london.
    ok(
        client.put(
            f"/api/bias/notes/{pre_ny['id']}", json=note_body(entries=[entry("GER40", "bullish")])
        )
    )
    assert trade_detail(client, ny.id)["bias_note_ids"]["daily"] == pre_london["id"]
    assert trade_detail(client, ny.id)["bias_alignment"] == "counter"

    # Kind change: pre_london -> pre_ny; the London trade loses its daily bias.
    ok(client.put(f"/api/bias/notes/{pre_ny['id']}", json=note_body("monthly", THU)))
    ok(
        client.put(
            f"/api/bias/notes/{pre_london['id']}",
            json=note_body("pre_ny", entries=[entry("XAUUSD", "bullish")]),
        )
    )
    assert trade_detail(client, london.id)["bias_alignment"] == "no_bias"
    assert trade_detail(client, ny.id)["bias_alignment"] == "aligned"

    # Delete the weekly note.
    assert client.delete(f"/api/bias/notes/{weekly['id']}").status_code == 204
    assert trade_detail(client, ny.id)["bias_alignment_weekly"] == "no_bias"


def test_override_wins_and_is_kept(client: TestClient, session: Session, account: Account) -> None:
    trade = add_trade(
        session,
        account,
        open_time=datetime(2026, 11, 5, 8, 30, tzinfo=UTC),
        close_time=datetime(2026, 11, 5, 9, 0, tzinfo=UTC),
        bias_alignment_override="aligned",
        bias_alignment_override_reason="мій вибір",
    )
    create(client, kind="pre_london", entries=[entry("XAUUSD", "bearish")])
    detail = trade_detail(client, trade.id)
    assert detail["bias_alignment"] == "aligned"
    assert detail["journal"]["bias_alignment"] == "aligned"
    session.expire_all()
    stored = session.get(Trade, trade.id)
    assert stored is not None
    assert stored.bias_alignment == "counter"
    assert stored.bias_alignment_override == "aligned"


# --- broken config ---


@pytest.fixture
def broken_bias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    (config / "bias.yaml").write_text("symbols: []\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield
    reload_config()


def test_broken_bias_yaml_saves_nothing(
    client: TestClient, session: Session, broken_bias: None
) -> None:
    response = client.post("/api/bias/notes", json=note_body())
    assert response.status_code == 500
    error = response.json()["error"]
    assert (error["code"], error["details"]["file"]) == ("config_error", "bias.yaml")
    assert session.scalar(select(func.count()).select_from(BiasEntry)) == 0
    assert client.get("/api/bias/status").status_code == 500


def test_trade_detail_survives_broken_bias_yaml(
    client: TestClient, session: Session, account: Account, broken_bias: None
) -> None:
    trade = add_trade(session, account)
    assert trade_detail(client, trade.id)["bias_note_ids"] == {
        "daily": None,
        "weekly": None,
        "monthly": None,
    }


# --- status ---


def status_at(app: FastAPI, client: TestClient, moment: datetime) -> dict[str, Any]:
    set_now(app, moment)
    return ok(client.get("/api/bias/status"))


def test_status_pre_ny_reminder_window(app: FastAPI, client: TestClient) -> None:
    at_1231 = status_at(app, client, datetime(2026, 11, 5, 11, 31, tzinfo=UTC))  # 12:31 CET
    assert (at_1231["date"], at_1231["weekday"]) == (THU, True)
    assert at_1231["now"] == "2026-11-05T11:31:00Z"
    assert at_1231["sessions"]["pre_ny"] == {
        "note_id": None,
        "missing": True,
        "remind": True,
        "from": "12:30",
        "until": "16:00",
    }
    assert at_1231["sessions"]["pre_london"]["remind"] is False  # window ended at 11:00
    assert at_1231["sessions"]["pre_london"]["missing"] is True

    at_1229 = status_at(app, client, datetime(2026, 11, 5, 11, 29, tzinfo=UTC))
    assert at_1229["sessions"]["pre_ny"]["remind"] is False
    assert at_1229["sessions"]["pre_ny"]["missing"] is True

    saturday = status_at(app, client, datetime(2026, 11, 7, 11, 31, tzinfo=UTC))
    assert saturday["weekday"] is False
    assert saturday["sessions"]["pre_ny"]["remind"] is False


def test_status_summer_time_and_until(app: FastAPI, client: TestClient) -> None:
    # 07:45 CEST = 05:45 UTC: pre_london starts.
    assert status_at(app, client, datetime(2026, 7, 7, 5, 45, tzinfo=UTC))["sessions"][
        "pre_london"
    ]["remind"]
    assert not status_at(app, client, datetime(2026, 7, 7, 5, 44, tzinfo=UTC))["sessions"][
        "pre_london"
    ]["remind"]
    # 16:00 CEST: pre_ny window is over (until is exclusive).
    assert not status_at(app, client, datetime(2026, 7, 7, 14, 0, tzinfo=UTC))["sessions"][
        "pre_ny"
    ]["remind"]


def test_status_with_notes(app: FastAPI, client: TestClient) -> None:
    pre_ny = create(client, kind="pre_ny", entries=[])
    weekly = create(client, kind="weekly", period_date="2026-11-02")
    monthly = create(client, kind="monthly", period_date="2026-11-01")
    create(client, kind="pre_london", period_date="2026-11-04")  # yesterday: not today's
    data = status_at(app, client, datetime(2026, 11, 5, 11, 31, tzinfo=UTC))
    assert data["sessions"]["pre_ny"]["note_id"] == pre_ny["id"]
    assert data["sessions"]["pre_ny"]["missing"] is False
    assert data["sessions"]["pre_ny"]["remind"] is False
    assert data["sessions"]["pre_london"]["note_id"] is None
    assert data["weekly"] == {"note_id": weekly["id"]}
    assert data["monthly"] == {"note_id": monthly["id"]}


def test_concurrent_insert_is_409(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    first = create(client)
    monkeypatch.setattr(bias_notes, "_check_free", lambda *args: None)  # lost the race
    response = client.post("/api/bias/notes", json=note_body())
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"id": first["id"]}
