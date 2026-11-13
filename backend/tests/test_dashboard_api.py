"""M6-03 ``GET /api/dashboard`` (docs/api.md "Dashboard API (PRD 6.10)").

Contract pinned by these tests (additions to api.md are marked NEW):
- ``now`` is the injected ``app.clock.utc_now`` (ISO, UTC).
- ``accounts``: active accounts only (archived excluded), ordered by id. Money = string with
  2 dp ("-170.00"), percents = string with 4 dp ("-1.7000"). ``pct``/``low_pct``/``high_pct`` are
  % of ``account_size`` (= accounts.reference_balance), never of the synced balance.
- ``today`` = Brussels day, ``week`` = Mon-Sun Brussels week, by close time. Each block is
  ``{pnl, pct, low_pnl, low_pct, high_pnl, high_pct}`` (NEW: pnl amounts of the extremes added).
- ``limits`` (NEW: 4 dp strings from config/rules.yaml, e.g. "-3.0000"): daily_loss_pct,
  daily_profit_pct, weekly_loss_pct, weekly_profit_pct.
- ``stop.today`` / ``stop.week``: any account's state is not ok.
- ``open_positions``: open trades of active accounts with the canonical symbol.
- ``inbox`` equals ``GET /api/inbox/counts``.
- Broken rules.yaml: 500 ``config_error``.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import REPO_ROOT
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.models import Account, Trade
from app.models.enums import AccountStatus
from app.schemas.dashboard import money_str, pct_str
from tests.test_trades_api import add_account, add_trade

D = Decimal
# Thu 2026-11-12 14:00 UTC = 15:00 Brussels (UTC+1). Day = 12th, week = Mon 9th - Sun 15th.
NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
TODAY = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
MON = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
LAST_SUN_LATE = datetime(2026, 11, 8, 22, 30, tzinfo=UTC)  # Sun 23:30 Brussels, previous week


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


@pytest.fixture(autouse=True)
def _now(app: FastAPI) -> None:
    app.dependency_overrides[utc_now] = lambda: NOW


def closed(session: Session, account: Account, close: datetime, pnl: str, **kw: Any) -> Trade:
    fields: dict[str, Any] = {
        "open_time": close - timedelta(minutes=30),
        "close_time": close,
        "net_pnl": D(pnl),
        "status": "complete",
    }
    return add_trade(session, account, **(fields | kw))


def open_position(session: Session, account: Account, **kw: Any) -> Trade:
    fields: dict[str, Any] = {
        "status": "open",
        "open_time": TODAY,
        "close_time": None,
        "exit_price": None,
        "net_pnl": None,
        "gross_pnl": None,
        "commission": None,
        "duration_seconds": None,
        "initial_sl": D("2640.00"),
        "risk_amount": D("100.00"),
        "risk_pct": D("1.0000"),
    }
    return add_trade(session, account, **(fields | kw))


def dashboard(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def by_name(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(a for a in data["accounts"] if a["name"] == name)


@pytest.fixture
def seeded(session: Session) -> dict[str, Account]:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"), balance=D("9000.00"))
    b = add_account(session, "Beta", 2, reference_balance=D("20000.00"), balance=D("50000.00"))
    old = add_account(session, "Old", 3, status=AccountStatus.ARCHIVED.value)
    # Alpha today: -320 then +150 -> total -170 (-1.7 %), sticky low -3.2 % => stop_loss.
    closed(session, a, TODAY, "-320.00")
    closed(session, a, TODAY + timedelta(hours=1), "150.00")
    # Alpha earlier this week: +200 on Monday; the previous week's +999 does not count.
    closed(session, a, MON, "200.00")
    closed(session, a, LAST_SUN_LATE, "999.00")
    # Beta today +1100: 5.5 % of the 20 000 size (stop_profit), but only 2.2 % of 50 000 balance.
    closed(session, b, TODAY, "1100.00")
    # Archived account: huge loss and an open position, both excluded.
    closed(session, old, TODAY, "-5000.00")
    open_position(session, old, symbol="EURUSD")
    return {"a": a, "b": b, "old": old}


def test_lists_only_active_accounts_in_id_order(
    client: TestClient, seeded: dict[str, Account]
) -> None:
    data = dashboard(client)

    assert [a["name"] for a in data["accounts"]] == ["Alpha", "Beta"]
    assert data["now"].startswith("2026-11-12T14:00:00")
    alpha = data["accounts"][0]
    assert alpha["id"] == seeded["a"].id
    assert alpha["currency"] == "USD"


def test_today_block_is_pct_of_the_account_size_with_sticky_low(
    client: TestClient, seeded: dict[str, Account]
) -> None:
    alpha = by_name(dashboard(client), "Alpha")

    assert alpha["account_size"] == "10000.00"
    assert alpha["today"] == {
        "pnl": "-170.00",
        "pct": "-1.7000",
        "low_pnl": "-320.00",
        "low_pct": "-3.2000",
        "high_pnl": "0.00",
        "high_pct": "0.0000",
    }
    assert alpha["today_state"] == "stop_loss"


def test_week_block_includes_monday_and_excludes_the_previous_sunday(
    client: TestClient, seeded: dict[str, Account]
) -> None:
    alpha = by_name(dashboard(client), "Alpha")

    # Replay: +200 (Mon), -320, +150 -> total +30, low -120, high +200.
    assert alpha["week"] == {
        "pnl": "30.00",
        "pct": "0.3000",
        "low_pnl": "-120.00",
        "low_pct": "-1.2000",
        "high_pnl": "200.00",
        "high_pct": "2.0000",
    }
    assert alpha["week_state"] == "ok"


def test_pct_uses_the_size_not_the_balance(client: TestClient, seeded: dict[str, Account]) -> None:
    beta = by_name(dashboard(client), "Beta")

    assert beta["account_size"] == "20000.00"
    assert beta["today"]["pct"] == "5.5000"
    assert beta["today"]["high_pct"] == "5.5000"
    assert beta["today_state"] == "stop_profit"
    assert beta["week_state"] == "ok"  # 5.5 % < the weekly +10 %


def test_limits_come_from_rules_yaml(client: TestClient, seeded: dict[str, Account]) -> None:
    alpha = by_name(dashboard(client), "Alpha")

    assert alpha["limits"] == {
        "daily_loss_pct": "-3.0000",
        "daily_profit_pct": "5.0000",
        "weekly_loss_pct": "-6.0000",
        "weekly_profit_pct": "10.0000",
    }


def test_stop_flags_follow_any_account_state(
    client: TestClient, seeded: dict[str, Account]
) -> None:
    assert dashboard(client)["stop"] == {"today": True, "week": False}


def test_week_stop_flag(client: TestClient, session: Session) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    closed(session, a, MON, "-650.00")  # -6.5 % in the week, today untouched

    data = dashboard(client)

    assert by_name(data, "Alpha")["week_state"] == "stop_loss"
    assert by_name(data, "Alpha")["today_state"] == "ok"
    assert data["stop"] == {"today": False, "week": True}


def test_exactly_at_the_limit_is_a_stop(client: TestClient, session: Session) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    closed(session, a, TODAY, "-300.00")  # exactly -3.0 %

    assert by_name(dashboard(client), "Alpha")["today_state"] == "stop_loss"


def test_no_stop_when_all_accounts_are_ok(client: TestClient, session: Session) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    closed(session, a, TODAY, "-299.00")

    data = dashboard(client)

    assert data["stop"] == {"today": False, "week": False}
    assert by_name(data, "Alpha")["today_state"] == "ok"


def test_account_without_trades_is_all_zeros_and_ok(client: TestClient, session: Session) -> None:
    add_account(session, "Empty", 1, reference_balance=D("10000.00"))

    data = dashboard(client)

    empty = by_name(data, "Empty")
    zeros = {
        "pnl": "0.00",
        "pct": "0.0000",
        "low_pnl": "0.00",
        "low_pct": "0.0000",
        "high_pnl": "0.00",
        "high_pct": "0.0000",
    }
    assert empty["today"] == zeros
    assert empty["week"] == zeros
    assert (empty["today_state"], empty["week_state"]) == ("ok", "ok")
    assert data["stop"] == {"today": False, "week": False}
    assert data["open_positions"] == []


def test_open_positions_list_canonical_symbol_account_and_risk(
    client: TestClient, session: Session, seeded: dict[str, Account]
) -> None:
    trade = open_position(
        session,
        seeded["b"],
        symbol="GER40",
        broker_symbol="DE40.cash",
        direction="sell",
        volume=D("0.13"),
        entry_price=D("26478.80"),
        initial_sl=D("26514.20"),
        risk_amount=D("46.00"),
        risk_pct=D("0.2300"),
    )

    positions = dashboard(client)["open_positions"]

    assert len(positions) == 1  # the archived account's position is not listed
    pos = positions[0]
    assert pos["trade_id"] == trade.id
    assert pos["account_name"] == "Beta"
    assert pos["symbol"] == "GER40"
    assert pos["direction"] == "sell"
    assert D(pos["volume"]) == D("0.13")
    assert D(pos["entry_price"]) == D("26478.80")
    assert D(pos["initial_sl"]) == D("26514.20")
    assert pos["risk_amount"] == "46.00"
    assert pos["risk_pct"] == "0.2300"
    assert pos["open_time"].startswith("2026-11-12T09:00:00")


def test_open_position_without_sl_has_null_risk(client: TestClient, session: Session) -> None:
    a = add_account(session, "Alpha", 1)
    open_position(session, a, status="open", initial_sl=None, risk_amount=None, risk_pct=None)

    pos = dashboard(client)["open_positions"][0]

    assert pos["initial_sl"] is None
    assert pos["risk_amount"] is None
    assert pos["risk_pct"] is None


def test_open_trades_do_not_count_as_pnl(client: TestClient, session: Session) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    open_position(session, a)

    alpha = by_name(dashboard(client), "Alpha")

    assert alpha["today"]["pnl"] == "0.00"
    assert alpha["week"]["pnl"] == "0.00"


def test_inbox_equals_the_inbox_counts_endpoint(
    client: TestClient, session: Session, seeded: dict[str, Account]
) -> None:
    a = seeded["a"]
    closed(session, a, TODAY, "1.00", status="needs_sl")
    closed(session, a, TODAY, "1.00", status="needs_sl")
    closed(session, a, TODAY, "1.00", status="needs_description")
    closed(session, a, TODAY, "1.00", status="draft")
    closed(session, seeded["old"], TODAY, "1.00", status="needs_sl")  # archived: not counted

    data = dashboard(client)

    counts = client.get("/api/inbox/counts").json()
    assert data["inbox"] == counts
    assert data["inbox"]["needs_sl"] == 2
    assert set(data["inbox"]) == {"needs_sl", "needs_description", "draft"}


def test_no_accounts_gives_an_empty_dashboard(client: TestClient) -> None:
    data = dashboard(client)

    assert data["accounts"] == []
    assert data["open_positions"] == []
    assert data["stop"] == {"today": False, "week": False}
    assert data["inbox"] == {"needs_sl": 0, "needs_description": 0, "draft": 0}


def test_account_without_a_usable_size_has_no_stop(client: TestClient, session: Session) -> None:
    a = add_account(session, "Alpha", 1)
    # reference_balance is NOT NULL (defaults to starting_balance); a zero size is the edge case.
    a.reference_balance = D("0.00")
    session.commit()
    closed(session, a, TODAY, "-500.00")

    data = dashboard(client)

    alpha = by_name(data, "Alpha")
    assert alpha["today_state"] == "ok"
    assert data["stop"]["today"] is False
    zeros = {
        "pnl": "0.00",
        "pct": "0.0000",
        "low_pnl": "0.00",
        "low_pct": "0.0000",
        "high_pnl": "0.00",
        "high_pct": "0.0000",
    }
    assert alpha["today"] == zeros
    assert alpha["week"] == zeros


@pytest.mark.parametrize(
    ("func", "value", "expected"),
    [
        (pct_str, D("-0.00004"), "0.0000"),
        (pct_str, D("-0.00005"), "-0.0001"),
        (money_str, D("-0.004"), "0.00"),
        (money_str, D("2.005"), "2.01"),
    ],
)
def test_rounding_at_the_edge_never_shows_negative_zero(
    func: Callable[[D], str], value: D, expected: str
) -> None:
    assert func(value) == expected


# --- broken config ---------------------------------------------------------------------------


@pytest.fixture
def broken_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    (config / "rules.yaml").write_text("timezone: [not, valid\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield
    reload_config()


def test_broken_rules_yaml_is_a_config_error(client: TestClient, broken_rules: None) -> None:
    response = client.get("/api/dashboard")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "config_error"
    assert error["details"]["file"] == "rules.yaml"


# --- disabled stop rule, position order ----------------------------------------------------


@pytest.fixture
def daily_stop_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    path = config / "rules.yaml"
    source = path.read_text(encoding="utf-8")
    for key in ("daily_stop_loss_pct", "daily_stop_profit_pct"):
        pattern = re.compile(rf"^(  {key}:.*?)enabled: true", re.MULTILINE)
        source, count = pattern.subn(r"\1enabled: false", source)
        assert count == 1
    path.write_text(source, encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield
    reload_config()


def test_disabled_daily_stop_has_null_limits_and_never_stops(
    client: TestClient, session: Session, daily_stop_disabled: None
) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    closed(session, a, TODAY, "-500.00")  # -5 % today

    data = dashboard(client)

    alpha = by_name(data, "Alpha")
    assert alpha["limits"]["daily_loss_pct"] is None
    assert alpha["limits"]["daily_profit_pct"] is None
    assert alpha["limits"]["weekly_loss_pct"] == "-6.0000"
    assert alpha["limits"]["weekly_profit_pct"] == "10.0000"
    assert alpha["today_state"] == "ok"
    assert data["stop"]["today"] is False


def test_weekly_stop_still_enforced_when_daily_is_disabled(
    client: TestClient, session: Session, daily_stop_disabled: None
) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    closed(session, a, MON, "-650.00")  # -6.5 % in the week

    data = dashboard(client)

    assert by_name(data, "Alpha")["week_state"] == "stop_loss"
    assert data["stop"] == {"today": False, "week": True}


def test_open_positions_are_ordered_by_open_time_then_trade_id(
    client: TestClient, session: Session
) -> None:
    a = add_account(session, "Alpha", 1)
    late = open_position(session, a, open_time=TODAY + timedelta(hours=2))
    early_first = open_position(session, a, open_time=TODAY)
    early_second = open_position(session, a, open_time=TODAY)

    ids = [p["trade_id"] for p in dashboard(client)["open_positions"]]

    assert ids == [early_first.id, early_second.id, late.id]
