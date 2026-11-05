"""TradeDetail M2 shape and PUT /api/trades/{id}/journal (docs/api.md M2)."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.config_files import get_journal_fields, reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.domain.journal import ai_fillable_keys, journal_keys
from app.models import Account, ChartLink, RuleViolation, Trade
from tests.test_trades_api import add_account, add_trade, add_violation

SNAP = "https://www.tradingview.com/x/AbCd1234/"
SNAP_PREVIEW = "https://s3.tradingview.com/snapshots/a/AbCd1234.png"
CHART = "https://www.tradingview.com/chart/Xy12ab/"

COMPLETE_FIELDS: dict[str, Any] = {
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


def trade_in(db: Session, account: Account, trading_session: str) -> Trade:
    t = add_trade(db, account)
    t.session = trading_session
    db.commit()
    return t


def body(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "fields": {},
        "chart_links": [],
        "raw_text": None,
        "ai_filled_fields": [],
        "complete": False,
    }
    return data | kw


def put(client: TestClient, trade_id: int, data: dict[str, Any]) -> Any:
    return client.put(f"/api/trades/{trade_id}/journal", json=data)


def ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def field_errors(response: Any) -> dict[str, str]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields: dict[str, str] = error["details"]["fields"]
    return fields


def stored(session: Session, trade_id: int) -> Trade:
    session.expire_all()
    found = session.get(Trade, trade_id)
    assert found is not None
    return found


def violation_rows(session: Session, trade_id: int) -> list[tuple[str, str]]:
    session.expire_all()
    rows = session.execute(
        select(RuleViolation.rule_key, RuleViolation.source)
        .where(RuleViolation.trade_id == trade_id)
        .order_by(RuleViolation.rule_key)
    )
    return [(k, s) for k, s in rows]


# --- GET shape ---


def test_detail_m2_shape(client: TestClient, session: Session, trade: Trade) -> None:
    trade.setup_context = "yes"
    trade.poi_type = "other"
    trade.poi_type_other = "OB H4"
    trade.bias_alignment = "counter"
    trade.extra = {"removed_field": 1}
    session.add(ChartLink(trade_id=trade.id, url=SNAP, kind="before"))
    session.add(ChartLink(trade_id=trade.id, url=CHART, kind="after"))
    session.commit()
    add_violation(session, trade, "min_planned_rr")
    add_violation(session, trade, "max_risk_pct", "user")

    data = ok(client.get(f"/api/trades/{trade.id}"))

    for key in ("setup_context", "extra", "bias_alignment_override", "poi_type_other"):
        assert key not in data
    journal = data["journal"]
    assert journal["setup_context"] == "yes"
    assert journal["poi_type_other"] == "OB H4"
    assert journal["rule_violations"] == ["max_risk_pct", "min_planned_rr"]
    assert journal["bias_alignment"] == "counter"
    assert journal["lesson"] is None
    assert "removed_field" not in journal
    assert "chart_links" not in journal
    assert set(journal) == {k.key for k in journal_keys(get_journal_fields()) if k.type != "links"}
    assert [(c["url"], c["kind"], c["preview_url"]) for c in data["chart_links"]] == [
        (SNAP, "before", SNAP_PREVIEW),
        (CHART, "after", None),
    ]
    assert all(isinstance(c["id"], int) for c in data["chart_links"])
    assert data["missing_required"] == [
        "fvg_kind",
        "entry_model",
        "exit_reason",
        "followed_plan",
        "emotion_before",
        "emotion_after",
        "quality_rating",
    ]
    assert data["raw_text"] is None
    assert data["transcript"] is None
    assert data["ai_filled_fields"] == []
    assert data["described_at"] is None


def test_bias_override_wins(client: TestClient, session: Session, trade: Trade) -> None:
    trade.bias_alignment = "counter"
    trade.bias_alignment_override = "aligned"
    session.commit()
    assert ok(client.get(f"/api/trades/{trade.id}"))["journal"]["bias_alignment"] == "aligned"


def test_missing_required_no_before_link(client: TestClient, trade: Trade) -> None:
    links = [{"url": CHART, "kind": "after"}]
    data = ok(put(client, trade.id, body(fields=COMPLETE_FIELDS, chart_links=links)))
    assert data["missing_required"] == ["chart_links"]


# --- PUT: basics ---


def test_put_draft_saves_columns(client: TestClient, session: Session, trade: Trade) -> None:
    before = datetime.now(UTC)
    data = ok(
        put(
            client,
            trade.id,
            body(
                fields={"setup_context": "yes", "quality_rating": 4, "lesson": "  wait  "},
                raw_text="опис угоди як є",
            ),
        )
    )
    assert data["status"] == "draft"
    assert data["journal"]["setup_context"] == "yes"
    assert data["journal"]["lesson"] == "wait"
    assert data["raw_text"] == "опис угоди як є"
    t = stored(session, trade.id)
    assert (t.status, t.setup_context, t.quality_rating, t.lesson) == ("draft", "yes", 4, "wait")
    assert t.described_at is not None
    assert t.described_at >= before


def test_put_is_full_replacement(client: TestClient, session: Session, trade: Trade) -> None:
    ok(put(client, trade.id, body(fields={"setup_context": "yes", "lesson": "x"})))
    data = ok(put(client, trade.id, body(fields={"lesson": None, "mistakes": "y"})))
    assert data["journal"]["setup_context"] is None
    assert data["journal"]["lesson"] is None
    assert data["journal"]["mistakes"] == "y"
    assert stored(session, trade.id).setup_context is None


def test_described_at_updated_on_every_save(
    client: TestClient, session: Session, trade: Trade
) -> None:
    first = ok(put(client, trade.id, body()))["described_at"]
    second = ok(put(client, trade.id, body()))["described_at"]
    assert first is not None
    assert first.endswith("Z")
    assert second >= first
    assert stored(session, trade.id).described_at is not None


@pytest.mark.parametrize("missing", ["fields", "chart_links", "raw_text", "ai_filled_fields"])
def test_top_level_keys_required(client: TestClient, trade: Trade, missing: str) -> None:
    data = body()
    del data[missing]
    assert missing in field_errors(put(client, trade.id, data))


def test_complete_key_required_and_unknown_rejected(client: TestClient, trade: Trade) -> None:
    data = body()
    del data["complete"]
    assert "complete" in field_errors(put(client, trade.id, data))
    assert "status" in field_errors(put(client, trade.id, body(status="complete")))
    assert "complete" in field_errors(put(client, trade.id, body(complete="true")))


def test_unknown_and_not_writable_field_keys(client: TestClient, trade: Trade) -> None:
    fields = {"nope": 1, "bias_alignment": "aligned", "chart_links": [], "extra": {}}
    errors = field_errors(put(client, trade.id, body(fields=fields)))
    assert set(errors) == {
        "fields.nope",
        "fields.bias_alignment",
        "fields.chart_links",
        "fields.extra",
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("setup_context", "maybe"),
        ("setup_context", True),
        ("followed_plan", "yes"),
        ("quality_rating", 0),
        ("quality_rating", 6),
        ("quality_rating", 4.0),
        ("quality_rating", True),
        ("lesson", 5),
        ("lesson", "x" * 5001),
        ("rule_violations", ["max_risk_pct", "max_risk_pct"]),
        ("rule_violations", ["not_a_rule"]),
        ("rule_violations", "max_risk_pct"),
    ],
)
def test_field_type_errors(
    client: TestClient, session: Session, trade: Trade, key: str, value: Any
) -> None:
    errors = field_errors(put(client, trade.id, body(fields={key: value})))
    assert list(errors) == [f"fields.{key}"]
    assert stored(session, trade.id).status == "needs_description"  # nothing saved


def test_raw_text_limit(client: TestClient, trade: Trade) -> None:
    assert "raw_text" in field_errors(put(client, trade.id, body(raw_text="x" * 20001)))
    ok(put(client, trade.id, body(raw_text="x" * 20000)))


def test_other_text_cleared_unless_other(client: TestClient, trade: Trade) -> None:
    data = ok(put(client, trade.id, body(fields={"poi_type": "fvg_h4", "poi_type_other": "OB"})))
    assert data["journal"]["poi_type_other"] is None
    data = ok(put(client, trade.id, body(fields={"poi_type": "other", "poi_type_other": "OB"})))
    assert data["journal"]["poi_type_other"] == "OB"


def test_note_text_key_kept(client: TestClient, trade: Trade) -> None:
    fields = {"emotion_before": "fear", "emotion_before_text": "news"}
    assert ok(put(client, trade.id, body(fields=fields)))["journal"]["emotion_before_text"] == (
        "news"
    )


def test_ai_filled_fields_filtered(client: TestClient, session: Session, trade: Trade) -> None:
    data = ok(
        put(
            client,
            trade.id,
            body(
                fields={"setup_context": "yes", "followed_plan": False, "lesson": ""},
                ai_filled_fields=[
                    "followed_plan",
                    "lesson",
                    "entry_model",
                    "nope",
                    "setup_context",
                ],
            ),
        )
    )
    assert data["ai_filled_fields"] == ["followed_plan", "setup_context"]
    assert stored(session, trade.id).ai_filled_fields == ["followed_plan", "setup_context"]


# --- status rules ---


def test_complete_saves_and_back_to_draft(client: TestClient, trade: Trade) -> None:
    links = [{"url": SNAP, "kind": "before"}]
    data = ok(put(client, trade.id, body(fields=COMPLETE_FIELDS, chart_links=links, complete=True)))
    assert data["status"] == "complete"
    assert data["missing_required"] == []
    data = ok(put(client, trade.id, body(fields=COMPLETE_FIELDS, chart_links=links)))
    assert data["status"] == "draft"


def test_incomplete_is_422_and_saves_nothing(
    client: TestClient, session: Session, trade: Trade
) -> None:
    fields = COMPLETE_FIELDS | {"poi_type": "other", "fvg_kind": None}
    response = put(
        client,
        trade.id,
        body(
            fields=fields,
            chart_links=[{"url": CHART, "kind": "after"}],
            raw_text="text",
            complete=True,
        ),
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "journal_incomplete"
    assert error["details"] == {"missing": ["poi_type_other", "fvg_kind", "chart_links"]}
    t = stored(session, trade.id)
    assert (t.status, t.setup_context, t.raw_text, t.described_at) == (
        "needs_description",
        None,
        None,
        None,
    )
    assert session.scalars(select(ChartLink).where(ChartLink.trade_id == trade.id)).all() == []


def test_incomplete_keeps_previous_draft(
    client: TestClient, session: Session, trade: Trade
) -> None:
    ok(put(client, trade.id, body(fields={"lesson": "first"})))
    response = put(client, trade.id, body(fields={"lesson": "second"}, complete=True))
    assert response.json()["error"]["code"] == "journal_incomplete"
    t = stored(session, trade.id)
    assert (t.status, t.lesson) == ("draft", "first")


def test_needs_sl_is_409(client: TestClient, session: Session, account: Account) -> None:
    t = add_trade(session, account, status="needs_sl")
    response = put(client, t.id, body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "needs_sl"


def test_open_trade_is_409(client: TestClient, session: Session, account: Account) -> None:
    t = add_trade(
        session,
        account,
        status="open",
        close_time=None,
        exit_price=None,
        gross_pnl=None,
        net_pnl=None,
        duration_seconds=None,
    )
    response = put(client, t.id, body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "trade_open"


def test_put_404(client: TestClient) -> None:
    response = put(client, 999999, body())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- chart links ---


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/x/AbCd1234/",
        "http://www.tradingview.com/x/AbCd1234/",
        "https://www.tradingview.com",
        "https://www.tradingview.com/x/AbCd1234/" + "a" * 500,
    ],
)
def test_link_url_invalid(client: TestClient, trade: Trade, url: str) -> None:
    links = [{"url": SNAP, "kind": "before"}, {"url": url, "kind": "after"}]
    assert list(field_errors(put(client, trade.id, body(chart_links=links)))) == [
        "chart_links.1.url"
    ]


def test_link_kind_bias_rejected(client: TestClient, trade: Trade) -> None:
    links = [{"url": SNAP, "kind": "bias"}]
    assert "chart_links.0.kind" in field_errors(put(client, trade.id, body(chart_links=links)))


def test_link_unknown_key_rejected(client: TestClient, trade: Trade) -> None:
    links = [{"url": SNAP, "kind": "before", "id": 3}]
    assert "chart_links.0.id" in field_errors(put(client, trade.id, body(chart_links=links)))


def test_link_duplicates_rejected(client: TestClient, trade: Trade) -> None:
    links = [
        {"url": SNAP, "kind": "before"},
        {"url": CHART, "kind": "after"},
        {"url": "HTTPS://WWW.TRADINGVIEW.COM/x/AbCd1234?utm=1", "kind": "after"},
    ]
    errors = field_errors(put(client, trade.id, body(chart_links=links)))
    assert list(errors) == ["chart_links.2.url"]


def test_link_case_sensitive_ids_are_not_duplicates(client: TestClient, trade: Trade) -> None:
    links = [
        {"url": SNAP, "kind": "before"},
        {"url": SNAP.replace("AbCd", "abcd"), "kind": "after"},
    ]
    assert len(ok(put(client, trade.id, body(chart_links=links)))["chart_links"]) == 2


def test_link_count_limit(client: TestClient, trade: Trade) -> None:
    links = [{"url": f"https://www.tradingview.com/x/id{i}/", "kind": "after"} for i in range(11)]
    assert "chart_links" in field_errors(put(client, trade.id, body(chart_links=links)))
    ok(put(client, trade.id, body(chart_links=links[:10])))


def test_links_full_replacement_in_order(
    client: TestClient, session: Session, trade: Trade
) -> None:
    ok(put(client, trade.id, body(chart_links=[{"url": SNAP, "kind": "before"}])))
    links = [{"url": CHART, "kind": "after"}, {"url": SNAP, "kind": "before"}]
    data = ok(put(client, trade.id, body(chart_links=links)))
    assert [(c["url"], c["kind"]) for c in data["chart_links"]] == [
        (CHART, "after"),
        (SNAP, "before"),
    ]
    rows = session.scalars(select(ChartLink).where(ChartLink.trade_id == trade.id)).all()
    assert len(rows) == 2
    assert ok(put(client, trade.id, body()))["chart_links"] == []


# --- rule violations ---


def test_user_violations_add_and_delete(client: TestClient, session: Session, trade: Trade) -> None:
    fields = {"rule_violations": ["no_breakeven", "max_risk_pct"]}
    data = ok(put(client, trade.id, body(fields=fields)))
    assert data["journal"]["rule_violations"] == ["max_risk_pct", "no_breakeven"]
    assert violation_rows(session, trade.id) == [("max_risk_pct", "user"), ("no_breakeven", "user")]
    data = ok(put(client, trade.id, body(fields={"rule_violations": ["max_risk_pct"]})))
    assert violation_rows(session, trade.id) == [("max_risk_pct", "user")]
    data = ok(put(client, trade.id, body()))
    assert violation_rows(session, trade.id) == []
    assert data["journal"]["rule_violations"] is None


def test_auto_violations_untouched(client: TestClient, session: Session, account: Account) -> None:
    t = trade_in(session, account, "outside")  # entry_session is an auto violation
    ok(put(client, t.id, body()))  # first save runs the rules recompute
    assert violation_rows(session, t.id) == [("entry_session", "auto")]

    data = ok(put(client, t.id, body(fields={"rule_violations": []})))  # auto key omitted
    assert violation_rows(session, t.id) == [("entry_session", "auto")]
    assert data["journal"]["rule_violations"] == ["entry_session"]

    fields = {"rule_violations": ["entry_session", "max_risk_pct"]}  # auto key listed
    data = ok(put(client, t.id, body(fields=fields)))
    assert violation_rows(session, t.id) == [("entry_session", "auto"), ("max_risk_pct", "user")]
    assert data["rule_violations"][0]["source"] == "auto"


def test_entry_model_change_recomputes_rules(
    client: TestClient, session: Session, account: Account
) -> None:
    t = trade_in(session, account, "ny")
    ok(put(client, t.id, body(fields={"entry_model": "qm_m5"})))
    assert ("qm_not_in_ny", "auto") in violation_rows(session, t.id)
    ok(put(client, t.id, body(fields={"entry_model": "ifvg_m5"})))
    assert "qm_not_in_ny" not in dict(violation_rows(session, t.id))


def test_locked_auto_key_never_becomes_user_violation(
    client: TestClient, session: Session, account: Account
) -> None:
    t = trade_in(session, account, "ny")
    ok(put(client, t.id, body(fields={"entry_model": "qm_m5"})))
    assert violation_rows(session, t.id) == [("qm_not_in_ny", "auto")]
    # The UI sends the locked auto key back unchanged while changing entry_model: the
    # recompute drops the auto row and no user row may take its place.
    fields = {"entry_model": "ifvg_m5", "rule_violations": ["qm_not_in_ny"]}
    data = ok(put(client, t.id, body(fields=fields)))
    assert violation_rows(session, t.id) == []
    assert data["journal"]["rule_violations"] is None


def test_incomplete_rollback_restores_user_violations(
    client: TestClient, session: Session, trade: Trade
) -> None:
    ok(put(client, trade.id, body(fields={"rule_violations": ["max_risk_pct"]})))
    response = put(client, trade.id, body(fields={"rule_violations": []}, complete=True))
    assert response.json()["error"]["code"] == "journal_incomplete"
    assert violation_rows(session, trade.id) == [("max_risk_pct", "user")]


def test_ai_filled_fields_limit(client: TestClient, trade: Trade) -> None:
    data = body(ai_filled_fields=[f"k{i}" for i in range(101)])
    assert "ai_filled_fields" in field_errors(put(client, trade.id, data))


def test_user_violation_kept_when_rule_now_detects_it(
    client: TestClient, session: Session, account: Account
) -> None:
    t = trade_in(session, account, "ny")
    ok(put(client, t.id, body(fields={"rule_violations": ["qm_not_in_ny"]})))
    assert violation_rows(session, t.id) == [("qm_not_in_ny", "user")]
    # Removing the user row while the rule fires leaves the auto row (never lost).
    ok(put(client, t.id, body(fields={"entry_model": "qm_m5", "rule_violations": []})))
    assert violation_rows(session, t.id) == [("qm_not_in_ny", "auto")]


# --- YAML-driven: deprecated options and new fields without code changes ---

REAL_CONFIG = REPO_ROOT / "config"
NEW_FIELD = """
  - key: market_phase
    label: "Фаза ринку"
    type: enum
    options:
      - { value: trend, label: "тренд" }
      - { value: range, label: "флет" }
      - { value: other, label: "інше" }
    required: true
    analytics: true
    storage: extra
    text_key: market_phase_other
    allow_other_text: true
"""


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for name in (
        "rules.yaml",
        "journal_fields.yaml",
        "ai_pricing.yaml",
        "extraction.yaml",
        "transcription.yaml",
        "transcript_glossary.yaml",
        "bias.yaml",
    ):
        shutil.copy(REAL_CONFIG / name, tmp_path / name)
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


def test_deprecated_option_only_if_already_stored(
    client: TestClient, session: Session, account: Account, cfg_dir: Path
) -> None:
    edit_yaml(
        cfg_dir,
        '{ value: partially, label: "частково" }',
        '{ value: partially, label: "частково", deprecated: true }',
    )
    old = add_trade(session, account, setup_context="partially")
    new = add_trade(session, account)
    fields = {"setup_context": "partially"}
    assert "fields.setup_context" in field_errors(put(client, new.id, body(fields=fields)))
    assert ok(put(client, old.id, body(fields=fields)))["journal"]["setup_context"] == "partially"


def test_new_yaml_field_works_without_code_changes(
    client: TestClient, session: Session, trade: Trade, cfg_dir: Path
) -> None:
    trade.extra = {"legacy_key": "kept"}
    session.commit()
    path = cfg_dir / "journal_fields.yaml"
    path.write_text(path.read_text(encoding="utf-8") + NEW_FIELD, encoding="utf-8")
    reload_config()

    keys = [f["key"] for f in ok(client.get("/api/journal-fields"))["fields"]]
    assert keys[-1] == "market_phase"
    assert "market_phase" in [k.key for k in ai_fillable_keys(get_journal_fields())]
    assert "market_phase_other" in [k.key for k in ai_fillable_keys(get_journal_fields())]

    data = ok(client.get(f"/api/trades/{trade.id}"))
    assert data["journal"]["market_phase"] is None
    assert data["journal"]["market_phase_other"] is None
    assert "market_phase" in data["missing_required"]

    links = [{"url": SNAP, "kind": "before"}]
    response = put(client, trade.id, body(fields=COMPLETE_FIELDS, chart_links=links, complete=True))
    assert response.json()["error"]["details"]["missing"] == ["market_phase"]

    fields = COMPLETE_FIELDS | {"market_phase": "other", "market_phase_other": " клин "}
    data = ok(put(client, trade.id, body(fields=fields, chart_links=links, complete=True)))
    assert data["status"] == "complete"
    assert data["journal"]["market_phase"] == "other"
    assert data["journal"]["market_phase_other"] == "клин"
    assert "legacy_key" not in data["journal"]
    t = stored(session, trade.id)
    assert t.extra == {"legacy_key": "kept", "market_phase": "other", "market_phase_other": "клин"}

    bad = COMPLETE_FIELDS | {"market_phase": "sideways"}
    assert "fields.market_phase" in field_errors(put(client, trade.id, body(fields=bad)))
    data = ok(put(client, trade.id, body(fields={"market_phase": "trend"})))
    assert stored(session, trade.id).extra == {"legacy_key": "kept", "market_phase": "trend"}


def test_broken_yaml_is_config_error(client: TestClient, trade: Trade, cfg_dir: Path) -> None:
    (cfg_dir / "journal_fields.yaml").write_text("fields: []\n", encoding="utf-8")
    reload_config()
    for response in (client.get(f"/api/trades/{trade.id}"), put(client, trade.id, body())):
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "config_error"


def test_patch_initial_sl_with_broken_journal_yaml(
    client: TestClient, session: Session, account: Account, cfg_dir: Path
) -> None:
    t = add_trade(session, account, status="needs_sl")
    (cfg_dir / "journal_fields.yaml").write_text("fields: []\n", encoding="utf-8")
    reload_config()
    response = client.patch(f"/api/trades/{t.id}", json={"initial_sl": "2640.00"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"
    saved = stored(session, t.id)
    assert (saved.initial_sl, saved.status) == (None, "needs_sl")  # SL not saved


def test_save_with_broken_rules_yaml_skips_recompute(
    client: TestClient,
    session: Session,
    account: Account,
    cfg_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    t = trade_in(session, account, "outside")  # would get an entry_session auto violation
    (cfg_dir / "rules.yaml").write_text("timezone: 5\n", encoding="utf-8")
    reload_config()
    with caplog.at_level(logging.ERROR, logger="app.services.trade_rules"):
        data = ok(put(client, t.id, body(fields={"lesson": "x"})))
    assert data["status"] == "draft"
    assert data["journal"]["lesson"] == "x"
    assert violation_rows(session, t.id) == []
    assert any("violations not recomputed" in r.getMessage() for r in caplog.records)
