"""The cTrader columns on `accounts`: defaults, constraints and a reversible migration."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import alembic_config

REVISION = "f1a2b3c4d5e6"
PREVIOUS = "e7c41b9a2d60"
_INSERT = text(
    "INSERT INTO accounts (name, firm, program, phase, login, server, starting_balance, "
    "currency, reference_balance, platform, ctid_trader_account_id, ctrader_is_live) VALUES "
    "(:name, 'F', 'P', 'phase_1', :login, 'S', 1000, 'USD', 1000, :platform, :ctid, :live)"
)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


def _insert(engine: Engine, **overrides: Any) -> None:
    values = {"name": "A", "login": 1, "platform": "ctrader", "ctid": 10, "live": False}
    with engine.begin() as conn:
        conn.execute(_INSERT, values | overrides)


def test_existing_style_insert_defaults_to_mt5(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (name, firm, program, phase, login, server, "
                "starting_balance, currency, reference_balance) VALUES "
                "('M', 'F', 'P', 'phase_1', 5, 'S', 1000, 'USD', 1000)"
            )
        )
        row = conn.execute(
            text("SELECT platform, ctid_trader_account_id, ctrader_is_live FROM accounts")
        ).one()
    assert tuple(row) == ("mt5", None, None)


def test_valid_ctrader_row(db_engine: Engine) -> None:
    _insert(db_engine)


@pytest.mark.parametrize(
    "overrides",
    [
        {"platform": "other"},
        {"ctid": None},
        {"live": None},
        {"platform": "mt5"},
        {"platform": "mt5", "ctid": None},
        {"platform": "mt5", "live": None},
    ],
)
def test_constraint_refuses(db_engine: Engine, overrides: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        _insert(db_engine, **overrides)


def test_ctid_is_unique_when_set(db_engine: Engine) -> None:
    _insert(db_engine)
    with pytest.raises(IntegrityError):
        _insert(db_engine, name="B", login=2)


def test_many_mt5_rows_have_a_null_ctid(db_engine: Engine) -> None:
    _insert(db_engine, platform="mt5", ctid=None, live=None)
    _insert(db_engine, name="B", login=2, platform="mt5", ctid=None, live=None)


def test_downgrade_removes_the_columns_and_upgrade_restores_them(db_engine: Engine) -> None:
    _insert(db_engine, platform="mt5", ctid=None, live=None)
    cfg = alembic_config()
    try:
        command.downgrade(cfg, PREVIOUS)
        columns = {c["name"] for c in inspect(db_engine).get_columns("accounts")}
        assert not columns & {"platform", "ctid_trader_account_id", "ctrader_is_live"}
    finally:
        command.upgrade(cfg, "head")
    columns = {c["name"] for c in inspect(db_engine).get_columns("accounts")}
    assert {"platform", "ctid_trader_account_id", "ctrader_is_live"} <= columns
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT platform FROM accounts")).scalar_one() == "mt5"


def test_downgrade_refuses_while_ctrader_accounts_exist(db_engine: Engine) -> None:
    """Dropping the columns would silently turn a cTrader account into an MT5 one."""
    _insert(db_engine)
    cfg = alembic_config()
    try:
        with pytest.raises(RuntimeError, match="cTrader"):
            command.downgrade(cfg, PREVIOUS)
        columns = {c["name"] for c in inspect(db_engine).get_columns("accounts")}
        assert "platform" in columns
    finally:
        command.upgrade(cfg, "head")
