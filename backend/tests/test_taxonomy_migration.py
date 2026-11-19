"""M8-04..M8-08 migration (one revision after c6f2a8d4e173, docs/api.md "Migration"):
the exact mappings of the old journal values and rule violations, the requirements rows
and the downgrade. Drift / roundtrip / single head: test_migrations.py."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text

from tests.conftest import alembic_config

# The head before this revision (the brief named e4a7c2f9b315, but a91d3c7e5f20 and
# c6f2a8d4e173 already follow it; revising it would create a second head).
BEFORE = "c6f2a8d4e173"
NEW_TEXT_COLUMNS = [
    "h1_context_other",
    "h4_context_other",
    "poi_types_other",
    "fvg_types_h1_other",
    "fvg_types_h4_other",
    "entry_model_other",
]
NEW_MULTI_COLUMNS = ["poi_types", "fvg_types_h1", "fvg_types_h4"]
# «Інше» texts get requirements rows too (review 2026-11-19).
NEW_TEXT_KEYS = (
    "h1_context_other",
    "h4_context_other",
    "poi_types_other",
    "fvg_types_h1_other",
    "fvg_types_h4_other",
    "entry_model_other",
)
NEW_COLUMNS = ["h1_context", "h4_context", *NEW_TEXT_COLUMNS, *NEW_MULTI_COLUMNS]
OLD_RISK_KEYS = [
    "daily_stop_loss_pct",
    "daily_stop_profit_pct",
    "weekly_stop_loss_pct",
    "weekly_stop_profit_pct",
]


@pytest.fixture(autouse=True)
def _restore_head(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))
        conn.execute(text("DELETE FROM journal_field_requirements"))
    command.upgrade(alembic_config(), "head")


def _account(conn: Connection) -> None:
    conn.execute(
        text(
            "INSERT INTO accounts (name, firm, program, phase, login, server, starting_balance,"
            " reference_balance, currency, status) VALUES ('A', 'F', 'P', 'phase_1', 1, 'S',"
            " 10000, 10000, 'USD', 'active')"
        )
    )


def _trade(conn: Connection, position: int, **columns: Any) -> int:
    names = ["account_id", "position_id", "symbol", "broker_symbol", "direction", "open_time"]
    names += ["close_time", "entry_price", "volume", "net_pnl", "status", *columns]
    values = [
        ":account",
        ":pos",
        "'XAUUSD'",
        "'XAUUSD'",
        "'buy'",
        "'2026-11-11T08:00Z'",
        "'2026-11-11T09:00Z'",
        "2650",
        "0.1",
        "-50",
        "'needs_description'",
        *(f":{c}" for c in columns),
    ]
    sql = f"INSERT INTO trades ({', '.join(names)}) VALUES ({', '.join(values)}) RETURNING id"  # noqa: S608
    return int(conn.execute(text(sql), {"account": 1, "pos": position, **columns}).scalar_one())


def _violation(conn: Connection, trade_id: int, key: str, source: str, details: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO rule_violations (trade_id, rule_key, source, details)"
            " VALUES (:t, :k, :s, :d)"
        ),
        {"t": trade_id, "k": key, "s": source, "d": details},
    )


def _row(conn: Connection, trade_id: int, *names: str) -> dict[str, Any]:
    sql = f"SELECT {', '.join(names)} FROM trades WHERE id = :id"  # noqa: S608
    return dict(conn.execute(text(sql), {"id": trade_id}).mappings().one())


def _violations(conn: Connection, trade_id: int) -> dict[str, tuple[str, str | None]]:
    rows = conn.execute(
        text("SELECT rule_key, source, details FROM rule_violations WHERE trade_id = :t"),
        {"t": trade_id},
    )
    return {r.rule_key: (r.source, r.details) for r in rows}


def _columns(db_engine: Engine) -> dict[str, str]:
    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute"
                " WHERE attrelid = 'trades'::regclass AND attnum > 0 AND NOT attisdropped"
            )
        )
        return dict(rows.all())


def test_the_new_revision_follows_the_previous_head() -> None:
    script = ScriptDirectory.from_config(alembic_config())
    head = script.get_current_head()
    assert head is not None

    assert head != BEFORE
    revision = script.get_revision(head)
    assert revision is not None
    assert revision.down_revision == BEFORE


def test_upgrade_adds_the_new_columns_with_the_contract_types(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), BEFORE)
    assert not set(NEW_COLUMNS) & set(_columns(db_engine))

    command.upgrade(alembic_config(), "head")

    columns = _columns(db_engine)
    for name in ("h1_context", "h4_context"):
        assert columns[name] == "character varying(50)"
    for name in NEW_TEXT_COLUMNS:
        assert columns[name] == "text"
    for name in NEW_MULTI_COLUMNS:
        assert columns[name] == "character varying(50)[]"
    for old in ("setup_context", "poi_type", "poi_type_other", "fvg_kind"):
        assert old in columns  # old columns are never dropped


# --- the data mappings ---


@pytest.fixture
def migrated(db_engine: Engine) -> dict[str, int]:
    """Real-shaped rows at the previous revision, then upgraded. Returns name -> trade id."""
    command.downgrade(alembic_config(), BEFORE)
    ids: dict[str, int] = {}
    with db_engine.begin() as conn:
        _account(conn)
        ids["yes_h1_updating"] = _trade(
            conn, 1, setup_context="yes", poi_type="fvg_h1", fvg_kind="fractal_updating"
        )
        ids["no_h4_post"] = _trade(
            conn, 2, setup_context="no", poi_type="fvg_h4", fvg_kind="post_manipulation"
        )
        ids["partially_other"] = _trade(
            conn, 3, setup_context="partially", poi_type="other", poi_type_other="OB H4"
        )
        ids["blank"] = _trade(conn, 4)
        ids["yes_other_post"] = _trade(
            conn,
            5,
            setup_context="yes",
            poi_type="other",
            poi_type_other="x",
            fvg_kind="post_manipulation",
        )
        ids["h1_na"] = _trade(conn, 6, poi_type="fvg_h1", fvg_kind="na")
        ids["yes_h4_updating"] = _trade(
            conn, 7, setup_context="yes", poi_type="fvg_h4", fvg_kind="fractal_updating"
        )
        ids["kind_without_poi"] = _trade(conn, 8, fvg_kind="fractal_updating")
        _violation(conn, ids["yes_h1_updating"], "weekly_stop_loss_pct", "auto", "week d")
        _violation(conn, ids["yes_h1_updating"], "max_risk_pct", "auto", "risk 2%")
        _violation(conn, ids["no_h4_post"], "daily_stop_loss_pct", "auto", "loss detail")
        _violation(conn, ids["no_h4_post"], "daily_stop_profit_pct", "user", "profit detail")
        _violation(conn, ids["partially_other"], "daily_stop_profit_pct", "auto", "p")
        _violation(conn, ids["yes_other_post"], "weekly_stop_profit_pct", "user", "wp")
        _violation(conn, ids["h1_na"], "weekly_stop_loss_pct", "auto", "wl")
        _violation(conn, ids["h1_na"], "weekly_stop_profit_pct", "auto", "wp")
        _violation(conn, ids["yes_h4_updating"], "daily_stop_loss_pct", "auto", None)
        old = datetime(2026, 1, 1, tzinfo=UTC)
        for key in ("setup_context", "poi_type", "fvg_kind", "entry_model"):
            conn.execute(
                text(
                    "INSERT INTO journal_field_requirements (key, required_since) VALUES (:k, :s)"
                ),
                {"k": key, "s": old},
            )
        conn.execute(
            text("INSERT INTO journal_field_requirements (key, required_since) VALUES (:k, :s)"),
            {"k": "h1_context", "s": datetime(2026, 1, 2, tzinfo=UTC)},
        )
        # A DB whose first requirements fill happened (DECISIONS 2026-11-19, RED gaps): only
        # then does the migration insert rows for the new required keys.
        _mark_first_fill_done(conn)
    command.upgrade(alembic_config(), "head")
    assert "poi_types" in _columns(db_engine)  # the upgrade really ran
    return ids


NEW = ("h1_context", "h4_context", "poi_types", "fvg_types_h1", "fvg_types_h4")
OLD = ("setup_context", "poi_type", "poi_type_other", "fvg_kind")


def test_setup_context_yes_becomes_flow_flow(db_engine: Engine, migrated: dict[str, int]) -> None:
    with db_engine.connect() as conn:
        row = _row(conn, migrated["yes_h1_updating"], "h1_context", "h4_context", "setup_context")

    assert row == {"h1_context": "flow", "h4_context": "flow", "setup_context": None}


@pytest.mark.parametrize("name", ["no_h4_post", "partially_other"])
def test_setup_context_no_and_partially_are_kept_as_legacy(
    db_engine: Engine, migrated: dict[str, int], name: str
) -> None:
    expected = {"no_h4_post": "no", "partially_other": "partially"}[name]

    with db_engine.connect() as conn:
        row = _row(conn, migrated[name], "h1_context", "h4_context", "setup_context")

    assert row == {"h1_context": None, "h4_context": None, "setup_context": expected}


def test_poi_type_moves_into_poi_types(db_engine: Engine, migrated: dict[str, int]) -> None:
    expected = {
        "yes_h1_updating": ["fvg_h1"],
        "no_h4_post": ["fvg_h4"],
        "partially_other": ["other"],
        "yes_other_post": ["other"],
        "h1_na": ["fvg_h1"],
        "yes_h4_updating": ["fvg_h4"],
        "blank": None,
        "kind_without_poi": None,
    }

    with db_engine.connect() as conn:
        for name, poi_types in expected.items():
            row = _row(conn, migrated[name], "poi_types", "poi_type", "poi_type_other")
            assert row["poi_types"] == poi_types, name
            assert row["poi_type"] is None, name
            assert row["poi_type_other"] is None, name


def test_poi_type_other_text_moves_to_poi_types_other(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    with db_engine.connect() as conn:
        a = _row(conn, migrated["partially_other"], "poi_types_other")
        b = _row(conn, migrated["yes_other_post"], "poi_types_other")
        c = _row(conn, migrated["no_h4_post"], "poi_types_other")

    assert a["poi_types_other"] == "OB H4"
    assert b["poi_types_other"] == "x"
    assert c["poi_types_other"] is None


def test_fvg_kind_moves_to_the_matching_fvg_types_column(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    expected = {
        "yes_h1_updating": (["fractal_updating"], None, None),
        "no_h4_post": (None, ["post_manipulation"], None),
        "yes_h4_updating": (None, ["fractal_updating"], None),
    }

    with db_engine.connect() as conn:
        for name, (h1, h4, kind) in expected.items():
            row = _row(conn, migrated[name], "fvg_types_h1", "fvg_types_h4", "fvg_kind")
            assert (row["fvg_types_h1"], row["fvg_types_h4"], row["fvg_kind"]) == (h1, h4, kind)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("h1_na", "na"),  # `na` has no option in the new field
        ("yes_other_post", "post_manipulation"),  # the POI is not an FVG
        ("kind_without_poi", "fractal_updating"),
    ],
)
def test_fvg_kind_that_cannot_be_mapped_exactly_is_kept_as_legacy(
    db_engine: Engine, migrated: dict[str, int], name: str, kind: str
) -> None:
    with db_engine.connect() as conn:
        row = _row(conn, migrated[name], "fvg_types_h1", "fvg_types_h4", "fvg_kind")

    assert row == {"fvg_types_h1": None, "fvg_types_h4": None, "fvg_kind": kind}


def test_blank_trade_stays_blank(db_engine: Engine, migrated: dict[str, int]) -> None:
    with db_engine.connect() as conn:
        row = _row(conn, migrated["blank"], *NEW, *OLD, "entry_model_other")

    assert all(value is None for value in row.values())


def test_no_empty_arrays_are_written(db_engine: Engine, migrated: dict[str, int]) -> None:
    with db_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM trades WHERE cardinality(poi_types) = 0"
                " OR cardinality(fvg_types_h1) = 0 OR cardinality(fvg_types_h4) = 0"
            )
        ).scalar_one()

    assert count == 0


# --- violations ---


def test_old_risk_violations_become_daily_and_weekly_risk(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    with db_engine.connect() as conn:
        weekly = _violations(conn, migrated["yes_h1_updating"])
        daily_auto = _violations(conn, migrated["partially_other"])
        weekly_user = _violations(conn, migrated["yes_other_post"])

    assert weekly["weekly_risk"] == ("auto", "weekly_stop_loss_pct: week d")
    assert weekly["max_risk_pct"] == ("auto", "risk 2%")  # unrelated keys are untouched
    assert daily_auto == {"daily_risk": ("auto", "daily_stop_profit_pct: p")}
    assert weekly_user == {"weekly_risk": ("user", "weekly_stop_profit_pct: wp")}


def test_two_daily_rows_of_one_trade_merge_and_user_wins(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    with db_engine.connect() as conn:
        rows = _violations(conn, migrated["no_h4_post"])

    assert set(rows) == {"daily_risk"}
    source, details = rows["daily_risk"]
    assert source == "user"
    assert details is not None
    assert set(details.split("; ")) == {
        "daily_stop_loss_pct: loss detail",
        "daily_stop_profit_pct: profit detail",
    }


def test_two_weekly_auto_rows_merge_into_one_auto_row(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    with db_engine.connect() as conn:
        rows = _violations(conn, migrated["h1_na"])

    source, details = rows["weekly_risk"]
    assert set(rows) == {"weekly_risk"}
    assert source == "auto"
    assert details is not None
    assert set(details.split("; ")) == {"weekly_stop_loss_pct: wl", "weekly_stop_profit_pct: wp"}


def test_old_row_without_details_still_names_the_old_key(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    with db_engine.connect() as conn:
        rows = _violations(conn, migrated["yes_h4_updating"])

    source, details = rows["daily_risk"]
    assert source == "auto"
    assert details is not None
    assert details.startswith("daily_stop_loss_pct")


def test_no_row_keeps_an_old_risk_key(db_engine: Engine, migrated: dict[str, int]) -> None:
    with db_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM rule_violations WHERE rule_key = ANY(:keys)"),
            {"keys": OLD_RISK_KEYS},
        ).scalar_one()
        total = conn.execute(text("SELECT count(*) FROM rule_violations")).scalar_one()

    assert count == 0
    assert total == 7  # 9 rows, minus 2 merged pairs, the unrelated max_risk_pct stays


# --- requirements ---


def _mark_first_fill_done(conn: Connection) -> None:
    conn.execute(
        text("UPDATE journal_requirements_state SET initial_fill_at = :s"),
        {"s": datetime(2026, 1, 1, tzinfo=UTC)},
    )


def _requirements(db_engine: Engine) -> dict[str, datetime]:
    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT key, required_since FROM journal_field_requirements"))
        return {r.key: r.required_since for r in rows}


def test_requirements_rows_for_the_new_required_keys_are_inserted_with_now(
    db_engine: Engine,
) -> None:
    # Adjusted to DECISIONS 2026-11-19 (RED gaps): ALL five new required keys get a row
    # (show_if fields are required when shown, so old FVG trades must not become incomplete),
    # and only when the first fill already happened (initial_fill_at set).
    command.downgrade(alembic_config(), BEFORE)
    with db_engine.begin() as conn:
        _mark_first_fill_done(conn)
    lo = datetime.now(UTC) - timedelta(minutes=1)

    command.upgrade(alembic_config(), "head")

    rows = _requirements(db_engine)
    hi = datetime.now(UTC) + timedelta(minutes=1)
    for key in ("h1_context", "h4_context", "poi_types", "fvg_types_h1", "fvg_types_h4"):
        assert lo <= rows[key] <= hi, key
    for key in NEW_TEXT_KEYS:
        assert lo <= rows[key] <= hi, key


def test_requirements_rows_are_not_inserted_before_the_first_fill(db_engine: Engine) -> None:
    """A fresh DB (initial_fill_at NULL) keeps the 1970 first-fill rule of the M3-07 sync."""
    command.downgrade(alembic_config(), BEFORE)

    command.upgrade(alembic_config(), "head")

    assert not set(_requirements(db_engine)) & {
        "h1_context",
        "h4_context",
        "poi_types",
        "fvg_types_h1",
        "fvg_types_h4",
        *NEW_TEXT_KEYS,
    }


def test_downgrade_deletes_the_requirements_rows_of_the_new_keys(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), BEFORE)
    with db_engine.begin() as conn:
        _mark_first_fill_done(conn)
    command.upgrade(alembic_config(), "head")
    assert set(NEW_TEXT_KEYS) <= set(_requirements(db_engine))

    command.downgrade(alembic_config(), BEFORE)

    left = set(_requirements(db_engine))
    assert not left & {*NEW_TEXT_KEYS, "h1_context", "h4_context", "poi_types"}


def test_requirements_existing_rows_win_and_removed_keys_are_deleted(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    rows = _requirements(db_engine)

    assert rows["entry_model"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert rows["h1_context"] == datetime(2026, 1, 2, tzinfo=UTC)  # ON CONFLICT DO NOTHING
    assert {"h4_context", "poi_types"} <= set(rows)
    assert not set(rows) & {"setup_context", "poi_type", "fvg_kind"}


# --- downgrade ---


def test_downgrade_restores_old_columns_where_one_value_exists(db_engine: Engine) -> None:
    command.downgrade(alembic_config(), BEFORE)
    with db_engine.begin() as conn:
        _account(conn)
    command.upgrade(alembic_config(), "head")
    ids: dict[str, int] = {}
    with db_engine.begin() as conn:
        cast = {c: f"CAST(:{c} AS varchar[])" for c in NEW_MULTI_COLUMNS}

        def new_trade(position: int, **columns: Any) -> int:
            names = ["account_id", "position_id", "symbol", "broker_symbol", "direction"]
            names += ["open_time", "close_time", "entry_price", "volume", "net_pnl", "status"]
            marks = [":account", ":pos", "'X'", "'X'", "'buy'", "'2026-11-11T08:00Z'"]
            marks += ["'2026-11-11T09:00Z'", "1", "0.1", "-1", "'needs_description'"]
            for column in columns:
                names.append(column)
                marks.append(cast.get(column, f":{column}"))
            sql = (
                f"INSERT INTO trades ({', '.join(names)}) VALUES ({', '.join(marks)}) RETURNING id"  # noqa: S608
            )
            params = {"account": 1, "pos": position, **columns}
            return int(conn.execute(text(sql), params).scalar_one())

        ids["flow_flow"] = new_trade(1, h1_context="flow", h4_context="flow")
        ids["flow_reversal"] = new_trade(2, h1_context="flow", h4_context="reversal")
        ids["legacy_no"] = new_trade(3, setup_context="no")
        ids["multi_poi"] = new_trade(
            4, poi_types=["fvg_h4", "fractal_h1"], fvg_types_h4=["post_manipulation"]
        )
        ids["other_poi"] = new_trade(5, poi_types=["other"], poi_types_other="OB")
        ids["two_fvg_types"] = new_trade(
            6, poi_types=["fvg_h1"], fvg_types_h1=["fractal_updating", "post_manipulation"]
        )
        ids["legacy_kind"] = new_trade(7, fvg_kind="na", poi_types=["fvg_h1"])
        ids["other_not_first"] = new_trade(
            8, poi_types=["fvg_h1", "other"], poi_types_other="OB H4", fvg_types_h1=["other"]
        )
        ids["fvg_list_without_fvg_poi"] = new_trade(
            9, poi_types=["fractal_h1"], fvg_types_h1=["post_manipulation"]
        )
        _violation(conn, ids["flow_flow"], "daily_risk", "auto", "daily_stop_loss_pct: x")
        _violation(conn, ids["flow_reversal"], "weekly_risk", "user", "weekly_stop_profit_pct: y")
        _violation(conn, ids["legacy_no"], "max_risk_pct", "auto", "risk")

    command.downgrade(alembic_config(), BEFORE)

    assert not set(NEW_COLUMNS) & set(_columns(db_engine))
    with db_engine.connect() as conn:

        def old(name: str) -> dict[str, Any]:
            return _row(conn, ids[name], "setup_context", "poi_type", "poi_type_other", "fvg_kind")

        assert old("flow_flow") == dict.fromkeys(OLD) | {"setup_context": "yes"}
        assert old("flow_reversal")["setup_context"] is None
        assert old("legacy_no")["setup_context"] == "no"
        # extra multi values are lost: the first one is restored
        assert old("multi_poi")["poi_type"] == "fvg_h4"
        assert old("multi_poi")["fvg_kind"] == "post_manipulation"
        assert old("other_poi")["poi_type"] == "other"
        assert old("other_poi")["poi_type_other"] == "OB"
        assert old("two_fvg_types")["poi_type"] == "fvg_h1"
        assert old("two_fvg_types")["fvg_kind"] is None  # not one value: not restored
        assert old("legacy_kind")["fvg_kind"] == "na"
        # the «Інше» text belongs to `other`: lost when `other` is not the first POI
        assert old("other_not_first")["poi_type"] == "fvg_h1"
        assert old("other_not_first")["poi_type_other"] is None
        # fvg_kind only for an FVG POI (the restored poi_type is fractal_h1)
        assert old("fvg_list_without_fvg_poi")["poi_type"] == "fractal_h1"
        assert old("fvg_list_without_fvg_poi")["fvg_kind"] is None
        assert _violations(conn, ids["flow_flow"]) == {"daily_stop_loss_pct": ("auto", "x")}
        assert _violations(conn, ids["flow_reversal"]) == {"weekly_stop_profit_pct": ("user", "y")}
        assert _violations(conn, ids["legacy_no"]) == {"max_risk_pct": ("auto", "risk")}


def test_downgrade_of_migrated_data_restores_the_exact_old_values(
    db_engine: Engine, migrated: dict[str, int]
) -> None:
    command.downgrade(alembic_config(), BEFORE)

    with db_engine.connect() as conn:
        for name, setup, poi, other, kind in [
            ("yes_h1_updating", "yes", "fvg_h1", None, "fractal_updating"),
            ("no_h4_post", "no", "fvg_h4", None, "post_manipulation"),
            ("partially_other", "partially", "other", "OB H4", None),
            ("blank", None, None, None, None),
            ("yes_other_post", "yes", "other", "x", "post_manipulation"),
            ("h1_na", None, "fvg_h1", None, "na"),
            ("yes_h4_updating", "yes", "fvg_h4", None, "fractal_updating"),
            ("kind_without_poi", None, None, None, "fractal_updating"),
        ]:
            row = _row(
                conn, migrated[name], "setup_context", "poi_type", "poi_type_other", "fvg_kind"
            )
            assert tuple(row.values()) == (setup, poi, other, kind), name
        merged = _violations(conn, migrated["no_h4_post"])
        assert "daily_risk" not in merged
        assert "daily_stop_loss_pct" in merged  # the first prefix of the merged details
