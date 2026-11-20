"""M8-10b: the worker's open-positions snapshot ``DATA_DIR/open_positions.json``.

Written after every successful account sync from the positions the sync already read
(fixture source here; MT5 stays read-only), replaced atomically, read by GET /api/home.
"""

# ruff: noqa: F811  (pytest fixtures imported from test_sync)
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config_files.rules import RulesConfig
from app.models import SyncLog
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.types import RawPosition
from app.services import open_positions_snapshot as snap
from app.worker.sync_job import run_sync_cycle
from tests.test_sync import (  # noqa: F401 (fixtures)
    WEEK_LOGIN,
    WEEK_NOW,
    WEEK_STEP1_NOW,
    _clean,
    add_account,
    env_passwords,
    factory,
    rules,
    session,
    source,
)

AT = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def position(
    identifier: int, price: str = "1.1625", profit: str = "40", swap: str = "0"
) -> RawPosition:
    return RawPosition(
        ticket=identifier,
        identifier=identifier,
        time=0,
        type=1,
        volume=Decimal("0.8"),
        price_open=Decimal("1.163"),
        sl=Decimal("1.165"),
        tp=Decimal("1.159"),
        price_current=Decimal(price),
        profit=Decimal(profit),
        symbol="EURUSD",
        swap=Decimal(swap),
    )


def write(path: Path, account_id: int, positions: Sequence[RawPosition], at: datetime = AT) -> None:
    snap.write_account(path, account_id, positions, at)


@pytest.fixture(autouse=True)
def _fresh_warnings() -> None:
    snap._warned.clear()


# --- write / read ----------------------------------------------------------------------------


def test_write_stores_price_profit_plus_swap_and_utc_time(tmp_path: Path) -> None:
    path = tmp_path / "data" / snap.SNAPSHOT_FILE

    write(path, 3, [position(77, profit="40.50", swap="-1.25")])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "3": {"77": {"price_current": "1.1625", "profit": "39.25", "time": "2026-11-20T09:00:00Z"}}
    }
    assert [p.name for p in path.parent.iterdir()] == [snap.SNAPSHOT_FILE]  # no temp left


def test_write_replaces_only_its_account(tmp_path: Path) -> None:
    path = tmp_path / snap.SNAPSHOT_FILE
    write(path, 1, [position(10), position(11)])
    write(path, 2, [position(20)])

    write(path, 1, [position(11, price="1.17")])

    live = snap.read_snapshot(path)
    assert sorted(live) == [(1, 11), (2, 20)]
    assert live[(1, 11)].price_current == Decimal("1.17")


def test_write_over_a_broken_file_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / snap.SNAPSHOT_FILE
    path.write_text("{not json", encoding="utf-8")

    write(path, 1, [position(10)])

    assert sorted(snap.read_snapshot(path)) == [(1, 10)]


def test_read_returns_decimals_and_aware_time(tmp_path: Path) -> None:
    path = tmp_path / snap.SNAPSHOT_FILE
    write(path, 1, [position(10, price="2650.55", profit="-12.3")])

    value = snap.read_snapshot(path)[(1, 10)]

    assert value == snap.LiveValue(Decimal("2650.55"), Decimal("-12.3"), AT)


def test_values_older_than_five_minutes_are_stale(tmp_path: Path) -> None:
    path = tmp_path / snap.SNAPSHOT_FILE
    write(path, 1, [position(10)])

    value = snap.read_snapshot(path)[(1, 10)]

    assert snap.is_fresh(value, AT + timedelta(minutes=5))
    assert not snap.is_fresh(value, AT + timedelta(minutes=5, seconds=1))


def test_missing_file_is_empty_and_warned_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    path = tmp_path / snap.SNAPSHOT_FILE

    assert snap.read_snapshot(path) == {}
    assert snap.read_snapshot(path) == {}

    assert caplog.text.count("not found") == 1


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", '"text"'])
def test_broken_file_is_empty_and_warned_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    caplog.set_level(logging.WARNING)
    path = tmp_path / snap.SNAPSHOT_FILE
    path.write_text(content, encoding="utf-8")

    assert snap.read_snapshot(path) == {}
    assert snap.read_snapshot(path) == {}

    assert caplog.text.count("unreadable") == 1


def test_bad_entries_are_skipped_good_ones_kept(tmp_path: Path) -> None:
    good = {"price_current": "1.1", "profit": "5", "time": "2026-11-20T09:00:00Z"}
    data = {
        "1": {
            "10": good,
            "11": {"price_current": "x", "profit": "5", "time": "2026-11-20T09:00:00Z"},
            "12": {"price_current": "1.1", "profit": "5", "time": "2026-11-20T09:00:00"},
            "13": {"price_current": "1.1"},
            "14": "nope",
            "bad": good,
        },
        "2": [],
    }
    path = tmp_path / snap.SNAPSHOT_FILE
    path.write_text(json.dumps(data), encoding="utf-8")

    assert sorted(snap.read_snapshot(path)) == [(1, 10)]


# --- worker sync -----------------------------------------------------------------------------


@pytest.mark.usefixtures("env_passwords")
def test_sync_cycle_writes_the_open_positions_of_the_account(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig, tmp_path: Path
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")
    path = tmp_path / snap.SNAPSHOT_FILE

    run_sync_cycle(
        factory,
        source("basic_week.json"),
        now=lambda: WEEK_NOW,
        rules_getter=lambda: rules,
        snapshot_path=path,
    )

    live = snap.read_snapshot(path)
    assert live == {
        (account.id, 2000701): snap.LiveValue(Decimal("1.1625"), Decimal("40"), WEEK_NOW)
    }


@pytest.mark.usefixtures("env_passwords")
def test_closed_position_leaves_the_snapshot_on_the_next_sync(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig, tmp_path: Path
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")
    path = tmp_path / snap.SNAPSHOT_FILE
    run_sync_cycle(
        factory,
        source("basic_week.json"),
        now=lambda: WEEK_NOW,
        rules_getter=lambda: rules,
        snapshot_path=path,
    )

    run_sync_cycle(
        factory,
        source("basic_week.json", step=1),
        now=lambda: WEEK_STEP1_NOW,
        rules_getter=lambda: rules,
        snapshot_path=path,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {str(account.id): {}}


@pytest.mark.usefixtures("env_passwords")
def test_snapshot_write_failure_never_fails_the_sync(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")

    def broken(*_args: object) -> None:
        raise PermissionError("disk is read-only")

    monkeypatch.setattr(snap, "write_account", broken)

    synced = run_sync_cycle(
        factory,
        source("basic_week.json"),
        now=lambda: WEEK_NOW,
        rules_getter=lambda: rules,
        snapshot_path=tmp_path / snap.SNAPSHOT_FILE,
    )

    assert synced == [account.id]
    log = session.scalars(select(SyncLog)).one()
    assert log.ok is True
    assert f"Account {account.id}: open positions snapshot not written" in caplog.text


@pytest.mark.usefixtures("env_passwords")
def test_failed_sync_keeps_the_previous_snapshot(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig, tmp_path: Path
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")
    path = tmp_path / snap.SNAPSHOT_FILE
    write(path, account.id, [position(5)], WEEK_NOW)
    src = source("basic_week.json")
    src.fail("open_positions", Mt5Error(Mt5ErrorCode.TIMEOUT, "slow"))
    run_sync_cycle(
        factory, src, now=lambda: WEEK_NOW, rules_getter=lambda: rules, snapshot_path=path
    )

    assert sorted(snap.read_snapshot(path)) == [(account.id, 5)]


def test_reported_accounts_include_empty_entries(tmp_path: Path) -> None:
    path = snap.snapshot_path(tmp_path)
    assert snap.reported_accounts(path) == frozenset()  # missing file
    snap.write_account(path, 3, [], datetime(2026, 11, 20, 21, 15, tzinfo=UTC))
    path.write_text(
        json.dumps({**json.loads(path.read_text(encoding="utf-8")), "x": {}, "7": []}),
        encoding="utf-8",
    )
    assert snap.reported_accounts(path) == frozenset({3})  # empty entry counts; junk does not
    path.write_text("{broken", encoding="utf-8")
    assert snap.reported_accounts(path) == frozenset()
