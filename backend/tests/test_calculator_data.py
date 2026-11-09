"""Calculator persistence invariants; synthetic records, no terminal operations."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, delete, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, CalculatorMarginRequest, SymbolSpec
from app.services.sync import _upsert_specs
from tests.conftest import alembic_config
from tests.mt5.factories import legacy_spec

NOW = datetime(2026, 11, 8, 10, tzinfo=UTC)
# Revision before the calculator migration (its down_revision).
_BEFORE_CALCULATOR = "b6d41a9e2c57"
# Calculator migration, before samples and request signatures were dropped.
_WITH_MARGIN_SAMPLES = "c8a41e62b903"
_REQUESTS = "calculator_margin_requests"


@pytest.fixture
def account(db_session: Session) -> Account:
    row = Account(
        name="Calculator synthetic",
        firm="Fixture",
        program="Fixture",
        phase="phase_1",
        login=987654321,
        server="Fixture",
        starting_balance=Decimal("10000"),
        currency="USD",
    )
    db_session.add(row)
    db_session.flush()
    return row


def request_values(account: Account, **changes: Any) -> dict[str, Any]:
    return {
        "account_id": account.id,
        "symbol": "GER40.cash",
        "direction": "buy",
        "volume": Decimal("0.01"),
        "entry": Decimal("19000.5"),
        "currency": "USD",
        "status": "pending",
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=1),
    } | changes


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"status": "processing", "started_at": NOW},
        {"status": "done", "started_at": NOW, "finished_at": NOW, "margin": Decimal("0")},
        {"status": "failed", "started_at": NOW, "finished_at": NOW, "error_code": "mt5_error"},
        {"status": "expired", "finished_at": NOW, "error_code": "request_expired"},
    ],
)
def test_valid_request_lifecycle_snapshots(
    db_session: Session,
    account: Account,
    changes: dict[str, Any],
) -> None:
    row = CalculatorMarginRequest(**request_values(account, **changes))
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.entry == Decimal("19000.5")
    assert row.created_at == NOW


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unknown"},
        {"direction": "hold"},
        {"volume": Decimal("0")},
        {"entry": Decimal("0")},
        {"entry": Decimal("NaN")},
        {"volume": Decimal("NaN")},
        {"symbol": ""},
        {"currency": ""},
        {"margin": Decimal("1")},
        {"finished_at": NOW},
        {"started_at": NOW},
        {"error_code": "mt5_error"},
        {"status": "processing"},
        {"status": "done", "started_at": NOW, "finished_at": NOW},
        {"status": "done", "finished_at": NOW, "margin": Decimal("1")},
        {"status": "done", "started_at": NOW, "finished_at": NOW, "margin": Decimal("-1")},
        {"status": "done", "started_at": NOW, "finished_at": NOW, "margin": Decimal("NaN")},
        {
            "status": "done",
            "started_at": NOW,
            "finished_at": NOW,
            "margin": Decimal("1"),
            "error_code": "mt5_error",
        },
        {"status": "failed", "finished_at": NOW},
        {"status": "expired", "finished_at": NOW},
        {"expires_at": NOW},
        {"status": "processing", "started_at": NOW - timedelta(seconds=1)},
        {
            "status": "failed",
            "started_at": NOW + timedelta(seconds=1),
            "finished_at": NOW,
            "error_code": "mt5_error",
        },
    ],
)
def test_invalid_request_states_rejected(
    db_session: Session,
    account: Account,
    changes: dict[str, Any],
) -> None:
    db_session.add(CalculatorMarginRequest(**request_values(account, **changes)))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_account_delete_cascades_margin_requests(db_session: Session, account: Account) -> None:
    db_session.add(CalculatorMarginRequest(**request_values(account)))
    db_session.flush()
    db_session.execute(delete(Account).where(Account.id == account.id))
    assert db_session.scalar(select(CalculatorMarginRequest.id)) is None


@pytest.mark.parametrize("value", [Decimal("Infinity"), Decimal("-Infinity")])
@pytest.mark.parametrize("field", ["margin", "volume", "entry"])
def test_infinite_request_numbers_rejected(
    db_session: Session,
    account: Account,
    value: Decimal,
    field: str,
) -> None:
    values = request_values(
        account, status="done", started_at=NOW, finished_at=NOW, margin=Decimal("1")
    )
    values[field] = value
    db_session.add(CalculatorMarginRequest(**values))
    with pytest.raises((IntegrityError, DataError)):
        db_session.flush()


def test_sync_stores_distinct_metadata_and_clears_missing_values(
    db_session: Session,
    account: Account,
) -> None:
    old = legacy_spec()
    _upsert_specs(db_session, account.id, [old], NOW)
    db_session.flush()
    row = db_session.scalar(select(SymbolSpec).where(SymbolSpec.account_id == account.id))
    assert row is not None
    assert row.point is None
    assert row.tick_value_loss is None
    actual = replace(old, point=Decimal("0.1"), tick_value_loss=Decimal("2.5"))
    _upsert_specs(db_session, account.id, [actual], NOW + timedelta(seconds=1))
    db_session.flush()
    db_session.refresh(row)
    assert row.point == Decimal("0.1")
    assert row.tick_value_loss == Decimal("2.5")
    assert row.tick_value == old.tick_value
    _upsert_specs(db_session, account.id, [old], NOW + timedelta(seconds=2))
    db_session.flush()
    db_session.refresh(row)
    assert row.point is None
    assert row.tick_value_loss is None


def test_request_queue_index(db_engine: Engine) -> None:
    indexes = inspect(db_engine).get_indexes("calculator_margin_requests")
    assert any(index["column_names"] == ["status", "created_at", "id"] for index in indexes)


def test_metadata_upgrade_preserves_legacy_rows_and_downgrades(db_engine: Engine) -> None:
    cfg = alembic_config()
    account_id: int | None = None
    try:
        command.downgrade(cfg, _BEFORE_CALCULATOR)
        with db_engine.begin() as conn:
            account_id = conn.execute(
                text(
                    "INSERT INTO accounts (name, firm, program, phase, login, server, "
                    "starting_balance, currency) VALUES ('Legacy sizing', 'Fixture', 'Fixture', "
                    "'phase_1', 987654322, 'Fixture', 10000, 'USD') RETURNING id"
                )
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO symbol_specs (account_id, symbol, contract_size, tick_size, "
                    "tick_value, volume_min, volume_step, volume_max, digits, currency_profit, "
                    "currency_margin, synced_at) VALUES (:id, 'GER40.cash', 1, 0.5, 2, 0.01, "
                    "0.01, 100, 1, 'EUR', 'EUR', :now)"
                ),
                {"id": account_id, "now": NOW},
            )
        command.upgrade(cfg, "head")
        with db_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT point, tick_value_loss, tick_value, tick_size FROM symbol_specs "
                    "WHERE account_id=:id"
                ),
                {"id": account_id},
            ).one()
        assert tuple(row) == (None, None, Decimal("2"), Decimal("0.5"))
        command.downgrade(cfg, _BEFORE_CALCULATOR)
        assert "calculator_margin_samples" not in inspect(db_engine).get_table_names()
        assert "calculator_margin_requests" not in inspect(db_engine).get_table_names()
        assert "point" not in {
            col["name"] for col in inspect(db_engine).get_columns("symbol_specs")
        }
        with db_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM symbol_specs WHERE account_id=:id"),
                    {"id": account_id},
                ).scalar_one()
                == 1
            )
    finally:
        try:
            if account_id is not None:
                with db_engine.begin() as conn:
                    conn.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": account_id})
        finally:
            command.upgrade(cfg, "head")


def _column_names(engine: Engine, table: str) -> set[str]:
    return {col["name"] for col in inspect(engine).get_columns(table)}


def test_head_has_no_margin_samples_or_request_signature(db_engine: Engine) -> None:
    assert "calculator_margin_samples" not in inspect(db_engine).get_table_names()
    assert "signature" not in _column_names(db_engine, _REQUESTS)


def test_samples_and_signature_restored_on_downgrade_and_dropped_on_upgrade(
    db_engine: Engine,
) -> None:
    cfg = alembic_config()
    account_id: int | None = None
    try:
        with db_engine.begin() as conn:
            account_id = conn.execute(
                text(
                    "INSERT INTO accounts (name, firm, program, phase, login, server, "
                    "starting_balance, currency) VALUES ('Margin downgrade', 'Fixture', "
                    "'Fixture', 'phase_1', 987654323, 'Fixture', 10000, 'USD') RETURNING id"
                )
            ).scalar_one()
            request_id = conn.execute(
                text(
                    "INSERT INTO calculator_margin_requests (account_id, symbol, direction, "
                    "volume, entry, currency, status, created_at, expires_at) "
                    "VALUES (:id, 'GER40.cash', 'buy', 0.01, 19000.5, 'USD', 'pending', :now, "
                    ":expires) RETURNING id"
                ),
                {"id": account_id, "now": NOW, "expires": NOW + timedelta(minutes=1)},
            ).scalar_one()
        command.downgrade(cfg, _WITH_MARGIN_SAMPLES)
        inspector = inspect(db_engine)
        assert "calculator_margin_samples" in inspector.get_table_names()
        assert [
            uq["name"] for uq in inspector.get_unique_constraints("calculator_margin_samples")
        ] == ["uq_calculator_margin_samples_account_id_symbol_direction"]
        assert {
            ck["name"] for ck in inspector.get_check_constraints("calculator_margin_samples")
        } == {
            f"ck_calculator_margin_samples_{name}"
            for name in (
                "direction_valid",
                "symbol_not_empty",
                "currency_valid",
                "signature_not_empty",
                "margin_valid",
                "volume_valid",
                "price_valid",
            )
        }
        with db_engine.connect() as conn:
            restored_rows = conn.execute(
                text("SELECT count(*) FROM calculator_margin_samples")
            ).scalar_one()
        assert restored_rows == 0  # restored empty, old samples are not recovered
        signature = next(
            col for col in inspector.get_columns(_REQUESTS) if col["name"] == "signature"
        )
        assert signature["nullable"] is False
        assert "ck_calculator_margin_requests_signature_not_empty" in {
            ck["name"] for ck in inspector.get_check_constraints(_REQUESTS)
        }
        with db_engine.connect() as conn:
            filled = conn.execute(
                text("SELECT signature FROM calculator_margin_requests WHERE id=:id"),
                {"id": request_id},
            ).scalar_one()
        assert filled == f"downgraded:{request_id}"

        command.upgrade(cfg, "head")
        assert "calculator_margin_samples" not in inspect(db_engine).get_table_names()
        assert "signature" not in _column_names(db_engine, _REQUESTS)
        with db_engine.connect() as conn:
            row = conn.execute(
                text("SELECT symbol, entry FROM calculator_margin_requests WHERE id=:id"),
                {"id": request_id},
            ).one()
        assert tuple(row) == ("GER40.cash", Decimal("19000.5"))
    finally:
        try:
            if account_id is not None:
                with db_engine.begin() as conn:
                    conn.execute(text("DELETE FROM accounts WHERE id=:id"), {"id": account_id})
        finally:
            command.upgrade(cfg, "head")
