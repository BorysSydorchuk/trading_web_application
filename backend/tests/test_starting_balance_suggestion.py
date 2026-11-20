"""Starting balance suggestion: the first deposit of the MT5 deal history, read once per
account by the worker (fixture source; MT5 stays read-only) into
``DATA_DIR/starting_balance_suggestions.json``."""

# ruff: noqa: F811  (pytest fixtures imported from test_sync)
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config_files.rules import RulesConfig
from app.domain.broker_time import FixedOffset
from app.models import SyncLog
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from app.mt5.types import RawDeal
from app.services import starting_balance_suggestion as sbs
from app.worker.sync_job import run_sync_cycle
from tests.test_sync import (  # noqa: F401 (fixtures)
    WEEK_LOGIN,
    WEEK_NOW,
    _clean,
    add_account,
    env_passwords,
    factory,
    rules,
    session,
    source,
)

UTC2 = FixedOffset(2)
AT = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def deal(
    ticket: int,
    deal_type: int,
    profit: str,
    wall: datetime,
    *,
    commission: str = "0",
    fee: str = "0",
    swap: str = "0",
) -> RawDeal:
    """A deal at server wall time ``wall`` (given tagged as UTC, server = UTC+2)."""
    return RawDeal(
        ticket=ticket,
        order=0,
        position_id=0 if deal_type not in (0, 1) else ticket,
        time=int(wall.timestamp()),
        type=deal_type,
        entry=0,
        volume=Decimal("0"),
        price=Decimal("0"),
        profit=Decimal(profit),
        symbol="" if deal_type not in (0, 1) else "EURUSD",
        commission=Decimal(commission),
        fee=Decimal(fee),
        swap=Decimal(swap),
    )


@pytest.fixture(autouse=True)
def _fresh_warnings() -> None:
    sbs._warned.clear()


# --- picking the first deposit ---------------------------------------------------------------


def test_first_deposit_is_the_earliest_positive_non_trade_deal() -> None:
    deals = [
        deal(5, 0, "120.00", datetime(2026, 11, 10, 14, 0, tzinfo=UTC)),  # a buy: ignored
        deal(6, 2, "-50.00", datetime(2026, 11, 10, 13, 0, tzinfo=UTC)),  # withdrawal
        deal(7, 2, "500.00", datetime(2026, 11, 12, 9, 0, tzinfo=UTC)),  # a later top-up
        deal(194830322, 4, "10000.00", datetime(2026, 11, 10, 14, 53, tzinfo=UTC)),
        deal(3, 1, "-13.95", datetime(2026, 11, 10, 14, 0, tzinfo=UTC)),  # a sell: ignored
    ]

    found = sbs.first_deposit(deals, UTC2)

    assert found == sbs.FirstDeposit(
        Decimal("10000.00"), datetime(2026, 11, 10, 12, 53, tzinfo=UTC), 194830322
    )


def test_first_deposit_type_2_and_net_of_costs() -> None:
    deals = [
        deal(9, 2, "100000", datetime(2026, 10, 1, 2, 0, tzinfo=UTC), commission="-1.5", fee="-1"),
        deal(8, 4, "5", datetime(2026, 10, 1, 3, 0, tzinfo=UTC)),
    ]

    found = sbs.first_deposit(deals, UTC2)

    assert found is not None
    assert (found.amount, found.ticket) == (Decimal("99997.50"), 9)
    assert found.time == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


def test_same_time_lowest_ticket_wins_and_none_without_deposits() -> None:
    at = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
    found = sbs.first_deposit([deal(12, 2, "10", at), deal(11, 2, "20", at)], UTC2)
    assert found is not None
    assert found.ticket == 11

    assert sbs.first_deposit([deal(1, 0, "10", at), deal(2, 2, "-10", at)], UTC2) is None
    assert sbs.first_deposit([], UTC2) is None


def test_a_deposit_eaten_by_its_costs_is_skipped_so_a_valid_amount_is_always_stored() -> None:
    at = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)
    later = datetime(2026, 10, 2, 2, 0, tzinfo=UTC)

    found = sbs.first_deposit([deal(1, 2, "1", at, fee="-1"), deal(2, 2, "10000", later)], UTC2)

    assert found is not None
    assert (found.ticket, found.amount) == (2, Decimal("10000.00"))
    assert sbs.first_deposit([deal(1, 2, "0.004", at)], UTC2) is None  # rounds to 0.00


# --- file write / read -----------------------------------------------------------------------


def test_file_round_trip_with_amount_and_with_none(tmp_path: Path) -> None:
    path = tmp_path / "data" / sbs.SUGGESTIONS_FILE
    deposit = sbs.FirstDeposit(
        Decimal("10000.00"), datetime(2026, 11, 10, 12, 53, tzinfo=UTC), 194830322
    )

    sbs.write_account(path, 1, deposit, AT)
    sbs.write_account(path, 2, None, AT)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "1": {
            "amount": "10000.00",
            "time": "2026-11-10T12:53:00Z",
            "ticket": 194830322,
            "checked_at": "2026-11-20T09:00:00Z",
        },
        "2": {"amount": None, "checked_at": "2026-11-20T09:00:00Z"},
    }
    assert sbs.read_suggestions(path) == {
        1: sbs.Suggestion(Decimal("10000.00"), datetime(2026, 11, 10, 12, 53, tzinfo=UTC)),
        2: sbs.Suggestion(None, None),
    }
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("content", [None, "{broken", "[]"])
def test_missing_or_broken_file_reads_empty_and_logs_once(
    tmp_path: Path, content: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / sbs.SUGGESTIONS_FILE
    if content is not None:
        path.write_text(content, encoding="utf-8")
    caplog.set_level(logging.INFO, logger=sbs.__name__)

    assert sbs.read_suggestions(path) == {}
    assert sbs.read_suggestions(path) == {}

    assert len([r for r in caplog.records if r.name == sbs.__name__]) == 1


def test_malformed_entries_are_skipped(tmp_path: Path) -> None:
    good = {"amount": "10.00", "time": "2026-11-10T12:53:00Z"}
    data = {
        "1": good,
        "2": {"amount": "x", "time": "2026-11-10T12:53:00Z"},
        "3": {"amount": "10.00", "time": "2026-11-10T12:53:00"},  # naive
        "4": {"amount": "10.00"},
        "5": {"amount": "-1", "time": "2026-11-10T12:53:00Z"},
        "6": "nope",
        "bad": good,
    }
    path = tmp_path / sbs.SUGGESTIONS_FILE
    path.write_text(json.dumps(data), encoding="utf-8")

    assert sorted(sbs.read_suggestions(path)) == [1]


def test_write_replaces_a_broken_file(tmp_path: Path) -> None:
    path = tmp_path / sbs.SUGGESTIONS_FILE
    path.write_text("{broken", encoding="utf-8")

    sbs.write_account(path, 4, None, AT)

    assert sbs.read_suggestions(path) == {4: sbs.Suggestion(None, None)}


def test_suggestion_for_only_when_it_differs() -> None:
    entries = {
        1: sbs.Suggestion(Decimal("10000.00"), AT),
        2: sbs.Suggestion(None, None),
    }
    assert sbs.suggestion_for(entries, 1, Decimal("9986.05")) == entries[1]
    assert sbs.suggestion_for(entries, 1, Decimal("10000")) is None
    assert sbs.suggestion_for(entries, 2, Decimal("9986.05")) is None
    assert sbs.suggestion_for(entries, 3, Decimal("9986.05")) is None


# --- worker sync -----------------------------------------------------------------------------


def _record_deals(src: FixtureMt5Source, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the ``from`` epoch of every deals() call."""
    starts: list[int] = []
    original = src.deals

    def recording(from_epoch: int, to_epoch: int) -> list[RawDeal]:
        starts.append(from_epoch)
        return original(from_epoch, to_epoch)

    monkeypatch.setattr(src, "deals", recording)
    return starts


def _cycle(
    factory: sessionmaker[Session], src: FixtureMt5Source, rules: RulesConfig, path: Path | None
) -> list[int]:
    return run_sync_cycle(
        factory, src, now=lambda: WEEK_NOW, rules_getter=lambda: rules, suggestions_path=path
    )


@pytest.mark.usefixtures("env_passwords")
def test_account_without_entry_reads_the_full_history_once(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")
    path = tmp_path / sbs.SUGGESTIONS_FILE
    src = source("basic_week.json")
    starts = _record_deals(src, monkeypatch)

    assert _cycle(factory, src, rules, path) == [account.id]

    assert starts.count(0) == 1
    entry = json.loads(path.read_text(encoding="utf-8"))[str(account.id)]
    assert (entry["amount"], entry["ticket"]) == ("100000.00", 1000001)
    assert entry["time"].endswith("Z")
    assert entry["checked_at"] == "2026-10-23T10:00:00Z"


@pytest.mark.usefixtures("env_passwords")
def test_account_with_an_entry_is_not_asked_again(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")
    path = tmp_path / sbs.SUGGESTIONS_FILE
    sbs.write_account(path, account.id, None, AT)
    before = path.read_text(encoding="utf-8")
    src = source("basic_week.json")
    starts = _record_deals(src, monkeypatch)

    assert _cycle(factory, src, rules, path) == [account.id]

    assert 0 not in starts
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.usefixtures("env_passwords")
def test_no_suggestions_path_never_reads_the_full_history(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_account(session, WEEK_LOGIN, "B good")
    src = source("basic_week.json")
    starts = _record_deals(src, monkeypatch)

    _cycle(factory, src, rules, None)

    assert starts
    assert 0 not in starts


@pytest.mark.usefixtures("env_passwords")
def test_history_read_failure_never_fails_the_sync(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = add_account(session, WEEK_LOGIN, "B good")
    path = tmp_path / sbs.SUGGESTIONS_FILE
    src = source("basic_week.json")
    original = src.deals

    def failing(from_epoch: int, to_epoch: int) -> list[RawDeal]:
        if from_epoch == 0:
            raise Mt5Error(Mt5ErrorCode.TIMEOUT, "history too slow")
        return original(from_epoch, to_epoch)

    monkeypatch.setattr(src, "deals", failing)

    assert _cycle(factory, src, rules, path) == [account.id]

    assert session.scalars(select(SyncLog)).one().ok is True
    assert not path.exists()  # not checked: asked again on the next sync
    assert "starting balance suggestion not read" in caplog.text


@pytest.mark.usefixtures("env_passwords")
def test_write_failure_never_fails_the_sync(
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

    monkeypatch.setattr(sbs, "write_account", broken)

    assert _cycle(factory, source("basic_week.json"), rules, tmp_path / "s.json") == [account.id]

    assert session.scalars(select(SyncLog)).one().ok is True
    assert f"Account {account.id}: starting balance suggestion not written" in caplog.text
