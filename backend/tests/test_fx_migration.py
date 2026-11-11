"""M5-09 migration: table fx_rates and symbol_specs.mt5_loss_per_tick(_at).

Follows 5d2e8b1c4a90 (canonical symbols). Model/migration drift, the full roundtrip and the
single head are covered by test_migrations.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Numeric, inspect, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, FxRate, SymbolSpec
from tests.conftest import alembic_config

D = Decimal
BEFORE = "5d2e8b1c4a90"
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
FX_COLUMNS = {
    "id",
    "account_id",
    "from_currency",
    "to_currency",
    "pair",
    "inverted",
    "bid",
    "ask",
    "rate",
    "rate_at",
    "synced_at",
}


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


def account(db: Session) -> Account:
    row = Account(
        name="M5-09 migration",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase="phase_1",
        login=987654331,
        server="FundedNext-Server",
        starting_balance=D("100000"),
        currency="USD",
    )
    db.add(row)
    db.commit()
    return row


def fx(acc: Account, **changes: Any) -> FxRate:
    values: dict[str, Any] = {
        "account_id": acc.id,
        "from_currency": "EUR",
        "to_currency": "USD",
        "pair": "EURUSD",
        "inverted": False,
        "bid": D("1.10905"),
        "ask": D("1.1091"),
        "rate": D("1.1091"),
        "rate_at": NOW,
        "synced_at": NOW,
    }
    return FxRate(**(values | changes))


def spec(acc: Account, **changes: Any) -> SymbolSpec:
    values: dict[str, Any] = {
        "account_id": acc.id,
        "symbol": "GER30",
        "contract_size": D("10"),
        "tick_size": D("0.01"),
        "tick_value": D("0.12"),
        "volume_min": D("0.01"),
        "volume_step": D("0.01"),
        "volume_max": D("100"),
        "digits": 2,
        "currency_profit": "EUR",
        "currency_margin": "EUR",
        "synced_at": NOW,
    }
    return SymbolSpec(**(values | changes))


# --- revision / schema -------------------------------------------------------------------------


def test_a_revision_follows_5d2e8b1c4a90() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    children = [r for r in script.walk_revisions() if r.down_revision == BEFORE]

    assert len(children) == 1
    assert script.get_current_head() is not None


def test_head_has_the_fx_rates_table_and_the_check_columns(db_engine: Engine) -> None:
    insp = inspect(db_engine)

    assert {c["name"] for c in insp.get_columns("fx_rates")} == FX_COLUMNS
    columns = {c["name"]: c for c in insp.get_columns("symbol_specs")}
    for name in ("mt5_loss_per_tick", "mt5_loss_per_tick_at"):
        assert name in columns, name
        assert columns[name]["nullable"] is True, name


def test_rate_column_is_numeric_20_8_and_not_null(db_engine: Engine) -> None:
    columns = {c["name"]: c for c in inspect(db_engine).get_columns("fx_rates")}

    assert columns["rate"]["nullable"] is False
    rate_type = columns["rate"]["type"]
    assert isinstance(rate_type, Numeric)
    assert (rate_type.precision, rate_type.scale) == (20, 8)
    spec_cols = {c["name"]: c for c in inspect(db_engine).get_columns("symbol_specs")}
    check_type = spec_cols["mt5_loss_per_tick"]["type"]
    assert isinstance(check_type, Numeric)
    assert (check_type.precision, check_type.scale) == (20, 8)


# --- fx_rates constraints ----------------------------------------------------------------------


def test_a_valid_rate_row_roundtrips(db_session: Session) -> None:
    acc = account(db_session)
    db_session.add(fx(acc))
    db_session.commit()

    row = db_session.query(FxRate).one()

    assert (row.from_currency, row.to_currency, row.rate) == ("EUR", "USD", D("1.1091"))


def test_unique_per_account_from_and_to_currency(db_session: Session) -> None:
    acc = account(db_session)
    db_session.add(fx(acc))
    db_session.commit()
    db_session.add(fx(acc, pair="EURUSD.r"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_another_currency_or_account_may_have_its_own_row(db_session: Session) -> None:
    acc = account(db_session)
    db_session.add_all([fx(acc), fx(acc, from_currency="GBP", pair="GBPUSD")])
    db_session.commit()

    assert db_session.query(FxRate).count() == 2


@pytest.mark.parametrize("bad", [D("0"), D("-1.1"), D("NaN")])
def test_rate_must_be_positive(db_session: Session, bad: Decimal) -> None:
    acc = account(db_session)
    db_session.add(fx(acc, rate=bad))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("column", ["bid", "ask", "rate"])
@pytest.mark.parametrize("bad", [D("Infinity"), D("-Infinity")])
def test_infinite_prices_are_rejected(db_session: Session, column: str, bad: Decimal) -> None:
    # NUMERIC(20,8) cannot hold an infinite value (DataError before the CHECK runs).
    acc = account(db_session)
    db_session.add(fx(acc, **{column: bad}))

    with pytest.raises(DataError):
        db_session.commit()


@pytest.mark.parametrize(("source", "target"), [("EUR", "EUR"), ("eur", "EUR")])
def test_a_rate_row_needs_two_different_currencies(
    db_session: Session, source: str, target: str
) -> None:
    acc = account(db_session)
    db_session.add(fx(acc, from_currency=source, to_currency=target, pair="EUREUR"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_the_account_deletes_its_rates(db_session: Session, db_engine: Engine) -> None:
    acc = account(db_session)
    db_session.add(fx(acc))
    db_session.commit()
    acc_id = acc.id

    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": acc_id})

    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM fx_rates")).scalar_one() == 0


def test_a_rate_needs_an_existing_account(db_session: Session) -> None:
    db_session.add(FxRate(**_values(account_id=999999)))

    with pytest.raises(IntegrityError):
        db_session.commit()


def _values(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "from_currency": "EUR",
        "to_currency": "USD",
        "pair": "EURUSD",
        "inverted": False,
        "bid": D("1.1"),
        "ask": D("1.1"),
        "rate": D("1.1"),
        "rate_at": NOW,
        "synced_at": NOW,
    }
    return values | changes


# --- symbol_specs check columns ----------------------------------------------------------------


def test_check_value_and_time_set_together_are_accepted(db_session: Session) -> None:
    acc = account(db_session)
    db_session.add(spec(acc, mt5_loss_per_tick=D("0.11091"), mt5_loss_per_tick_at=NOW))
    db_session.commit()

    row = db_session.query(SymbolSpec).one()

    assert (row.mt5_loss_per_tick, row.mt5_loss_per_tick_at) == (D("0.11091"), NOW)


def test_check_columns_default_to_null(db_session: Session) -> None:
    acc = account(db_session)
    db_session.add(spec(acc))
    db_session.commit()

    row = db_session.query(SymbolSpec).one()

    assert (row.mt5_loss_per_tick, row.mt5_loss_per_tick_at) == (None, None)


@pytest.mark.parametrize(
    "changes",
    [
        {"mt5_loss_per_tick": D("0.11")},  # value without time
        {"mt5_loss_per_tick_at": NOW},  # time without value
    ],
)
def test_check_value_and_time_are_both_null_or_both_set(
    db_session: Session, changes: dict[str, Any]
) -> None:
    acc = account(db_session)
    db_session.add(spec(acc, **changes))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("bad", [D("0"), D("-0.1"), D("NaN")])
def test_check_value_must_be_positive(db_session: Session, bad: Decimal) -> None:
    acc = account(db_session)
    db_session.add(spec(acc, mt5_loss_per_tick=bad, mt5_loss_per_tick_at=NOW))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("bad", [D("Infinity"), D("-Infinity")])
def test_infinite_check_value_is_rejected(db_session: Session, bad: Decimal) -> None:
    # NUMERIC(20,8) cannot hold an infinite value (DataError before the CHECK runs).
    acc = account(db_session)
    db_session.add(spec(acc, mt5_loss_per_tick=bad, mt5_loss_per_tick_at=NOW))

    with pytest.raises(DataError):
        db_session.commit()


# --- downgrade ---------------------------------------------------------------------------------


def test_downgrade_drops_the_table_and_the_columns_and_upgrade_restores_them(
    db_engine: Engine,
) -> None:
    cfg = alembic_config()
    try:
        command.downgrade(cfg, BEFORE)

        insp = inspect(db_engine)
        assert "fx_rates" not in insp.get_table_names()
        names = {c["name"] for c in insp.get_columns("symbol_specs")}
        assert not names & {"mt5_loss_per_tick", "mt5_loss_per_tick_at"}
        assert "canonical_symbol" in names  # the earlier revision is intact
    finally:
        command.upgrade(cfg, "head")

    assert "fx_rates" in inspect(db_engine).get_table_names()
