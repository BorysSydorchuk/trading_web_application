"""«Ліміти» firm alert and account pick through GET /api/home (PM 2026-11-26).

NOW = Thu 2026-11-12 14:00 UTC (see tests/test_firm_rules_api.py). Key accounts: size 10 000,
daily 4 %, static max loss 8 % (floor 9 200). FundedNext: firm rules from Settings only.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests import test_firm_rules_api as base
from tests.test_dashboard_api import closed
from tests.test_firm_rules_api import FRESH, TODAY, home, key_account, synced
from tests.test_trades_api import add_account

D = Decimal

# Fixtures of tests/test_firm_rules_api.py (clean DB, pinned NOW, pinned firms.yaml).
_clean = base._clean
_env = base._env
config_copy = base.config_copy
session = base.session


def test_far_from_firm_limits_has_no_alert(client: TestClient, session: Session) -> None:
    account = key_account(session)
    synced(session, account, "10000.00", "10000.00", FRESH)

    assert home(client, account_id=account.id)["limits"]["firm_alert"] is None


def test_static_max_loss_within_one_percent_alerts(client: TestClient, session: Session) -> None:
    account = key_account(session)
    synced(session, account, "9250.00", "9250.00", FRESH)  # floor 9 200: room 0.5 %

    alert = home(client, account_id=account.id)["limits"]["firm_alert"]

    assert alert == {"kind": "max_loss", "room_pct": "0.5000"}


def test_firm_daily_floor_within_one_percent_alerts(client: TestClient, session: Session) -> None:
    account = key_account(session)
    closed(session, account, TODAY, "-320.00")
    synced(session, account, "9680.00", "9680.00", FRESH)  # start 10 000, floor 9 600: 0.8 %

    alert = home(client, account_id=account.id)["limits"]["firm_alert"]

    assert alert == {"kind": "firm_day", "room_pct": "0.8000"}


def test_all_accounts_puts_the_firm_alert_first(client: TestClient, session: Session) -> None:
    fn = add_account(session, "FN", 11, reference_balance=D("10000.00"))
    closed(session, fn, TODAY, "-250.00")  # personal day -2.5 %: 0.5 % to the -3 % stop
    synced(session, fn, "9750.00", "9750.00", FRESH)
    key = key_account(session)
    synced(session, key, "9250.00", "9250.00", FRESH)  # day 0 %, max-loss room 0.5 %

    limits = home(client)["limits"]

    assert (limits["account_id"], limits["firm_alert"]["kind"]) == (key.id, "max_loss")


def test_all_accounts_without_alerts_keeps_the_personal_stop_pick(
    client: TestClient, session: Session
) -> None:
    fn = add_account(session, "FN", 11, reference_balance=D("10000.00"))
    closed(session, fn, TODAY, "-250.00")
    synced(session, fn, "9750.00", "9750.00", FRESH)
    key = key_account(session)
    synced(session, key, "10000.00", "10000.00", FRESH)

    limits = home(client)["limits"]

    assert (limits["account_id"], limits["firm_alert"]) == (fn.id, None)


def test_fundednext_max_loss_from_settings_alerts_too(client: TestClient, session: Session) -> None:
    fn = add_account(session, "FN", 11, reference_balance=D("10000.00"), max_drawdown_pct=D("8"))
    synced(session, fn, "9280.00", "9280.00", FRESH)  # floor 9 200: room 0.8 %

    limits = home(client, account_id=fn.id)["limits"]

    assert (limits["firm_day"], limits["firm_alert"]) == (
        None,
        {"kind": "max_loss", "room_pct": "0.8000"},
    )
