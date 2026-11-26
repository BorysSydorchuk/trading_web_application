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
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import REPO_ROOT, Settings, get_settings
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.db import make_session_factory
from app.models import Account, RuleViolation, Trade
from tests.test_dashboard_api import closed, open_position
from tests.test_trades_api import add_account, add_exit

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


# Pinned KeyFunding rules for these tests (the real config/firms.yaml may change: EET reset,
# Borys 2026-11-26): `server` zone so the offset tests stay meaningful, both items to verify.
PINNED_FIRMS = """firms:
  KeyFunding:
    daily_loss_pct: 4.0
    max_loss_pct: 8.0
    max_loss_type: static
    profit_target_pct: { phase_1: 8.0, phase_2: 4.0 }
    daily_basis: balance
    daily_reset: "00:00"
    reset_timezone: server
    to_verify: [daily_basis, daily_reset]
"""


@pytest.fixture(autouse=True)
def config_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    (config / "firms.yaml").write_text(PINNED_FIRMS, encoding="utf-8")
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


def break_file(config: Path, name: str, text_: str = "firms:\n  KeyFunding: {bogus: 1}\n") -> None:
    (config / name).write_text(text_, encoding="utf-8")
    reload_config()


def logged(caplog: pytest.LogCaptureFixture, level: str, needle: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.levelname == level and needle in r.getMessage()
    ]


def test_accounts_with_a_broken_firms_file_show_no_rules_and_log_once_per_request(
    client: TestClient,
    session: Session,
    config_copy: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key_account(session)
    key_account(session, "Key2", 8)
    break_file(config_copy, "firms.yaml")
    caplog.clear()

    response = client.get("/api/accounts")

    assert response.status_code == 200
    assert [a["firm_rules"] for a in response.json()["items"]] == [None, None]
    assert len(logged(caplog, "ERROR", "firms.yaml")) == 1


def test_get_one_account_with_a_broken_firms_file_still_answers(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    account = key_account(session)
    break_file(config_copy, "firms.yaml")

    response = client.get(f"/api/accounts/{account.id}")

    assert response.status_code == 200
    assert response.json()["firm_rules"] is None


def test_broken_rules_file_warns_once_per_request(
    client: TestClient,
    session: Session,
    config_copy: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    key_account(session)
    key_account(session, "Key2", 8)
    break_file(config_copy, "rules.yaml", "timezone: [broken\n")
    caplog.clear()

    response = client.get("/api/accounts")

    assert response.status_code == 200
    assert len(logged(caplog, "WARNING", "rules.yaml")) == 1


def test_patch_with_a_broken_firms_file_is_refused_before_writing(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    account = key_account(session)
    break_file(config_copy, "firms.yaml")

    response = client.patch(f"/api/accounts/{account.id}", json={"name": "Renamed"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"
    session.expire_all()
    assert session.get(Account, account.id).name == "Key"  # type: ignore[union-attr]


def test_post_with_a_broken_firms_file_creates_nothing(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    break_file(config_copy, "firms.yaml")
    body = {
        "name": "New",
        "firm": "KeyFunding",
        "program": "P",
        "phase": "phase_1",
        "login": 4242,
        "server": "S",
        "starting_balance": "10000.00",
        "currency": "USD",
    }

    response = client.post("/api/accounts", json=body)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"
    assert session.query(Account).count() == 0


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


# --- review fixes ------------------------------------------------------------------------------


def firm_violation_keys(session: Session, trade_id: int) -> set[str]:
    session.expire_all()
    rows = session.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade_id))
    return {r.rule_key for r in rows}


def loss_then_entry(session: Session, account: Account, loss: str = "-450.00") -> Trade:
    closed(session, account, TODAY - timedelta(hours=7), loss)  # 02:00 UTC
    return closed(session, account, TODAY + timedelta(hours=1), "10.00", open_time=TODAY)


def test_patching_the_firm_recomputes_the_firm_violation(
    client: TestClient, session: Session
) -> None:
    account = key_account(session, firm="OtherFirm")
    entry = loss_then_entry(session, account)
    assert "firm_daily_loss" not in firm_violation_keys(session, entry.id)

    client.patch(f"/api/accounts/{account.id}", json={"firm": "KeyFunding"})
    assert "firm_daily_loss" in firm_violation_keys(session, entry.id)

    client.patch(f"/api/accounts/{account.id}", json={"firm": "OtherFirm"})
    assert "firm_daily_loss" not in firm_violation_keys(session, entry.id)


def test_patching_the_daily_loss_recomputes_the_firm_violation(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    entry = loss_then_entry(session, account, "-350.00")  # -3.5 %: inside the firm 4 %
    client.patch(f"/api/accounts/{account.id}", json={"name": "Key"})  # no rule field: no change
    assert "firm_daily_loss" not in firm_violation_keys(session, entry.id)

    response = client.patch(f"/api/accounts/{account.id}", json={"daily_loss_pct": "3"})
    assert response.status_code == 200
    assert "firm_daily_loss" in firm_violation_keys(session, entry.id)  # -3.5 % <= -3 %

    client.patch(f"/api/accounts/{account.id}", json={"daily_loss_pct": "5"})
    assert "firm_daily_loss" not in firm_violation_keys(session, entry.id)


def test_patching_the_size_with_a_broken_firms_file_changes_nothing(
    client: TestClient, session: Session, config_copy: Path
) -> None:
    account = key_account(session)
    break_file(config_copy, "firms.yaml")

    response = client.patch(f"/api/accounts/{account.id}", json={"reference_balance": "5000"})

    assert response.status_code == 500
    session.expire_all()
    assert session.get(Account, account.id).reference_balance == D("10000.00")  # type: ignore[union-attr]


def test_recompute_account_reads_firms_before_changing_anything(
    session: Session, config_copy: Path
) -> None:
    from app.config_files import ConfigError
    from app.services import risk_base

    account = key_account(session)
    trade = closed(session, account, TODAY, "-5.00", risk_amount=D("100.00"), risk_pct=D("9.9999"))
    break_file(config_copy, "firms.yaml")

    with pytest.raises(ConfigError):
        risk_base.recompute_account(session, account.id)

    session.rollback()
    session.refresh(trade)
    assert trade.risk_pct == D("9.9999")


def test_recompute_all_fails_once_for_a_broken_firms_file(
    db_engine: Engine, session: Session, config_copy: Path
) -> None:
    from app.services import risk_base

    key_account(session)
    break_file(config_copy, "firms.yaml")

    assert risk_base.recompute_all(make_session_factory(db_engine)) is None


def test_symbol_map_configs_are_unavailable_for_a_broken_firms_file(config_copy: Path) -> None:
    from app.services import symbol_map

    break_file(config_copy, "firms.yaml")

    assert symbol_map._recompute_configs() is None


def test_partial_close_after_the_reset_of_a_position_opened_before_it(
    client: TestClient, session: Session
) -> None:
    """Buy 23:00 UTC yesterday, partial -300 at 01:00 today (after the 00:00 reset): that
    realized loss belongs to today, so the start balance is 9700 + 300."""
    account = key_account(session)
    trade = open_position(
        session,
        account,
        open_time=datetime(2026, 11, 11, 23, 0, tzinfo=UTC),
        net_pnl=D("-300.00"),
        commission=D("0.00"),
    )
    add_exit(
        session,
        trade,
        900001,
        time=datetime(2026, 11, 12, 1, 0, tzinfo=UTC),
        profit=D("-300.00"),
        price=D("2640.00"),
        commission=D("0.00"),
    )
    synced(session, account, "9700.00", "9700.00", FRESH)

    day = firm_day(client, account)

    assert day is not None
    assert day["start_balance"] == "10000.00"
    assert day["floor"] == "9600.00"
    assert day["pnl_pct"] == "-3.0000"


def test_entry_commission_of_a_position_opened_before_the_reset_stays_yesterday(
    client: TestClient, session: Session
) -> None:
    account = key_account(session)
    trade = open_position(
        session,
        account,
        open_time=datetime(2026, 11, 11, 23, 0, tzinfo=UTC),
        net_pnl=D("-307.00"),
        commission=D("-7.00"),
    )
    add_exit(
        session,
        trade,
        900002,
        time=datetime(2026, 11, 12, 1, 0, tzinfo=UTC),
        profit=D("-300.00"),
        price=D("2640.00"),
        commission=D("0.00"),
    )
    synced(session, account, "9693.00", "9693.00", FRESH)

    day = firm_day(client, account)

    assert day is not None
    assert day["start_balance"] == "9993.00"  # -7 entry commission was booked yesterday


def test_account_daily_loss_override_applies_to_the_home_firm_day(
    client: TestClient, session: Session
) -> None:
    account = key_account(session, daily_loss_pct=D("2"))
    open_position(session, account)
    synced(session, account, "10000.00", "9800.00", FRESH)

    day = firm_day(client, account)

    assert day is not None
    assert (day["loss_pct"], day["floor"], day["breached"]) == ("-2.0000", "9800.00", True)


def test_account_daily_loss_override_applies_to_the_dashboard_flag(
    client: TestClient, session: Session
) -> None:
    account = key_account(session, daily_loss_pct=D("2"))
    open_position(session, account)
    synced(session, account, "10000.00", "9800.00", FRESH)

    assert stop(client)["firm_day"] is True


def test_dashboard_flags_both_when_two_firm_accounts_are_breached(
    client: TestClient, session: Session
) -> None:
    first = key_account(session, "K1", 21)
    second = key_account(session, "K2", 22)
    for account in (first, second):
        open_position(session, account)
        synced(session, account, "10000.00", "9200.00", FRESH)

    flags = stop(client)

    assert (flags["firm_day"], flags["firm_max_loss"]) == (True, True)


def test_batch_equity_uses_sync_balance_or_trades(session: Session) -> None:
    from app.services.home_max_loss import accounts_equity

    fresh = key_account(session, "F", 31)
    synced(session, fresh, "10000.00", "10123.00", FRESH)
    balance_only = key_account(session, "B", 32, balance=D("9500.00"))
    nothing = key_account(session, "N", 33)
    closed(session, nothing, TODAY, "-250.00")
    size = D("10000.00")

    result = accounts_equity(session, [(fresh, size), (balance_only, size), (nothing, size)], NOW)

    assert result == {
        fresh.id: D("10123.00"),
        balance_only.id: D("9500.00"),
        nothing.id: D("9750.00"),
    }
