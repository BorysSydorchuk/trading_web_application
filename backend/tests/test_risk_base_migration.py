"""M5-10 migration: accounts.reference_balance = account size, NOT NULL; trades % recomputed.

Follows f6ea0d1af419 (M5-09 fx_rates). The new revision (id chosen by the backend-dev) must:
- backfill ``accounts.reference_balance = starting_balance`` where NULL (non-null values kept);
- recompute ``trades.risk_pct = risk_amount / reference_balance * 100`` and
  ``trades.pnl_pct = net_pnl / reference_balance * 100`` (4 dp, ROUND half away from zero,
  i.e. ROUND_HALF_UP also for negative values; NULL risk / pnl give NULL);
- make ``reference_balance`` NOT NULL. No CHECK constraint is added (the calculator guards a
  non-positive / NaN size, test_calculator_api.py).
Downgrade makes the column nullable again; values (and the recomputed percents) stay.
Model/migration drift, the full roundtrip and the single head: test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine.interfaces import ReflectedColumn
from sqlalchemy.exc import IntegrityError

from tests.conftest import alembic_config

D = Decimal
BEFORE = "f6ea0d1af419"


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


def _ref_column(engine: Engine) -> ReflectedColumn:
    columns = inspect(engine).get_columns("accounts")
    return next(c for c in columns if c["name"] == "reference_balance")


def test_exactly_one_revision_follows_f6ea0d1af419() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    children = [r for r in script.walk_revisions() if r.down_revision == BEFORE]

    assert len(children) == 1


def test_head_has_a_not_null_reference_balance(db_engine: Engine) -> None:
    assert _ref_column(db_engine)["nullable"] is False


def _account(conn: Any, name: str, login: int, starting: str, reference: str | None) -> int:
    new_id: int = conn.execute(
        text(
            "INSERT INTO accounts (name, firm, program, phase, login, server, "
            "starting_balance, currency, reference_balance) VALUES "
            "(:name, 'FundedNext', 'Stellar 2-Step', 'phase_1', :login, 'FundedNext-Server', "
            ":starting, 'USD', :ref) RETURNING id"
        ),
        {"name": name, "login": login, "starting": starting, "ref": reference},
    ).scalar_one()
    return new_id


def _trade(
    conn: Any,
    account_id: int,
    position_id: int,
    *,
    risk: str | None,
    risk_pct: str | None,
    net: str | None,
    pnl_pct: str | None,
    closed: bool = True,
) -> None:
    conn.execute(
        text(
            "INSERT INTO trades (account_id, position_id, symbol, broker_symbol, direction, "
            "open_time, close_time, entry_price, volume, status, balance_at_open, "
            "risk_amount, risk_pct, net_pnl, pnl_pct) VALUES (:a, :p, 'XAUUSD', 'XAUUSD', "
            "'buy', '2026-11-02 08:00+00', :closed_at, 2650, 1, :status, 10401.70, "
            ":risk, :rp, :net, :np)"
        ),
        {
            "a": account_id,
            "p": position_id,
            "closed_at": "2026-11-02 09:00+00" if closed else None,
            "status": "needs_description" if closed else "open",
            "risk": risk,
            "rp": risk_pct,
            "net": net,
            "np": pnl_pct,
        },
    )


def _seed_old_rows(engine: Engine) -> dict[str, int]:
    with engine.begin() as conn:
        null_ref = _account(conn, "null reference", 987650001, "10000.00", None)
        kept = _account(conn, "kept reference", 987650002, "5000.00", "20000.00")
        _trade(  # old base was balance_at_open 10401.70: 100 / 10401.70 = 0.9614
            conn, null_ref, 1, risk="100.00", risk_pct="0.9614", net="200.00", pnl_pct="1.9228"
        )
        _trade(conn, null_ref, 2, risk="0.00", risk_pct="0.0000", net="-300.00", pnl_pct="-2.8842")
        _trade(conn, null_ref, 3, risk=None, risk_pct=None, net=None, pnl_pct=None, closed=False)
        _trade(  # exact ties at the 5th decimal: x / 20000 * 100 = 0.00005
            conn, kept, 4, risk="0.01", risk_pct="0.0001", net="-0.01", pnl_pct="-0.0001"
        )
        _trade(conn, kept, 5, risk="0.03", risk_pct="9.0000", net="0.01", pnl_pct="9.0000")
        _trade(conn, kept, 6, risk=None, risk_pct=None, net="150.00", pnl_pct="0.0100")
        _trade(  # open trade with a (floating) net P&L: no P&L %, like the sync
            conn, kept, 7, risk="0.03", risk_pct="9.0000", net="50.00", pnl_pct=None, closed=False
        )
        _trade(  # -0.03 / 20000 * 100 = -0.00015 -> -0.0002 (half away from zero)
            conn, kept, 8, risk=None, risk_pct="5.0000", net="-0.03", pnl_pct="9.0000"
        )
        bad = {
            "zero": _account(conn, "zero size", 987650004, "10000.00", "0.00"),
            "negative": _account(conn, "negative size", 987650005, "10000.00", "-5.00"),
            "nan": _account(conn, "nan size", 987650006, "10000.00", "NaN"),
        }
        for offset, account_id in enumerate(bad.values()):
            _trade(
                conn,
                account_id,
                20 + offset,
                risk="100.00",
                risk_pct="9.0000",
                net="-300.00",
                pnl_pct="8.0000",
            )
    return {"null": null_ref, "kept": kept} | bad


def _pcts(engine: Engine, position_id: int) -> tuple[Decimal | None, Decimal | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT risk_pct, pnl_pct FROM trades WHERE position_id = :p"), {"p": position_id}
        ).one()
    return row[0], row[1]


def test_upgrade_backfills_the_size_and_recomputes_percents(db_engine: Engine) -> None:
    cfg = alembic_config()
    try:
        command.downgrade(cfg, BEFORE)
        assert _ref_column(db_engine)["nullable"] is True
        ids = _seed_old_rows(db_engine)

        command.upgrade(cfg, "head")

        assert _ref_column(db_engine)["nullable"] is False
        with db_engine.connect() as conn:
            sizes: dict[int, Decimal] = dict(
                conn.execute(text("SELECT id, reference_balance FROM accounts")).all()
            )
        assert sizes[ids["null"]] == D("10000.00")
        assert sizes[ids["kept"]] == D("20000.00")
        assert _pcts(db_engine, 1) == (D("1.0000"), D("2.0000"))
        assert _pcts(db_engine, 2) == (D("0.0000"), D("-3.0000"))
        assert _pcts(db_engine, 3) == (None, None)
        # 0.01 / 20000 * 100 = 0.00005 -> half away from zero, also for negative values.
        assert _pcts(db_engine, 4) == (D("0.0001"), D("-0.0001"))
        assert _pcts(db_engine, 5) == (D("0.0002"), D("0.0001"))  # 0.00015 -> 0.0002; 0.00005
        # risk NULL stays NULL; pnl uses the size: 150 / 20000 * 100 = 0.75
        assert _pcts(db_engine, 6) == (None, D("0.7500"))
        assert _pcts(db_engine, 7) == (D("0.0002"), None)  # open trade: P&L % stays NULL
        assert _pcts(db_engine, 8) == (None, D("-0.0002"))  # NULL risk -> NULL risk %
        # Size <= 0 or NaN: the account is skipped, its stored percents are kept.
        for position_id in (20, 21, 22):
            assert _pcts(db_engine, position_id) == (D("9.0000"), D("8.0000"))
    finally:
        command.upgrade(cfg, "head")


def test_a_null_reference_balance_is_rejected_at_head(db_engine: Engine) -> None:
    with pytest.raises(IntegrityError), db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (name, firm, program, phase, login, server, "
                "starting_balance, currency, reference_balance) VALUES ('null size', 'F', 'P', "
                "'phase_1', 987650009, 'S', 1000, 'USD', NULL)"
            )
        )


def test_downgrade_makes_the_column_nullable_and_keeps_values(db_engine: Engine) -> None:
    cfg = alembic_config()
    try:
        with db_engine.begin() as conn:
            _account(conn, "keep on downgrade", 987650003, "10000.00", "12345.67")

        command.downgrade(cfg, BEFORE)

        assert _ref_column(db_engine)["nullable"] is True
        with db_engine.connect() as conn:
            value = conn.execute(text("SELECT reference_balance FROM accounts")).scalar_one()
        assert value == D("12345.67")
    finally:
        command.upgrade(cfg, "head")
    assert _ref_column(db_engine)["nullable"] is False
