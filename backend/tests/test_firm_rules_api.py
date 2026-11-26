"""Firm rules from config (KeyFunding) through the APIs: accounts, home, dashboard
(docs/api.md "Firm rules from config: KeyFunding").

NOW = Thu 2026-11-12 14:00 UTC. With a server offset of 0 the firm day started at 00:00 UTC
that day; the Brussels day started 23:00 UTC the evening before.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
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
from app.config import REPO_ROOT, Settings, get_settings
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.models import Account
from tests.test_dashboard_api import closed, open_position
from tests.test_trades_api import add_account

D = Decimal
NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
TODAY = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
BEFORE_RESET = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)  # Brussels today, firm day yesterday
FRESH = NOW - timedelta(minutes=1)
STALE = NOW - timedelta(minutes=30)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts, bias_notes RESTART IDENTITY CASCADE"))

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
def _env(tmp_path: Path, app: FastAPI, settings: Settings) -> None:
    app.dependency_overrides[utc_now] = lambda: NOW
    custom = settings.model_copy(update={"data_dir": tmp_path.resolve()})
    app.dependency_overrides[get_settings] = lambda: custom


def key_account(session: Session, name: str = "Key", login: int = 7, **kw: Any) -> Account:
    fields: dict[str, Any] = {
        "name": name,
        "firm": "KeyFunding",
        "program": "Challenge",
        "phase": "phase_1",
        "login": login,
        "server": "Key-Server",
        "starting_balance": D("10000.00"),
        "currency": "USD",
        "reference_balance": D("10000.00"),
        "server_offset_hours": 0,
    }
    account = Account(**(fields | kw))
    session.add(account)
    session.commit()
    return account


def synced(session: Session, account: Account, balance: str, equity: str, at: datetime) -> None:
    account.balance = D(balance)
    account.equity = D(equity)
    account.balance_synced_at = at
    session.commit()


def home(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/home", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def firm_day(client: TestClient, account: Account) -> dict[str, Any] | None:
    day: dict[str, Any] | None = home(client, account_id=account.id)["limits"]["firm_day"]
    return day


@pytest.fixture
def config_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield config
    reload_config()


# --- AccountOut.firm_rules -------------------------------------------------------------------


def test_account_of_a_known_firm_lists_its_effective_rules(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)

    data = client.get(f"/api/accounts/{account.id}").json()

    rules = data["firm_rules"]
    assert rules["firm"] == "KeyFunding"
    assert rules["source"] == "firm"
    assert D(rules["daily_loss_pct"]) == D(4)
    assert D(rules["max_loss_pct"]) == D(8)
    assert D(rules["profit_target_pct"]) == D(8)  # phase_1
    assert rules["max_loss_type"] == "static"
    assert rules["daily_basis"] == "balance"
    assert rules["daily_reset"] == "00:00"
    assert rules["reset_timezone"] == "server"
    assert rules["to_verify"] == ["daily_basis", "daily_reset"]


def test_account_values_override_in_the_listed_rules_and_phase_2_target(
    client: TestClient, session: Session
) -> None:
    key_account(session, phase="phase_2", max_drawdown_pct=D("6"), daily_loss_pct=D("3"))

    rules = client.get("/api/accounts").json()["items"][0]["firm_rules"]

    assert (D(rules["max_loss_pct"]), D(rules["daily_loss_pct"])) == (D(6), D(3))
    assert D(rules["profit_target_pct"]) == D(4)


def test_funded_key_account_has_no_target(client: TestClient, session: Session) -> None:
    account = key_account(session, phase="funded")

    rules = client.get(f"/api/accounts/{account.id}").json()["firm_rules"]

    assert rules["profit_target_pct"] is None


def test_fundednext_account_shows_the_rules_yaml_fallback(
    client: TestClient, session: Session
) -> None:
    account = add_account(session, "Alpha", 1)

    rules = client.get(f"/api/accounts/{account.id}").json()["firm_rules"]

    assert rules["source"] == "fallback"
    assert rules["firm"] == "FundedNext"
    assert D(rules["max_loss_pct"]) == D(10)
    assert rules["daily_loss_pct"] is None
    assert rules["to_verify"] == []


def test_firm_rules_are_null_without_any_rule(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    path = config_copy / "rules.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index("account_limits:")
    path.write_text("\n".join(lines[:start] + lines[start + 3 :]) + "\n", encoding="utf-8")
    reload_config()
    account = add_account(session, "Alpha", 1)

    assert client.get(f"/api/accounts/{account.id}").json()["firm_rules"] is None


def test_account_api_survives_a_broken_rules_yaml_but_reports_a_broken_firms_yaml(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    account = key_account(session)
    (config_copy / "firms.yaml").write_text("firms:\n  KeyFunding: {bogus: 1}\n", encoding="utf-8")
    reload_config()

    response = client.get(f"/api/accounts/{account.id}")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"
    assert response.json()["error"]["details"]["file"] == "firms.yaml"


def test_ctrader_style_account_gets_the_same_rules(client: TestClient, session: Session) -> None:
    from app.api.accounts import to_schema

    account = key_account(
        session,
        name="cTrader Key",
        login=99,
        platform="ctrader",
        ctid_trader_account_id=555,
        ctrader_is_live=True,
        server_offset_hours=None,
    )

    schema = to_schema(account)

    assert schema.firm_rules is not None
    assert schema.firm_rules.source == "firm"


# --- home: firm_day --------------------------------------------------------------------------


def test_firm_day_from_a_fresh_balance(client: TestClient, session: Session) -> None:
    account = key_account(session)
    closed(session, account, TODAY, "-200.00")
    open_position(session, account)
    synced(session, account, "9800.00", "9700.00", FRESH)  # floating -100

    assert firm_day(client, account) == {
        "reset_at": "2026-11-12T00:00:00Z",
        "start_balance": "10000.00",
        "floor": "9600.00",
        "loss_pct": "-4.0000",
        "pnl_pct": "-3.0000",
        "room_pct": "1.0000",
        "breached": False,
        "to_verify": ["daily_basis", "daily_reset"],
    }


def test_firm_day_is_breached_at_exactly_the_floor(client: TestClient, session: Session) -> None:
    account = key_account(session)
    open_position(session, account)
    synced(session, account, "10000.00", "9600.00", FRESH)

    day = firm_day(client, account)

    assert day is not None
    assert (day["room_pct"], day["breached"]) == ("0.0000", True)


def test_firm_day_without_a_fresh_sync_uses_the_trades_and_has_no_pct_while_open(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    closed(session, account, TODAY - timedelta(days=2), "300.00")
    closed(session, account, TODAY, "-100.00")
    open_position(session, account)
    synced(session, account, "9900.00", "9800.00", STALE)  # floating unknown

    day = firm_day(client, account)

    assert day is not None
    assert day["start_balance"] == "10300.00"  # size + closed before the reset
    assert day["floor"] == "9900.00"
    assert (day["pnl_pct"], day["room_pct"], day["breached"]) == (None, None, False)


def test_firm_day_without_a_sync_and_without_open_trades_counts_closed_only(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    closed(session, account, TODAY, "-150.00")

    day = firm_day(client, account)

    assert day is not None
    assert (day["start_balance"], day["pnl_pct"], day["room_pct"]) == (
        "10000.00",
        "-1.5000",
        "2.5000",
    )


def test_firm_day_excludes_a_trade_closed_before_the_reset_but_brussels_day_has_it(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    closed(session, account, BEFORE_RESET, "-300.00")

    limits = home(client, account_id=account.id)["limits"]

    assert limits["day"]["pct"] == "-3.0000"  # Brussels day (23:00 UTC start)
    assert limits["firm_day"]["pnl_pct"] == "0.0000"  # firm day started 00:00 UTC
    assert limits["firm_day"]["start_balance"] == "9700.00"  # trades-only: size - 300


def test_firm_day_follows_the_server_offset(client: TestClient, session: Session) -> None:
    account = key_account(session, server_offset_hours=2)
    closed(session, account, BEFORE_RESET, "-300.00")  # 23:30 UTC is after the 22:00 reset

    day = firm_day(client, account)

    assert day is not None
    assert day["reset_at"] == "2026-11-11T22:00:00Z"
    assert day["pnl_pct"] == "-3.0000"


def test_unknown_server_offset_means_utc(client: TestClient, session: Session) -> None:
    account = key_account(session, server_offset_hours=None)

    day = firm_day(client, account)

    assert day is not None
    assert day["reset_at"] == "2026-11-12T00:00:00Z"


def test_open_trade_cash_booked_after_the_reset_is_part_of_the_firm_day(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    open_position(session, account, net_pnl=D("-7.00"), commission=D("-7.00"))
    synced(session, account, "9993.00", "9993.00", FRESH)

    day = firm_day(client, account)

    assert day is not None
    assert day["start_balance"] == "10000.00"
    assert day["pnl_pct"] == "-0.0700"


def test_fundednext_account_has_no_firm_day(client: TestClient, session: Session) -> None:
    account = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    closed(session, account, TODAY, "-900.00")

    assert firm_day(client, account) is None


def test_missing_firms_file_gives_no_firm_day_and_the_old_limits(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    (config_copy / "firms.yaml").unlink()
    reload_config()
    account = key_account(session)

    data = home(client, account_id=account.id)

    assert data["limits"]["firm_day"] is None
    assert data["kpis"]["max_loss"]["limit_pct"] == "-10.0000"  # rules.yaml fallback


def test_broken_firms_file_is_a_visible_config_error(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    key_account(session)
    (config_copy / "firms.yaml").write_text("firms:\n  KeyFunding: {bogus: 1}\n", encoding="utf-8")
    reload_config()

    response = client.get("/api/home")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"
    assert response.json()["error"]["details"]["file"] == "firms.yaml"


# --- home: effective max loss / target -------------------------------------------------------


def test_max_loss_and_month_bar_use_the_firm_static_floor(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    synced(session, account, "12000.00", "12000.00", FRESH)

    data = home(client, account_id=account.id)

    kpi = data["kpis"]["max_loss"]
    assert (kpi["limit_pct"], kpi["pct"]) == ("-8.0000", "28.0000")  # (12000 - 9200) / 10000
    month = data["limits"]["month"]
    assert (month["loss_pct"], month["profit_pct"]) == ("-8.0000", "8.0000")


def test_phase_2_and_funded_targets_on_the_month_bar(client: TestClient, session: Session) -> None:
    phase_2 = key_account(session, "P2", 8, phase="phase_2")
    funded = key_account(session, "F", 9, phase="funded")

    assert home(client, account_id=phase_2.id)["limits"]["month"]["profit_pct"] == "4.0000"
    assert home(client, account_id=funded.id)["limits"]["month"]["profit_pct"] is None


def test_account_settings_override_the_firm_on_home(client: TestClient, session: Session) -> None:
    account = key_account(session, max_drawdown_pct=D("6.0"), profit_target_pct=D("5.0"))

    month = home(client, account_id=account.id)["limits"]["month"]

    assert (month["loss_pct"], month["profit_pct"]) == ("-6.0000", "5.0000")


def test_fundednext_month_bar_and_max_loss_are_unchanged(
    client: TestClient, session: Session
) -> None:
    account = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))

    data = home(client, account_id=account.id)

    assert (data["limits"]["month"]["loss_pct"], data["limits"]["month"]["profit_pct"]) == (
        "-10.0000",
        "10.0000",
    )
    assert data["kpis"]["max_loss"]["limit_pct"] == "-10.0000"


# --- dashboard stop flags --------------------------------------------------------------------


def stop(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    flags: dict[str, Any] = response.json()["stop"]
    return flags


def test_dashboard_stop_flags_default_to_false(client: TestClient, session: Session) -> None:
    key_account(session)

    assert stop(client) == {
        "today": False,
        "week": False,
        "firm_day": False,
        "firm_max_loss": False,
    }


def test_dashboard_flags_a_breached_firm_day(client: TestClient, session: Session) -> None:
    account = key_account(session)
    open_position(session, account)
    synced(session, account, "10000.00", "9600.00", FRESH)

    flags = stop(client)

    assert flags["firm_day"] is True
    assert flags["firm_max_loss"] is False


def test_dashboard_firm_day_not_breached_just_above_the_floor(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    open_position(session, account)
    synced(session, account, "10000.00", "9600.01", FRESH)

    assert stop(client)["firm_day"] is False


def test_dashboard_flags_the_static_max_loss_floor(client: TestClient, session: Session) -> None:
    account = key_account(session)
    synced(session, account, "9200.00", "9200.00", FRESH)

    assert stop(client)["firm_max_loss"] is True


def test_dashboard_static_floor_does_not_move_after_profit(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    closed(session, account, TODAY - timedelta(days=5), "2000.00")
    synced(session, account, "9201.00", "9201.00", FRESH)

    assert stop(client)["firm_max_loss"] is False


def test_dashboard_firm_flags_ignore_fundednext_accounts(
    client: TestClient, session: Session
) -> None:
    account = add_account(session, "Alpha", 1, reference_balance=D("10000.00"))
    open_position(session, account)
    synced(session, account, "10000.00", "5000.00", FRESH)

    flags = stop(client)

    assert (flags["firm_day"], flags["firm_max_loss"]) == (False, False)


def test_dashboard_broken_firms_file_is_a_config_error(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    key_account(session)
    (config_copy / "firms.yaml").write_text("not: [valid", encoding="utf-8")
    reload_config()

    response = client.get("/api/dashboard")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"
