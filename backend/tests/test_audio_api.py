"""Voice-note API (docs/api.md "M3 / Voice notes"): upload, read, replay, retry."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import make_session_factory
from app.domain.audio import MAX_AUDIO_BYTES
from app.models import Account, AudioNote, Trade
from app.models.enums import TradeStatus
from tests.test_trades_api import add_account, add_trade

WEBM = b"\x1aE\xdf\xa3fake-webm-bytes"


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def data_dir(tmp_path: Path, app: FastAPI, settings: Settings) -> Path:
    custom = settings.model_copy(update={"data_dir": tmp_path.resolve()})
    app.dependency_overrides[get_settings] = lambda: custom
    return tmp_path.resolve()


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
def trade(session: Session, account: Account) -> Trade:
    return add_trade(session, account)


def upload(
    client: TestClient, trade_id: int, body: bytes = WEBM, content_type: str = "audio/webm"
) -> Any:
    return client.post(
        f"/api/trades/{trade_id}/audio", content=body, headers={"Content-Type": content_type}
    )


def add_note(session: Session, trade: Trade, **kw: Any) -> AudioNote:
    fields: dict[str, Any] = {
        "trade_id": trade.id,
        "file_path": "audio/2026/11/x.webm",
        "mime_type": "audio/webm",
    }
    note = AudioNote(**(fields | kw))
    session.add(note)
    session.commit()
    return note


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


# --- upload --------------------------------------------------------------------------------


def test_upload_writes_file_and_pending_row(
    client: TestClient, data_dir: Path, trade: Trade, session: Session
) -> None:
    response = upload(client, trade.id, content_type="audio/webm;codecs=opus")

    assert response.status_code == 201
    body = response.json()
    assert body["trade_id"] == trade.id
    assert body["bias_note_id"] is None
    assert body["status"] == "pending"
    assert body["progress"] is None
    assert body["duration_seconds"] is None
    assert body["mime_type"] == "audio/webm"
    assert body["transcript"] is None
    assert body["error_code"] is None
    assert body["transcribed_at"] is None
    assert body["created_at"].endswith("Z")
    assert body["file_url"] == f"/api/audio/{body['id']}/file"
    note = session.get(AudioNote, body["id"])
    assert note is not None
    assert note.file_path.startswith("audio/")
    assert note.file_path.endswith(".webm")
    _, year, month, _ = note.file_path.split("/")
    assert len(year) == 4
    assert len(month) == 2
    assert (data_dir / note.file_path).read_bytes() == WEBM
    assert _files(data_dir) == [data_dir / note.file_path]  # no .part left behind


@pytest.mark.parametrize(
    ("content_type", "ext"),
    [("audio/ogg", "ogg"), ("audio/mp4", "m4a"), ("audio/mpeg", "mp3"), ("audio/wav", "wav")],
)
def test_upload_allowed_types(
    client: TestClient, data_dir: Path, trade: Trade, content_type: str, ext: str
) -> None:
    response = upload(client, trade.id, content_type=content_type)
    assert response.status_code == 201
    assert response.json()["mime_type"] == content_type
    assert [p.suffix for p in _files(data_dir)] == [f".{ext}"]


@pytest.mark.parametrize("content_type", ["video/webm", "application/octet-stream", "text/plain"])
def test_upload_rejects_other_types(
    client: TestClient, data_dir: Path, trade: Trade, content_type: str
) -> None:
    response = upload(client, trade.id, content_type=content_type)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert _files(data_dir) == []


def test_upload_without_content_type(client: TestClient, data_dir: Path, trade: Trade) -> None:
    response = client.post(f"/api/trades/{trade.id}/audio", content=WEBM)
    assert response.status_code == 415


def test_upload_empty_body(client: TestClient, data_dir: Path, trade: Trade) -> None:
    response = upload(client, trade.id, body=b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _files(data_dir) == []


def test_upload_empty_streamed_body(client: TestClient, data_dir: Path, trade: Trade) -> None:
    def chunks() -> Iterator[bytes]:
        yield b""

    response = client.post(
        f"/api/trades/{trade.id}/audio", content=chunks(), headers={"Content-Type": "audio/ogg"}
    )
    assert response.status_code == 422
    assert _files(data_dir) == []


def test_upload_too_large_by_header(client: TestClient, data_dir: Path, trade: Trade) -> None:
    response = upload(client, trade.id, body=b"x" * (MAX_AUDIO_BYTES + 1))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "audio_too_large"
    assert _files(data_dir) == []


def test_upload_too_large_streamed_stops_reading(
    client: TestClient, data_dir: Path, trade: Trade
) -> None:
    """Chunked upload (no Content-Length): the limit is enforced while reading."""
    chunk = b"x" * (1024 * 1024)

    def chunks() -> Iterator[bytes]:
        for _ in range(40):
            yield chunk

    response = client.post(
        f"/api/trades/{trade.id}/audio", content=chunks(), headers={"Content-Type": "audio/webm"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "audio_too_large"
    assert _files(data_dir) == []


def test_upload_exactly_at_limit_is_accepted(
    client: TestClient, data_dir: Path, trade: Trade
) -> None:
    response = upload(client, trade.id, body=b"x" * MAX_AUDIO_BYTES)
    assert response.status_code == 201
    assert _files(data_dir)[0].stat().st_size == MAX_AUDIO_BYTES


def test_upload_unknown_trade(client: TestClient, data_dir: Path) -> None:
    response = upload(client, 999)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert _files(data_dir) == []


def test_upload_open_trade(
    client: TestClient, data_dir: Path, session: Session, account: Account
) -> None:
    open_trade = add_trade(
        session, account, status=TradeStatus.OPEN.value, close_time=None, exit_price=None
    )
    response = upload(client, open_trade.id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "trade_open"
    assert _files(data_dir) == []


@pytest.mark.parametrize("status", ["needs_sl", "needs_description", "draft", "complete"])
def test_upload_any_closed_status(
    client: TestClient, data_dir: Path, session: Session, account: Account, status: str
) -> None:
    closed = add_trade(session, account, status=status)
    assert upload(client, closed.id).status_code == 201


# --- read / file / retry ---------------------------------------------------------------------


def test_get_audio(client: TestClient, session: Session, trade: Trade) -> None:
    note = add_note(
        session,
        trade,
        transcription_status="processing",
        progress=Decimal("0.425"),
        duration_seconds=Decimal("118.4"),
    )
    body = client.get(f"/api/audio/{note.id}").json()
    assert body["status"] == "processing"
    assert body["progress"] == 0.425
    assert body["duration_seconds"] == "118.400"


def test_get_audio_unknown(client: TestClient) -> None:
    response = client.get("/api/audio/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_file_replays_bytes(client: TestClient, data_dir: Path, trade: Trade) -> None:
    note_id = upload(client, trade.id, content_type="audio/ogg;codecs=opus").json()["id"]
    response = client.get(f"/api/audio/{note_id}/file")
    assert response.status_code == 200
    assert response.content == WEBM
    assert response.headers["content-type"] == "audio/ogg"


def test_get_file_missing(
    client: TestClient, data_dir: Path, session: Session, trade: Trade
) -> None:
    note = add_note(session, trade)
    response = client.get(f"/api/audio/{note.id}/file")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "audio_missing"


@pytest.mark.parametrize("stored", ["../secret.txt", "audio/../../secret.txt", "secret.txt"])
def test_get_file_path_traversal_is_refused(
    client: TestClient,
    app: FastAPI,
    settings: Settings,
    tmp_path: Path,
    session: Session,
    trade: Trade,
    stored: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stored paths that leave DATA_DIR/audio are never served, even if the file exists."""
    data = (tmp_path / "data").resolve()
    data.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (data / "secret.txt").write_text("secret", encoding="utf-8")
    custom = settings.model_copy(update={"data_dir": data})
    app.dependency_overrides[get_settings] = lambda: custom
    note = add_note(session, trade, file_path=stored)
    response = client.get(f"/api/audio/{note.id}/file")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "audio_missing"
    assert "secret" not in response.text
    assert "outside DATA_DIR/audio" in caplog.text


def test_retry_failed_note(client: TestClient, session: Session, trade: Trade) -> None:
    note = add_note(
        session,
        trade,
        transcription_status="failed",
        error_code="audio_unreadable",
        transcription_error="InvalidDataError: boom",
        transcript="partial",
    )
    response = client.post(f"/api/audio/{note.id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["error_code"] is None
    assert body["progress"] is None
    assert body["transcript"] is None
    session.expire_all()
    stored = session.get(AudioNote, note.id)
    assert stored is not None
    assert stored.transcription_error is None


@pytest.mark.parametrize("status", ["pending", "processing", "done"])
def test_retry_only_from_failed(
    client: TestClient, session: Session, trade: Trade, status: str
) -> None:
    note = add_note(session, trade, transcription_status=status)
    response = client.post(f"/api/audio/{note.id}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "audio_not_failed"


def test_retry_unknown(client: TestClient) -> None:
    assert client.post("/api/audio/999/retry").status_code == 404


# --- TradeDetail.audio_notes -----------------------------------------------------------------


def test_trade_detail_lists_audio_notes_oldest_first(
    client: TestClient, data_dir: Path, trade: Trade
) -> None:
    first = upload(client, trade.id).json()["id"]
    second = upload(client, trade.id, content_type="audio/ogg").json()["id"]
    detail = client.get(f"/api/trades/{trade.id}").json()
    assert [n["id"] for n in detail["audio_notes"]] == [first, second]
    assert detail["audio_notes"][1]["mime_type"] == "audio/ogg"


def test_trade_detail_without_audio(client: TestClient, trade: Trade) -> None:
    assert client.get(f"/api/trades/{trade.id}").json()["audio_notes"] == []


# --- DB constraints from the migration -------------------------------------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"progress": Decimal("1.5")},
        {"progress": Decimal("-0.1")},
        {"transcription_status": "failed", "error_code": "nope"},
        {"transcription_status": "done", "error_code": "timeout"},
    ],
)
def test_audio_note_constraints(session: Session, trade: Trade, values: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        add_note(session, trade, **values)
    session.rollback()


def test_pending_claim_index_exists(session: Session) -> None:
    names = session.scalars(
        select(text("indexname"))
        .select_from(text("pg_indexes"))
        .where(text("tablename = 'audio_notes'"))
    ).all()
    assert "ix_audio_notes_pending_created_at" in names
