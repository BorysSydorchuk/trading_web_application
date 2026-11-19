"""M8-04..M8-08 journal API: new fields, `show_if` clearing, legacy fields, «Інше» text,
violations from config/violations.yaml and required_since for the new required fields
(docs/api.md "Journal taxonomy batch")."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.config_files import get_journal_fields, reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.domain.journal import journal_keys, requirement_keys
from app.models import Account, ChartLink, RuleViolation, Trade
from tests.test_trades_api import add_account, add_trade, add_violation

SNAP = "https://www.tradingview.com/x/AbCd1234/"
NEW_REQUIRED_KEYS = {"h1_context", "h4_context", "poi_types", "fvg_types_h1", "fvg_types_h4"}
# «Інше» texts are stamped by the migration too (review 2026-11-19).
NEW_TEXT_KEYS = {
    "h1_context_other",
    "h4_context_other",
    "poi_types_other",
    "fvg_types_h1_other",
    "fvg_types_h4_other",
    "entry_model_other",
}

BASE_FIELDS: dict[str, Any] = {
    "h1_context": "flow",
    "h4_context": "reversal",
    "poi_types": ["fractal_h1", "fractal_h4"],
    "entry_model": "ifvg_m5",
    "exit_reason": "tp",
    "followed_plan": True,
    "emotion_before": "calm",
    "emotion_after": "confidence",
    "quality_rating": 4,
}
BEFORE_LINK = [{"url": SNAP, "kind": "before"}]


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
def trade(session: Session, account: Account) -> Trade:
    return add_trade(session, account)


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for path in (REPO_ROOT / "config").glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    yield tmp_path
    reload_config()


def body(fields: dict[str, Any], *, complete: bool = False, links: bool = False) -> dict[str, Any]:
    return {
        "fields": fields,
        "chart_links": BEFORE_LINK if links else [],
        "raw_text": None,
        "ai_filled_fields": [],
        "complete": complete,
    }


def put(client: TestClient, trade_id: int, data: dict[str, Any]) -> Any:
    return client.put(f"/api/trades/{trade_id}/journal", json=data)


def ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def detail(client: TestClient, trade_id: int) -> dict[str, Any]:
    return ok(client.get(f"/api/trades/{trade_id}"))


def stored(session: Session, trade_id: int) -> Trade:
    session.expire_all()
    found = session.get(Trade, trade_id)
    assert found is not None
    return found


def column(session: Session, trade_id: int, name: str) -> Any:
    session.expire_all()
    return session.execute(
        text(f"SELECT {name} FROM trades WHERE id = :id"),  # noqa: S608 - test constant
        {"id": trade_id},
    ).scalar_one()


def incomplete_missing(response: Any) -> list[str]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "journal_incomplete"
    missing: list[str] = error["details"]["missing"]
    return missing


# --- roundtrip of the new fields ---


def test_new_fields_roundtrip_through_put_and_get(
    client: TestClient, session: Session, trade: Trade
) -> None:
    fields = {
        "h1_context": "flow",
        "h4_context": "other",
        "h4_context_other": "range з відкатом",
        "poi_types": ["fvg_h1", "other"],
        "poi_types_other": "OB H4",
        "fvg_types_h1": ["fractal_updating", "post_manipulation"],
        "entry_model": "other",
        "entry_model_other": "власна модель",
    }

    put_data = ok(put(client, trade.id, body(fields)))
    get_data = detail(client, trade.id)

    for data in (put_data, get_data):
        for key, value in fields.items():
            assert data["journal"][key] == value, key
        assert data["journal"]["fvg_types_h4"] is None
        assert data["journal"]["h1_context_other"] is None
    assert column(session, trade.id, "poi_types") == ["fvg_h1", "other"]
    assert column(session, trade.id, "fvg_types_h1") == ["fractal_updating", "post_manipulation"]
    assert column(session, trade.id, "poi_types_other") == "OB H4"
    assert column(session, trade.id, "entry_model_other") == "власна модель"


def test_multi_values_are_stored_in_a_varchar_array_column(
    client: TestClient, session: Session, trade: Trade
) -> None:
    ok(put(client, trade.id, body({"poi_types": ["fvg_h4"]})))

    kind = session.execute(
        text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'trades'::regclass AND attname = 'poi_types'"
        )
    ).scalar_one()

    assert kind == "character varying(50)[]"


def test_empty_multi_list_is_stored_as_null_not_empty_array(
    client: TestClient, session: Session, trade: Trade
) -> None:
    ok(put(client, trade.id, body({"poi_types": ["fvg_h4"]})))

    data = ok(put(client, trade.id, body({"poi_types": []})))

    assert column(session, trade.id, "poi_types") is None
    assert data["journal"]["poi_types"] is None


def test_unknown_multi_option_is_a_validation_error(client: TestClient, trade: Trade) -> None:
    response = put(client, trade.id, body({"poi_types": ["fvg_h4", "nope"]}))

    assert response.status_code == 422
    errors = response.json()["error"]["details"]["fields"]
    assert "unknown option" in errors["fields.poi_types"]


def test_other_text_is_cleared_when_other_is_not_chosen(
    client: TestClient, session: Session, trade: Trade
) -> None:
    fields = {
        "poi_types": ["fvg_h4"],
        "poi_types_other": "OB",
        "entry_model": "ifvg_m5",
        "entry_model_other": "x",
        "h1_context": "flow",
        "h1_context_other": "y",
    }

    ok(put(client, trade.id, body(fields)))

    t = stored(session, trade.id)
    assert (t.poi_types_other, t.entry_model_other, t.h1_context_other) == (None, None, None)


# --- show_if: hidden fields are cleared and reported ---


def test_hidden_field_is_cleared_and_reported(
    client: TestClient, session: Session, trade: Trade
) -> None:
    fields = {
        "poi_types": ["fractal_h1"],
        "fvg_types_h1": ["post_manipulation"],
        "fvg_types_h1_other": "щось",
    }

    data = ok(put(client, trade.id, body(fields)))

    assert "fvg_types_h1" in data["cleared_hidden"]
    assert "fvg_types_h4" not in data["cleared_hidden"]
    assert data["journal"]["fvg_types_h1"] is None
    assert column(session, trade.id, "fvg_types_h1") is None
    assert column(session, trade.id, "fvg_types_h1_other") is None


def test_shown_field_is_kept_and_nothing_is_reported(
    client: TestClient, session: Session, trade: Trade
) -> None:
    fields = {"poi_types": ["fvg_h1"], "fvg_types_h1": ["post_manipulation"]}

    data = ok(put(client, trade.id, body(fields)))

    assert data["cleared_hidden"] == []
    assert column(session, trade.id, "fvg_types_h1") == ["post_manipulation"]


def test_hidden_field_that_was_not_sent_is_not_reported(client: TestClient, trade: Trade) -> None:
    data = ok(put(client, trade.id, body({"poi_types": ["fractal_h1"]})))

    assert data["cleared_hidden"] == []


# --- complete: required, hidden, «Інше» ---


def test_complete_without_hidden_fvg_types_is_saved(client: TestClient, trade: Trade) -> None:
    data = ok(put(client, trade.id, body(BASE_FIELDS, complete=True, links=True)))

    assert data["status"] == "complete"
    assert data["missing_required"] == []


def test_complete_with_shown_fvg_types_missing_is_refused_but_draft_saves(
    client: TestClient, session: Session, trade: Trade
) -> None:
    fields = BASE_FIELDS | {"poi_types": ["fvg_h1"]}

    missing = incomplete_missing(put(client, trade.id, body(fields, complete=True, links=True)))
    draft = ok(put(client, trade.id, body(fields, links=True)))

    assert missing == ["fvg_types_h1"]
    assert draft["status"] == "draft"
    assert draft["missing_required"] == ["fvg_types_h1"]


def test_complete_with_both_fvg_types_shown_lists_both(client: TestClient, trade: Trade) -> None:
    fields = BASE_FIELDS | {"poi_types": ["fvg_h4", "fvg_h1"]}

    missing = incomplete_missing(put(client, trade.id, body(fields, complete=True, links=True)))

    assert missing == ["fvg_types_h1", "fvg_types_h4"]


def test_complete_without_poi_types_is_refused(client: TestClient, trade: Trade) -> None:
    fields = {k: v for k, v in BASE_FIELDS.items() if k != "poi_types"}

    missing = incomplete_missing(put(client, trade.id, body(fields, complete=True, links=True)))

    assert missing == ["poi_types"]


@pytest.mark.parametrize(
    ("fields", "text_key"),
    [
        ({"poi_types": ["other"]}, "poi_types_other"),
        ({"h1_context": "other"}, "h1_context_other"),
        ({"h4_context": "other"}, "h4_context_other"),
        ({"entry_model": "other"}, "entry_model_other"),
        (
            {"poi_types": ["fvg_h4"], "fvg_types_h4": ["other"]},
            "fvg_types_h4_other",
        ),
    ],
)
def test_other_without_text_blocks_complete_but_a_draft_saves(
    client: TestClient, session: Session, trade: Trade, fields: dict[str, Any], text_key: str
) -> None:
    all_fields = BASE_FIELDS | fields

    missing = incomplete_missing(put(client, trade.id, body(all_fields, complete=True, links=True)))
    draft = ok(put(client, trade.id, body(all_fields, links=True)))

    assert missing == [text_key]
    assert draft["status"] == "draft"
    assert stored(session, trade.id).status == "draft"


def test_other_with_text_completes(client: TestClient, trade: Trade) -> None:
    fields = BASE_FIELDS | {"poi_types": ["other"], "poi_types_other": "OB H4"}

    data = ok(put(client, trade.id, body(fields, complete=True, links=True)))

    assert data["status"] == "complete"


# --- legacy fields ---


@pytest.mark.parametrize(("key", "value"), [("setup_context", "yes"), ("fvg_kind", "na")])
def test_sending_a_legacy_field_is_422_not_writable(
    client: TestClient, trade: Trade, key: str, value: str
) -> None:
    response = put(client, trade.id, body({key: value}))

    assert response.status_code == 422
    error = response.json()["error"]
    assert f"fields.{key}" in error["details"]["fields"]


def test_poi_type_is_no_longer_a_field(client: TestClient, trade: Trade) -> None:
    response = put(client, trade.id, body({"poi_type": "fvg_h4"}))

    assert response.status_code == 422
    assert "fields.poi_type" in response.json()["error"]["details"]["fields"]


def test_legacy_value_is_returned_in_detail_and_survives_a_save(
    client: TestClient, session: Session, account: Account
) -> None:
    old = add_trade(session, account, setup_context="no", fvg_kind="na")

    before = detail(client, old.id)["journal"]
    ok(put(client, old.id, body({"h1_context": "flow"})))
    after = detail(client, old.id)["journal"]

    assert (before["setup_context"], before["fvg_kind"]) == ("no", "na")
    assert (after["setup_context"], after["fvg_kind"]) == ("no", "na")
    t = stored(session, old.id)
    assert (t.setup_context, t.fvg_kind) == ("no", "na")


def test_legacy_field_is_never_in_missing_required(client: TestClient, trade: Trade) -> None:
    missing = detail(client, trade.id)["missing_required"]

    assert not set(missing) & {"setup_context", "fvg_kind", "poi_type"}


def test_detail_journal_has_every_yaml_key(client: TestClient, trade: Trade) -> None:
    journal = detail(client, trade.id)["journal"]

    assert set(journal) == {k.key for k in journal_keys(get_journal_fields()) if k.type != "links"}


def test_detail_missing_required_order_for_a_blank_closed_trade(
    client: TestClient, trade: Trade
) -> None:
    missing = detail(client, trade.id)["missing_required"]

    assert missing == [
        "h1_context",
        "h4_context",
        "poi_types",
        "entry_model",
        "exit_reason",
        "followed_plan",
        "emotion_before",
        "emotion_after",
        "quality_rating",
        "chart_links",
    ]


# --- violations from config/violations.yaml ---


def add_violation_entries(cfg_dir: Path, *entries: dict[str, str]) -> None:
    path = cfg_dir / "violations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["violations"] += list(entries)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def manual(key: str, status: str = "active") -> dict[str, str]:
    return {"key": key, "label": f"label {key}", "type": "manual", "status": status}


def user_rows(session: Session, trade_id: int) -> list[str]:
    session.expire_all()
    rows = session.scalars(
        select(RuleViolation.rule_key)
        .where(RuleViolation.trade_id == trade_id, RuleViolation.source == "user")
        .order_by(RuleViolation.rule_key)
    )
    return list(rows)


def test_real_manual_violation_can_be_chosen(
    client: TestClient, session: Session, trade: Trade
) -> None:
    ok(put(client, trade.id, body({"rule_violations": ["entry_weak_poi"]})))

    assert user_rows(session, trade.id) == ["entry_weak_poi"]


def test_unknown_violation_is_rejected_until_it_is_added_to_the_yaml(
    client: TestClient, session: Session, trade: Trade, cfg_dir: Path
) -> None:
    fields = {"rule_violations": ["my_new_rule"]}

    first = put(client, trade.id, body(fields))
    add_violation_entries(cfg_dir, manual("my_new_rule"))  # no code change, file re-read on change
    second = put(client, trade.id, body(fields))

    assert first.status_code == 422
    assert "fields.rule_violations" in first.json()["error"]["details"]["fields"]
    ok(second)
    assert user_rows(session, trade.id) == ["my_new_rule"]


def test_deprecated_violation_is_kept_on_a_trade_that_has_it(
    client: TestClient, session: Session, trade: Trade, cfg_dir: Path
) -> None:
    add_violation_entries(cfg_dir, manual("old_manual", "deprecated"))
    reload_config()
    add_violation(session, trade, "old_manual", "user")

    ok(put(client, trade.id, body({"rule_violations": ["old_manual"]})))

    assert user_rows(session, trade.id) == ["old_manual"]


def test_deprecated_violation_is_rejected_on_a_trade_without_it(
    client: TestClient, session: Session, account: Account, cfg_dir: Path
) -> None:
    add_violation_entries(cfg_dir, manual("old_manual", "deprecated"))
    reload_config()
    other = add_trade(session, account)

    response = put(client, other.id, body({"rule_violations": ["old_manual"]}))

    assert response.status_code == 422
    assert "fields.rule_violations" in response.json()["error"]["details"]["fields"]
    assert user_rows(session, other.id) == []


def test_old_daily_key_is_shown_on_an_old_trade_but_not_selectable_elsewhere(
    client: TestClient, session: Session, account: Account
) -> None:
    old = add_trade(session, account)
    add_violation(session, old, "daily_stop_loss_pct")
    fresh = add_trade(session, account)

    assert "daily_stop_loss_pct" in detail(client, old.id)["journal"]["rule_violations"]
    response = put(client, fresh.id, body({"rule_violations": ["daily_stop_loss_pct"]}))
    assert response.status_code == 422


# --- required_since for the new required fields ---


def seed_requirements(db: Session, config_keys: tuple[str, ...], new_since: datetime) -> None:
    """The table as after the migration: old keys since 1970, the new ones since `new_since`."""
    old_since = datetime(1970, 1, 1, tzinfo=UTC)
    for key in config_keys:
        since = new_since if key in NEW_REQUIRED_KEYS | NEW_TEXT_KEYS else old_since
        db.execute(
            text("INSERT INTO journal_field_requirements (key, required_since) VALUES (:k, :s)"),
            {"k": key, "s": since},
        )
    db.execute(text("UPDATE journal_requirements_state SET initial_fill_at = :s"), {"s": new_since})
    db.commit()


def test_new_required_fields_do_not_make_an_old_complete_trade_incomplete(
    client: TestClient, session: Session, account: Account
) -> None:
    since = datetime.now(UTC)
    seed_requirements(session, requirement_keys(get_journal_fields()), since)
    old_fields = {
        k: v for k, v in BASE_FIELDS.items() if k not in {"h1_context", "h4_context", "poi_types"}
    }
    old = add_trade(
        session,
        account,
        status="complete",
        close_time=since - timedelta(days=5),
        open_time=since - timedelta(days=5, minutes=30),
        setup_context="yes",
        fvg_kind="na",
        **old_fields,
    )
    session.add(ChartLink(trade_id=old.id, url=SNAP, kind="before"))
    session.commit()

    data = detail(client, old.id)

    assert data["status"] == "complete"
    assert data["missing_required"] == []
    assert data["missing_new_fields"] == ["h1_context", "h4_context", "poi_types"]
    resaved = ok(put(client, old.id, body(old_fields, complete=True, links=True)))
    assert resaved["status"] == "complete"
    assert resaved["missing_new_fields"] == ["h1_context", "h4_context", "poi_types"]


def test_a_trade_closed_after_the_change_needs_the_new_fields(
    client: TestClient, session: Session, account: Account
) -> None:
    since = datetime.now(UTC)
    seed_requirements(session, requirement_keys(get_journal_fields()), since)
    new = add_trade(
        session,
        account,
        close_time=since + timedelta(seconds=1),
        open_time=since - timedelta(minutes=30),
    )
    old_fields = {
        k: v for k, v in BASE_FIELDS.items() if k not in {"h1_context", "h4_context", "poi_types"}
    }

    missing = incomplete_missing(put(client, new.id, body(old_fields, complete=True, links=True)))

    assert missing == ["h1_context", "h4_context", "poi_types"]


# --- «Інше» text made required later (review 2026-11-19: entry_model had `other` before) ---


def _old_other_trade(session: Session, account: Account, since: datetime) -> Trade:
    fields = BASE_FIELDS | {"entry_model": "other"}
    old = add_trade(
        session,
        account,
        status="complete",
        close_time=since - timedelta(days=5),
        open_time=since - timedelta(days=5, minutes=30),
        **fields,
    )
    session.add(ChartLink(trade_id=old.id, url=SNAP, kind="before"))
    session.commit()
    return old


def test_old_trade_with_other_and_no_text_stays_and_completes(
    client: TestClient, session: Session, account: Account
) -> None:
    since = datetime.now(UTC)
    seed_requirements(session, requirement_keys(get_journal_fields()), since)
    old = _old_other_trade(session, account, since)

    data = detail(client, old.id)
    resaved = ok(
        put(client, old.id, body(BASE_FIELDS | {"entry_model": "other"}, complete=True, links=True))
    )

    assert data["status"] == "complete"
    assert data["missing_required"] == []
    assert data["missing_new_fields"] == ["entry_model_other"]
    assert resaved["status"] == "complete"


def test_new_trade_with_other_needs_the_text(
    client: TestClient, session: Session, account: Account
) -> None:
    since = datetime.now(UTC)
    seed_requirements(session, requirement_keys(get_journal_fields()), since)
    new = add_trade(
        session,
        account,
        close_time=since + timedelta(seconds=1),
        open_time=since - timedelta(minutes=30),
    )
    fields = BASE_FIELDS | {"entry_model": "other"}

    missing = incomplete_missing(put(client, new.id, body(fields, complete=True, links=True)))

    assert missing == ["entry_model_other"]
