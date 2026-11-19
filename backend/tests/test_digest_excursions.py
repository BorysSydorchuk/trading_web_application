"""M8-16 digest block «excursions»: average MFE of winners and losers, losers that reached
1R first (final MFE only; M8-01 exclusions apply)."""

# ruff: noqa: F811  (pytest fixtures imported from test_trade_exclusion)
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Account
from tests.test_trade_exclusion import (  # noqa: F401 (fixtures)
    TODAY,
    _clean,
    _now,
    account,
    closed,
    digest,
    exclude,
    ok,
    session,
)

D = Decimal


def test_excursion_block(client: TestClient, session: Session, account: Account) -> None:
    final = {"excursion_status": "final"}
    closed(session, account, TODAY, "200.00", "2.0", mfe_r=D("2.5"), **final)
    closed(session, account, TODAY + timedelta(minutes=5), "150.00", "1.5", mfe_r=D("1.5"), **final)
    closed(
        session, account, TODAY + timedelta(minutes=10), "-100.00", "-1.0", mfe_r=D("1.2"), **final
    )
    closed(
        session, account, TODAY + timedelta(minutes=15), "-100.00", "-1.0", mfe_r=D("0.2"), **final
    )
    # a running value (open at the time) or no value never counts
    closed(
        session,
        account,
        TODAY + timedelta(minutes=20),
        "-100.00",
        "-1.0",
        mfe_r=D("3"),
        excursion_status="running",
    )
    closed(session, account, TODAY + timedelta(minutes=25), "-100.00", "-1.0")
    excluded = closed(
        session, account, TODAY + timedelta(minutes=30), "-50.00", "-0.5", mfe_r=D("1.1"), **final
    )
    ok(exclude(client, excluded.id))

    block = digest(client)["excursions"]

    assert block == {
        "n_winners": 2,
        "n_losers": 2,
        "winners_avg_mfe_r": "2.0000",
        "losers_avg_mfe_r": "0.7000",
        "losers_reached_1r": 1,
        "losers_reached_1r_share": "50.0000",
    }


def test_empty_block_without_values(client: TestClient, session: Session, account: Account) -> None:
    closed(session, account, TODAY, "200.00", "2.0")

    assert digest(client)["excursions"] == {
        "n_winners": 0,
        "n_losers": 0,
        "winners_avg_mfe_r": None,
        "losers_avg_mfe_r": None,
        "losers_reached_1r": 0,
        "losers_reached_1r_share": None,
    }
