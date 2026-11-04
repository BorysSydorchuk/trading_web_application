"""journal_field_requirements sync and the SQL `missing_new_fields` filter
(app.services.journal_requirements, docs/api.md M3 "New required fields")."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config_files import reload_config
from app.config_files.journal_fields import JournalFieldsConfig, load_journal_fields
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.domain.journal import required_field_keys
from app.models import ChartLink, JournalRequirementsState, RuleViolation, Trade
from app.services.journal_requirements import (
    INITIAL_REQUIRED_SINCE,
    load_requirements,
    missing_new_fields_condition,
    sync_requirements,
)
from app.services.trade_journal import journal_view
from app.worker.main import sync_journal_requirements
from tests.test_trades_api import T0, add_account, add_trade

LATER = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
LATEST = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


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


def config_with(*required: str, optional: tuple[str, ...] = ()) -> JournalFieldsConfig:
    """Bool fields in `extra`; the domain/sync code only looks at `required`."""
    fields: list[dict[str, Any]] = [
        {
            "key": key,
            "label": key,
            "type": "bool",
            "required": key in required,
            "analytics": False,
            "storage": "extra",
        }
        for key in (*required, *optional)
    ]
    return JournalFieldsConfig.model_validate({"fields": fields})


def at(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def never() -> datetime:
    raise AssertionError("sync wrote although the table already matched the YAML")


def marker(db: Session) -> datetime | None:
    db.expire_all()
    return db.scalars(select(JournalRequirementsState.initial_fill_at)).one()


# --- sync ---


def test_first_fill_stamps_1970(session: Session) -> None:
    result = sync_requirements(session, config_with("a", "b", optional=("c",)), at(LATER))
    assert result == {"a": INITIAL_REQUIRED_SINCE, "b": INITIAL_REQUIRED_SINCE}
    assert load_requirements(session) == result
    assert marker(session) == LATER


def test_field_required_later_gets_now(session: Session) -> None:
    sync_requirements(session, config_with("a", optional=("b",)), at(LATER))
    result = sync_requirements(session, config_with("a", "b"), at(LATEST))
    assert result == {"a": INITIAL_REQUIRED_SINCE, "b": LATEST}


def test_unrequired_field_loses_its_row(session: Session) -> None:
    sync_requirements(session, config_with("a", "b"), at(LATER))
    result = sync_requirements(session, config_with("a", optional=("b",)), at(LATEST))
    assert result == {"a": INITIAL_REQUIRED_SINCE}


def test_rerequired_after_empty_table_gets_now_not_1970(session: Session) -> None:
    sync_requirements(session, config_with("a"), at(LATER))
    assert sync_requirements(session, config_with(optional=("a",)), at(LATER)) == {}
    result = sync_requirements(session, config_with("a"), at(LATEST))
    assert result == {"a": LATEST}
    assert marker(session) == LATER  # the first fill is never repeated


def test_first_fill_is_the_first_insert(session: Session) -> None:
    """Contract: "the first time the table is filled". A sync with nothing required
    writes nothing, so the marker stays unset until a row is inserted."""
    assert sync_requirements(session, config_with(optional=("a",)), never) == {}
    assert marker(session) is None
    assert sync_requirements(session, config_with("a"), at(LATEST)) == {"a": INITIAL_REQUIRED_SINCE}


def test_no_write_when_table_matches(session: Session) -> None:
    config = config_with("a", "b")
    first = sync_requirements(session, config, at(LATER))
    assert sync_requirements(session, config, never) == first


def test_missing_marker_row_is_recreated_as_already_filled(
    session: Session, db_engine: Engine
) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM journal_requirements_state"))
    assert sync_requirements(session, config_with("a"), at(LATER)) == {"a": LATER}
    assert marker(session) == LATER


def test_concurrent_syncs_fill_once(db_engine: Engine) -> None:
    """API and worker syncing at the same moment: one first fill, same result for all."""
    config = config_with("a", "b", "c")
    factory = make_session_factory(db_engine)
    workers = 6
    barrier = threading.Barrier(workers)
    results: list[dict[str, datetime]] = []
    errors: list[BaseException] = []

    def run(i: int) -> None:
        with factory() as db:
            try:
                barrier.wait()
                results.append(sync_requirements(db, config, at(LATER + timedelta(seconds=i))))
            except BaseException as exc:  # reported below
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    expected = dict.fromkeys(("a", "b", "c"), INITIAL_REQUIRED_SINCE)
    assert results == [expected] * workers


def test_concurrent_addition_keeps_one_timestamp(db_engine: Engine) -> None:
    factory = make_session_factory(db_engine)
    with factory() as db:
        sync_requirements(db, config_with("a", optional=("b",)), at(LATER))
    config = config_with("a", "b")
    workers = 4
    barrier = threading.Barrier(workers)
    results: list[dict[str, datetime]] = []

    def run(i: int) -> None:
        with factory() as db:
            barrier.wait()
            results.append(sync_requirements(db, config, at(LATEST + timedelta(seconds=i))))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == workers
    assert len({r["b"] for r in results}) == 1  # all processes agree on the winner
    assert results[0]["a"] == INITIAL_REQUIRED_SINCE


# --- SQL filter == Python missing_new_fields ---


def _python_ids(
    session: Session, config: JournalFieldsConfig, since: dict[str, datetime]
) -> set[int]:
    session.expire_all()
    ids: set[int] = set()
    for trade in session.scalars(select(Trade)):
        if journal_view(trade, config, since).missing_new_fields:
            ids.add(trade.id)
    return ids


def _sql_ids(session: Session, config: JournalFieldsConfig, since: dict[str, datetime]) -> set[int]:
    return set(session.scalars(select(Trade.id).where(missing_new_fields_condition(config, since))))


def test_sql_filter_matches_python_rule(session: Session) -> None:
    """Every storage kind: column, extra JSONB, links (before only) and multi_enum relation."""
    real = load_journal_fields()
    account = add_account(session, "Alpha", 1)
    change = T0 + timedelta(hours=1)  # add_trade closes at T0 + 30 min
    since = dict.fromkeys(
        ("setup_context", "followed_plan", "quality_rating"), INITIAL_REQUIRED_SINCE
    )
    since |= {"chart_links": change, "entry_model": change}
    full = {"entry_model": "ifvg_m5"}

    before_link = add_trade(session, account, **full)
    session.add(
        ChartLink(trade_id=before_link.id, url="https://www.tradingview.com/x/A/", kind="before")
    )
    after_link_only = add_trade(session, account, **full)
    session.add(
        ChartLink(trade_id=after_link_only.id, url="https://www.tradingview.com/x/B/", kind="after")
    )
    no_model = add_trade(session, account)  # missing entry_model and chart_links
    session.add(
        ChartLink(trade_id=no_model.id, url="https://www.tradingview.com/x/C/", kind="before")
    )
    closed_later = add_trade(session, account, close_time=change)  # boundary: not "new"
    add_trade(session, account, status="open", close_time=None, duration_seconds=None)
    session.commit()

    assert _sql_ids(session, real, since) == _python_ids(session, real, since)
    assert _sql_ids(session, real, since) == {after_link_only.id, no_model.id}
    assert closed_later.id not in _sql_ids(session, real, since)

    # extra storage: missing key, JSON null, "", [] are empty; true/false/0 are values
    extra_cfg = config_with("flag")
    extras: list[dict[str, Any]] = [
        {"flag": None},
        {"flag": ""},
        {"flag": []},
        {"flag": True},
        {"flag": False},
    ]
    for extra in extras:
        add_trade(session, account, extra=extra)
    add_trade(session, account, extra={"flag": 0})
    since_extra = {"flag": change}
    sql = _sql_ids(session, extra_cfg, since_extra)
    assert sql == _python_ids(session, extra_cfg, since_extra)
    assert len(sql) == 3 + 3  # 3 trades above closed before, no "flag" + 3 empty ones

    # the rule_violations relation (multi_enum stored as child rows)
    rv_cfg = JournalFieldsConfig(
        fields=tuple(
            f.model_copy(update={"required": f.key == "rule_violations"}) for f in real.fields
        )
    )
    session.add(RuleViolation(trade_id=before_link.id, rule_key="max_risk_pct", source="user"))
    session.commit()
    since_rv = {"rule_violations": change}
    assert _sql_ids(session, rv_cfg, since_rv) == _python_ids(session, rv_cfg, since_rv)
    assert before_link.id not in _sql_ids(session, rv_cfg, since_rv)


def test_sql_filter_nothing_new_is_empty(session: Session) -> None:
    account = add_account(session, "Alpha", 1)
    add_trade(session, account)
    real = load_journal_fields()
    since = sync_requirements(session, real, at(LATER))
    assert _sql_ids(session, real, since) == set()
    assert _sql_ids(session, real, {}) == set()


# --- worker job ---


def test_worker_job_syncs_and_skips_broken_yaml(
    db_engine: Engine, session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = make_session_factory(db_engine)
    sync_journal_requirements(factory)
    rows = load_requirements(session)
    assert set(rows) == set(required_field_keys(load_journal_fields()))

    (tmp_path / "journal_fields.yaml").write_text("fields: []\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    reload_config()
    try:
        sync_journal_requirements(factory)  # no error, table untouched
    finally:
        monkeypatch.undo()
        reload_config()
    session.expire_all()
    assert load_requirements(session) == rows


def _all_required(config: JournalFieldsConfig) -> JournalFieldsConfig:
    return JournalFieldsConfig(
        fields=tuple(f.model_copy(update={"required": True}) for f in config.fields)
    )


def test_sql_filter_runs_for_every_real_field(session: Session) -> None:
    """Every field of the real journal_fields.yaml, made required, compiles and agrees
    with Python (catches a column type without an SQL empty check)."""
    account = add_account(session, "Alpha", 1)
    add_trade(session, account)
    add_trade(session, account, setup_context="", mistakes="", quality_rating=3)
    cfg = _all_required(load_journal_fields())
    since = {f.key: LATER for f in cfg.fields}
    assert _sql_ids(session, cfg, since) == _python_ids(session, cfg, since)
    for field in cfg.fields:
        one = {field.key: LATER}
        assert _sql_ids(session, cfg, one) == _python_ids(session, cfg, one), field.key


def test_sql_filter_auto_override(session: Session) -> None:
    """Auto field: effective value = override ?? value (a DB CHECK keeps '' out of the
    bias columns; the SQL check still treats '' as empty for string columns)."""
    account = add_account(session, "Alpha", 1)
    overridden = add_trade(session, account, bias_alignment_override="aligned")
    computed = add_trade(session, account, bias_alignment="counter")
    neither = add_trade(session, account)
    cfg = _all_required(load_journal_fields())
    since = {"bias_alignment": LATER}
    ids = _sql_ids(session, cfg, since)
    assert ids == _python_ids(session, cfg, since)
    assert ids == {neither.id}
    assert {overridden.id, computed.id}.isdisjoint(ids)


def test_sql_filter_key_without_column_is_empty(session: Session) -> None:
    """Hand-built config with a column key that is not a trades column: empty, as in Python."""
    account = add_account(session, "Alpha", 1)
    trade = add_trade(session, account)
    cfg = JournalFieldsConfig.model_validate(
        {
            "fields": [
                {
                    "key": "no_such_column",
                    "label": "x",
                    "type": "bool",
                    "required": True,
                    "analytics": False,
                    "storage": "column",
                }
            ]
        }
    )
    since = {"no_such_column": LATER}
    assert _sql_ids(session, cfg, since) == _python_ids(session, cfg, since) == {trade.id}
