"""M8-02: describe an OPEN trade while the position runs, complete it after the close.

The open position already gets its trade row on the first sync (account + MT5 position_id);
the closed trade continues that row. Sync never writes journal fields or links.
"""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api.ai import get_model_client, get_usage_log
from app.config_files import get_journal_fields, get_rules
from app.config_files.rules import RulesConfig
from app.db import make_session_factory
from app.domain.trade_builder import next_status
from app.models import Account, Trade
from app.models.enums import TradeStatus
from app.mt5.fixture import FixtureMt5Source
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, reply
from tests.test_exit_reason_sync import BASE, EURUSD
from tests.test_sync import WEEK_LOGIN, add_account, run, trades_by_pid

PID = 4000001
OPENED = BASE  # server time 2026-10-20 09:00 = 06:00 UTC
SERVER_OFFSET_S = 3 * 3600
# Each sync runs a few minutes after the deals of its stage (the history window starts at
# the last sync minus the overlap, so the close must be newer than the first sync).
SYNC_AT = {"open": 300, "partial": 900, "closed": 1500, "closed_tp": 1500}
BEFORE_1 = "https://www.tradingview.com/x/AbCd1234/"
BEFORE_2 = "https://www.tradingview.com/x/EfGh5678/"
AFTER_1 = "https://www.tradingview.com/x/IjKl9012/"
# Pre-entry values only (phase "before" in config/journal_fields.yaml).
PRE_ENTRY = {
    "setup_context": "yes",
    "poi_type": "fvg_h1",
    "fvg_kind": "fractal_updating",
    "entry_model": "ifvg_m5",
    "emotion_before": "calm",
    "quality_rating": 4,
}
AFTER_KEYS = {"exit_reason", "followed_plan", "emotion_after", "mistakes", "lesson"}


# --- fixture: one EURUSD buy, 1 lot, open -> half closed -> fully closed --------------------


def _deal(ticket: int, time: int, entry: int, price: str, volume: str) -> dict[str, Any]:
    return {
        "ticket": ticket,
        "order": ticket,
        "position_id": PID,
        "time": time,
        "time_msc": time * 1000,
        "type": 0 if entry == 0 else 1,
        "entry": entry,
        "reason": 0,
        "volume": volume,
        "price": price,
        "profit": "0" if entry == 0 else "150",
        "commission": "0",
        "swap": "0",
        "fee": "0",
        "symbol": "EURUSD",
        "sl": "1.162",
        "tp": "1.17",
    }


def _position(volume: str) -> dict[str, Any]:
    return {
        "ticket": PID,
        "identifier": PID,
        "time": OPENED,
        "time_msc": OPENED * 1000,
        "type": 0,
        "volume": volume,
        "price_open": "1.165",
        "sl": "1.162",
        "tp": "1.17",
        "price_current": "1.166",
        "profit": "100",
        "swap": "0",
        "symbol": "EURUSD",
    }


def mt5_data(stage: str) -> dict[str, Any]:
    """`open`, `partial` (0.5 closed, 0.5 still open), `closed` (manual) or `closed_tp`
    (the last 0.5 hits the TP: MT5 reason 5, so the sync prefills exit_reason tp)."""
    deals = [
        _deal(1, OPENED - 86400, 0, "0", "0")
        | {"type": 2, "profit": "100000", "symbol": "", "position_id": 0},
        _deal(PID * 10, OPENED, 0, "1.165", "1"),
    ]
    positions = [_position("1")]
    if stage in ("partial", "closed", "closed_tp"):
        deals.append(_deal(PID * 10 + 1, OPENED + 600, 1, "1.168", "0.5"))
        positions = [_position("0.5")]
    if stage == "closed":
        deals.append(_deal(PID * 10 + 2, OPENED + 1200, 1, "1.168", "0.5"))
        positions = []
    if stage == "closed_tp":
        deals.append(_deal(PID * 10 + 2, OPENED + 1200, 1, "1.17", "0.5") | {"reason": 5})
        positions = []
    return {
        "format": 1,
        "account": {
            "login": WEEK_LOGIN,
            "server": "FundedNext-Server",
            "balance": "100000",
            "equity": "100000",
            "currency": "USD",
        },
        "ticks": {"EURUSD": OPENED + SYNC_AT[stage]},
        "symbols": [deepcopy(EURUSD)],
        "deals": deals,
        "orders": [],
        "positions": positions,
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


@pytest.fixture
def account(session: Session) -> Account:
    return add_account(session, WEEK_LOGIN)


def sync(session: Session, account: Account, rules: RulesConfig, stage: str) -> Trade:
    now = datetime.fromtimestamp(OPENED - SERVER_OFFSET_S, UTC) + timedelta(seconds=SYNC_AT[stage])
    session.expire_all()  # the worker syncs in a fresh session: see the API's writes
    log = run(session, account, FixtureMt5Source(mt5_data(stage)), rules, now)
    assert log.ok is True, log.error_message
    trades = trades_by_pid(session, account.id)
    assert list(trades) == [PID]  # one record, never a duplicate
    return trades[PID]


def journal_body(
    fields: dict[str, Any] | None = None,
    links: list[tuple[str, str]] | None = None,
    *,
    raw_text: str | None = "Вхід від FVG M5, спокійно.",
    complete: bool = False,
    form_open: bool | None = None,
) -> dict[str, Any]:
    extra = {} if form_open is None else {"form_open": form_open}
    return extra | {
        "fields": PRE_ENTRY if fields is None else fields,
        "chart_links": [
            {"url": url, "kind": kind}
            for url, kind in (
                links if links is not None else [(BEFORE_1, "before"), (BEFORE_2, "before")]
            )
        ],
        "raw_text": raw_text,
        "ai_filled_fields": [],
        "complete": complete,
    }


def put(client: TestClient, trade: Trade, body: dict[str, Any]) -> Any:
    return client.put(f"/api/trades/{trade.id}/journal", json=body)


def ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def counts(client: TestClient) -> dict[str, Any]:
    return ok(client.get("/api/inbox/counts"))


def describe_open(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> Trade:
    trade = sync(session, account, rules, "open")
    ok(put(client, trade, journal_body()))
    session.refresh(trade)
    return trade


# --- open record -----------------------------------------------------------------------------


def test_sync_creates_the_open_record_outside_the_inbox(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules, "open")

    assert (trade.status, trade.close_time, trade.described_at) == ("open", None, None)
    assert counts(client)["needs_description"] == 0


def test_open_trade_can_be_described_and_stays_open(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules, "open")

    data = ok(put(client, trade, journal_body()))

    assert data["status"] == "open"
    assert data["journal"]["entry_model"] == "ifvg_m5"
    assert data["raw_text"] == "Вхід від FVG M5, спокійно."
    assert [(c["url"], c["kind"]) for c in data["chart_links"]] == [
        (BEFORE_1, "before"),
        (BEFORE_2, "before"),
    ]
    session.expire_all()
    stored = session.get(Trade, trade.id)
    assert stored is not None
    assert stored.described_at is not None
    assert counts(client)["draft"] == 0  # an open trade is never in the inbox


def test_open_trade_cannot_be_completed(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules, "open")

    response = put(client, trade, journal_body(complete=True))

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "open_trade_complete"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("exit_reason", "tp"),
        ("followed_plan", True),
        ("emotion_after", "calm"),
        ("mistakes", "рано вийшов"),
        ("lesson", "терпіння"),
    ],
)
def test_after_trade_fields_are_rejected_while_open(
    client: TestClient,
    session: Session,
    account: Account,
    rules: RulesConfig,
    key: str,
    value: Any,
) -> None:
    trade = sync(session, account, rules, "open")

    response = put(client, trade, journal_body(PRE_ENTRY | {key: value}))

    assert response.status_code == 422, response.text
    assert f"fields.{key}" in response.json()["error"]["details"]["fields"]


def test_after_trade_link_is_rejected_while_open(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules, "open")

    response = put(client, trade, journal_body(links=[(BEFORE_1, "before"), (AFTER_1, "after")]))

    assert response.status_code == 422, response.text
    assert "chart_links.1.kind" in response.json()["error"]["details"]["fields"]


def test_open_trade_without_sl_can_be_described(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules, "open")
    trade.initial_sl, trade.initial_sl_source = None, None
    session.commit()

    assert ok(put(client, trade, journal_body()))["status"] == "open"


# --- close via sync --------------------------------------------------------------------------


def test_close_continues_the_same_record_and_keeps_the_text(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)
    trade_id, described_at = trade.id, trade.described_at

    closed = sync(session, account, rules, "closed")

    assert closed.id == trade_id
    assert closed.close_time is not None
    assert closed.status == TradeStatus.DRAFT.value
    assert closed.described_at == described_at
    assert (closed.entry_model, closed.emotion_before, closed.quality_rating) == (
        "ifvg_m5",
        "calm",
        4,
    )
    assert closed.raw_text == "Вхід від FVG M5, спокійно."
    detail = ok(client.get(f"/api/trades/{trade_id}"))
    assert [c["url"] for c in detail["chart_links"]] == [BEFORE_1, BEFORE_2]
    # What is left after the close: the exit side (exit reason, emotion after, ...).
    assert {"exit_reason", "emotion_after", "followed_plan"} <= set(detail["missing_required"])
    assert "entry_model" not in detail["missing_required"]
    assert counts(client)["draft"] == 1
    assert counts(client)["needs_description"] == 0


def test_undescribed_open_trade_closes_into_needs_description(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    sync(session, account, rules, "open")

    closed = sync(session, account, rules, "closed")

    assert closed.status == TradeStatus.NEEDS_DESCRIPTION.value
    assert counts(client)["needs_description"] == 1


def test_partial_close_keeps_one_open_record_and_the_text(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)

    partial = sync(session, account, rules, "partial")

    assert partial.id == trade.id
    assert (partial.status, partial.close_time) == ("open", None)
    assert partial.entry_model == "ifvg_m5"
    assert len(partial.exit_deals) == 1

    closed = sync(session, account, rules, "closed")
    assert closed.id == trade.id
    assert closed.status == TradeStatus.DRAFT.value
    assert len(closed.exit_deals) == 2


def test_resync_after_close_never_overwrites_the_journal(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)
    sync(session, account, rules, "closed")
    after = {"exit_reason": "tp", "emotion_after": "calm", "followed_plan": True}
    links = [(BEFORE_1, "before"), (BEFORE_2, "before"), (AFTER_1, "after")]
    ok(put(client, trade, journal_body(PRE_ENTRY | after, links, complete=True)))

    again = sync(session, account, rules, "closed")

    assert again.status == TradeStatus.COMPLETE.value
    assert (again.exit_reason, again.exit_reason_source) == ("tp", "owner")
    assert (again.emotion_after, again.followed_plan) == ("calm", True)
    detail = ok(client.get(f"/api/trades/{trade.id}"))
    assert [(c["url"], c["kind"]) for c in detail["chart_links"]] == [(u, k) for u, k in links]


def test_described_open_trade_closed_without_sl_returns_to_draft_after_sl(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)
    trade.status = TradeStatus.NEEDS_SL.value  # as if MT5 had no SL anywhere
    trade.close_time, trade.initial_sl, trade.initial_sl_source = trade.open_time, None, None
    trade.exit_price = trade.entry_price
    session.commit()

    response = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "1.162"})

    assert ok(response)["status"] == TradeStatus.DRAFT.value


@pytest.mark.parametrize(
    ("current", "closed", "has_sl", "described", "expected"),
    [
        (None, False, True, False, TradeStatus.OPEN),
        ("open", False, True, True, TradeStatus.OPEN),
        ("open", True, True, False, TradeStatus.NEEDS_DESCRIPTION),
        ("open", True, True, True, TradeStatus.DRAFT),
        ("open", True, False, True, TradeStatus.NEEDS_SL),
        ("needs_sl", True, True, True, TradeStatus.DRAFT),
        ("needs_sl", True, True, False, TradeStatus.NEEDS_DESCRIPTION),
        ("complete", True, True, True, TradeStatus.COMPLETE),
    ],
)
def test_next_status_with_a_description_made_while_open(
    current: str | None, closed: bool, has_sl: bool, described: bool, expected: TradeStatus
) -> None:
    assert next_status(current, is_closed=closed, has_initial_sl=has_sl, described=described) is (
        expected
    )


# --- AI, audio, config -----------------------------------------------------------------------


def test_ai_on_an_open_trade_offers_and_returns_only_pre_entry_fields(
    app: FastAPI,
    client: TestClient,
    session: Session,
    account: Account,
    rules: RulesConfig,
    tmp_path: Path,
) -> None:
    trade = sync(session, account, rules, "open")
    text_in = "Вхід по IFVG M5, закрив по тейку."
    model = FakeClient(
        [
            reply(
                {
                    "entry_model": {"value": "ifvg_m5", "evidence": "Вхід по IFVG M5"},
                    "exit_reason": {"value": "tp", "evidence": "закрив по тейку"},
                }
            )
        ]
    )
    app.dependency_overrides[get_model_client] = lambda: model
    app.dependency_overrides[get_usage_log] = lambda: UsageLog(tmp_path / "ai_usage.jsonl")

    data = ok(client.post(f"/api/trades/{trade.id}/extract", json={"text": text_in}))

    assert data["fields"] == {"entry_model": "ifvg_m5"}
    assert data["ai_filled_fields"] == ["entry_model"]
    offered = set(
        model.requests[0].schema["properties"]["fields"]["items"]["properties"]["key"]["enum"]
    )
    assert "entry_model" in offered
    assert not offered & AFTER_KEYS
    assert not set(data["missing_required"]) & AFTER_KEYS


def test_audio_upload_is_accepted_for_an_open_trade(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    from app.services.audio_notes import check_trade_accepts_audio

    trade = sync(session, account, rules, "open")

    check_trade_accepts_audio(session, trade.id)  # no 409 any more


def test_journal_fields_mark_the_after_trade_phase(client: TestClient) -> None:
    fields = ok(client.get("/api/journal-fields"))["fields"]
    phases = {f["key"]: f["phase"] for f in fields}

    assert {k for k, p in phases.items() if p == "after"} == AFTER_KEYS
    assert phases["entry_model"] == phases["chart_links"] == "before"
    assert get_journal_fields().for_open_trade().get("exit_reason") is None


# --- review fix: a form opened while the trade was open, saved after the close ---------------


def test_open_form_saved_after_the_close_keeps_the_mt5_exit_reason(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)
    closed = sync(session, account, rules, "closed_tp")
    assert (closed.exit_reason, closed.exit_reason_source) == ("tp", "mt5_reason")

    data = ok(put(client, trade, journal_body(raw_text="ще трохи тексту", form_open=True)))

    assert data["status"] == TradeStatus.DRAFT.value
    assert data["raw_text"] == "ще трохи тексту"
    session.expire_all()
    stored = session.get(Trade, trade.id)
    assert stored is not None
    assert (stored.exit_reason, stored.exit_reason_source) == ("tp", "mt5_reason")


def test_open_form_saved_after_the_close_keeps_after_trade_values_and_links(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)
    sync(session, account, rules, "closed")
    after = {"emotion_after": "fomo", "emotion_after_text": "поспішив", "lesson": "терпіння"}
    links = [(BEFORE_1, "before"), (AFTER_1, "after")]
    ok(put(client, trade, journal_body(PRE_ENTRY | after, links)))  # e.g. another tab

    # The stale open form: pre-entry values only, its own before links.
    stale = journal_body(
        PRE_ENTRY | {"entry_model": "qm_m5"}, [(BEFORE_2, "before")], form_open=True
    )
    data = ok(put(client, trade, stale))

    assert data["journal"]["entry_model"] == "qm_m5"
    assert data["journal"]["emotion_after"] == "fomo"
    assert data["journal"]["emotion_after_text"] == "поспішив"
    assert data["journal"]["lesson"] == "терпіння"
    assert [(c["url"], c["kind"]) for c in data["chart_links"]] == [
        (BEFORE_2, "before"),
        (AFTER_1, "after"),
    ]


def test_without_the_flag_a_closed_trade_save_is_a_full_replacement(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = describe_open(client, session, account, rules)
    sync(session, account, rules, "closed_tp")

    ok(put(client, trade, journal_body()))

    session.expire_all()
    stored = session.get(Trade, trade.id)
    assert stored is not None
    assert (stored.exit_reason, stored.exit_reason_source) == (None, "owner")


def test_after_trade_note_alone_is_rejected_while_open(
    client: TestClient, session: Session, account: Account, rules: RulesConfig
) -> None:
    trade = sync(session, account, rules, "open")

    response = put(client, trade, journal_body(PRE_ENTRY | {"emotion_after_text": "поспішив"}))

    assert response.status_code == 422, response.text
    assert "fields.emotion_after_text" in response.json()["error"]["details"]["fields"]
