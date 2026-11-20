"""M8-10b ``GET /api/home`` (docs/api.md "M8-10b - «Головна» rebuild").

Pinned here (also in docs/api.md / DECISIONS): ``account_id`` may name any non-archived
account (archived / unknown -> 404); all accounts = active ones. Session is ``outside`` on
non-trading days (rules.yaml sync.trading_days). ``pre_ny_missing`` only Mon-Fri.
``price_time`` stays set for a stale snapshot entry (the «дані застаріли HH:MM» note).
"""

from __future__ import annotations

import json
import re
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
from app.models import Account, BiasEntry, BiasNote, SyncLog, Trade
from app.models.enums import AccountStatus, BiasKind
from app.services import open_positions_snapshot as snap
from tests.test_dashboard_api import closed, open_position
from tests.test_trades_api import add_account

D = Decimal
# Thu 2026-11-12 14:00 UTC = 15:00 Brussels (UTC+1): NY session, week Mon 9th, month Nov.
NOW = datetime(2026, 11, 12, 14, 0, tzinfo=UTC)
TODAY = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
MON = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
NOV_3 = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
OCT_20 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
MIDNIGHT = "2026-11-11T23:00:00Z"  # Brussels midnight of the 12th
# M8-01: an excluded trade (strategy statistics out, account money in).
EXCLUDED: dict[str, Any] = {
    "excluded_from_stats": True,
    "excluded_reason": "test trade",
    "excluded_at": TODAY,
}


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


@pytest.fixture
def clock(app: FastAPI) -> list[datetime]:
    now = [NOW]
    app.dependency_overrides[utc_now] = lambda: now[0]
    return now


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, app: FastAPI, settings: Settings, clock: list[datetime]) -> Path:
    custom = settings.model_copy(update={"data_dir": tmp_path.resolve()})
    app.dependency_overrides[get_settings] = lambda: custom
    snap._warned.clear()
    return tmp_path.resolve()


@pytest.fixture
def alpha(session: Session) -> Account:
    return add_account(session, "Alpha", 1, reference_balance=D("10000.00"))


def home(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/home", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def write_snapshot(data_dir: Path, values: dict[str, Any]) -> None:
    (data_dir / snap.SNAPSHOT_FILE).write_text(json.dumps(values), encoding="utf-8")


def live(price: str, profit: str, at: datetime) -> dict[str, str]:
    return {"price_current": price, "profit": profit, "time": at.isoformat()}


def rules_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edit: Any) -> Iterator[None]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    path = config / "rules.yaml"
    path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield
    reload_config()


# --- header ----------------------------------------------------------------------------------


def test_now_timezone_and_the_ny_session(client: TestClient) -> None:
    data = home(client)

    assert (data["now"], data["timezone"]) == ("2026-11-12T14:00:00Z", "Europe/Brussels")
    assert data["session"] == {"key": "ny", "entries_allowed": True}


@pytest.mark.parametrize(
    ("at", "key", "allowed"),
    [
        (datetime(2026, 11, 12, 7, 30, tzinfo=UTC), "london", True),
        (datetime(2026, 11, 12, 10, 30, tzinfo=UTC), "premarket", False),
        (datetime(2026, 11, 12, 15, 0, tzinfo=UTC), "outside", False),
        (datetime(2026, 11, 14, 8, 0, tzinfo=UTC), "outside", False),  # Saturday 09:00
    ],
)
def test_session_follows_brussels_time_and_trading_days(
    client: TestClient, clock: list[datetime], at: datetime, key: str, allowed: bool
) -> None:
    clock[0] = at

    assert home(client)["session"] == {"key": key, "entries_allowed": allowed}


def add_note(session: Session, kind: BiasKind, day: Any, entries: dict[str, str]) -> None:
    note = BiasNote(kind=kind.value, period_date=day)
    note.entries = [BiasEntry(symbol=s, direction=d) for s, d in entries.items()]
    session.add(note)
    session.commit()


def test_bias_today_without_notes(client: TestClient) -> None:
    assert home(client)["bias_today"] == {"pre_london": None, "pre_ny_missing": True}


def test_bias_today_lists_the_pre_london_entries(client: TestClient, session: Session) -> None:
    today = TODAY.date()
    add_note(session, BiasKind.PRE_LONDON, today, {"EURUSD": "bullish", "GER40": "bearish"})
    add_note(session, BiasKind.PRE_LONDON, today - timedelta(days=1), {"XAUUSD": "bullish"})
    add_note(session, BiasKind.PRE_NY, today, {"XAUUSD": "neutral"})

    assert home(client)["bias_today"] == {
        "pre_london": [
            {"symbol": "EURUSD", "direction": "bullish"},
            {"symbol": "GER40", "direction": "bearish"},
        ],
        "pre_ny_missing": False,
    }


def test_pre_ny_is_not_missing_at_the_weekend(client: TestClient, clock: list[datetime]) -> None:
    clock[0] = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)  # Sunday

    assert home(client)["bias_today"]["pre_ny_missing"] is False


# --- limits ----------------------------------------------------------------------------------


def test_limits_of_one_account(client: TestClient, session: Session, alpha: Account) -> None:
    closed(session, alpha, TODAY, "250.00")
    closed(session, alpha, TODAY + timedelta(hours=1), "-40.00", **EXCLUDED)
    closed(session, alpha, MON, "100.00")
    closed(session, alpha, NOV_3, "-300.00")
    closed(session, alpha, OCT_20, "999.00")  # last month: never counted
    open_position(session, alpha)

    limits = home(client, account_id=alpha.id)["limits"]

    assert limits == {
        "account_id": alpha.id,
        "account_name": "Alpha",
        "currency": "USD",
        "day": {"pct": "2.1000", "loss_pct": "-3.0000", "profit_pct": "5.0000"},
        "week": {"pct": "3.1000", "loss_pct": "-6.0000", "profit_pct": "10.0000"},
        "month": {"pct": "0.1000", "loss_pct": "-10.0000", "profit_pct": "10.0000"},
        "trades_week": 4,  # 3 closed this week (one excluded) + the open one
        "max_trades_week": 10,
        "to_daily_stop_pct": "5.1000",
        # an open position without a worker balance sync: closed P&L only, flagged
        "floating_pnl": None,
        "floating_included": False,
    }


def test_week_starting_in_the_previous_month_counts_its_trades(
    client: TestClient, session: Session, alpha: Account, clock: list[datetime]
) -> None:
    clock[0] = datetime(2026, 12, 1, 14, 0, tzinfo=UTC)  # Tue; the week began Mon 30 Nov
    closed(session, alpha, datetime(2026, 11, 30, 9, 0, tzinfo=UTC), "100.00")

    limits = home(client)["limits"]

    assert (limits["week"]["pct"], limits["month"]["pct"], limits["trades_week"]) == (
        "1.0000",
        "0.0000",
        1,
    )


def test_all_accounts_show_the_one_closest_to_its_daily_stop(
    client: TestClient, session: Session, alpha: Account
) -> None:
    beta = add_account(session, "Beta", 2, reference_balance=D("20000.00"))
    gone = add_account(session, "Old", 3, status=AccountStatus.PASSED.value)
    closed(session, alpha, TODAY, "210.00")  # +2.1 % -> 5.1 to the stop
    closed(session, beta, TODAY, "-500.00")  # -2.5 % -> 0.5 to the stop
    closed(session, gone, TODAY, "-2900.00")  # not active: not a candidate

    assert home(client)["limits"]["account_id"] == beta.id
    assert home(client)["limits"]["to_daily_stop_pct"] == "0.5000"
    assert home(client, account_id=alpha.id)["limits"]["account_id"] == alpha.id
    assert home(client, account_id=gone.id)["limits"]["account_name"] == "Old"


def test_no_accounts_means_no_limits(client: TestClient) -> None:
    data = home(client)

    assert data["limits"] is None
    assert data["open_positions"] == []
    assert data["open_totals"] == {"pnl": "0.00", "risk_pct": "0.0000", "price_time": None}


def test_unknown_or_archived_account_is_404(client: TestClient, session: Session) -> None:
    old = add_account(session, "Old", 3, status=AccountStatus.ARCHIVED.value)

    for account_id in (old.id, 999):
        response = client.get("/api/home", params={"account_id": account_id})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


@pytest.fixture
def no_account_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def edit(source: str) -> str:
        return re.sub(r"^account_limits:\n(  .*\n)+", "", source, flags=re.MULTILINE)

    yield from rules_copy(tmp_path, monkeypatch, edit)


def test_month_bar_without_account_limits(
    client: TestClient, alpha: Account, no_account_limits: None
) -> None:
    data = home(client)

    assert data["limits"]["month"] == {"pct": "0.0000", "loss_pct": None, "profit_pct": None}
    assert data["kpis"]["drawdown"]["limit_pct"] is None


@pytest.fixture
def broken_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    yield from rules_copy(tmp_path, monkeypatch, lambda _: "timezone: [not, valid\n")


def test_broken_rules_yaml_is_a_config_error(client: TestClient, broken_rules: None) -> None:
    response = client.get("/api/home")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "config_error"


def test_mixed_currencies_are_409(client: TestClient, session: Session, alpha: Account) -> None:
    euro = add_account(session, "Euro", 2, reference_balance=D("10000.00"))
    euro.currency = "EUR"
    session.commit()
    closed(session, alpha, TODAY, "10.00")
    closed(session, euro, TODAY, "10.00")

    response = client.get("/api/home")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mixed_currency"
    assert client.get("/api/home", params={"account_id": euro.id}).status_code == 200


# --- KPIs ------------------------------------------------------------------------------------


def test_today_kpi_runs_from_zero_at_brussels_midnight(
    client: TestClient, session: Session, alpha: Account
) -> None:
    closed(session, alpha, TODAY, "250.00")
    closed(session, alpha, TODAY + timedelta(hours=1), "-50.00", **EXCLUDED)
    closed(session, alpha, MON, "100.00")

    today = home(client)["kpis"]["today"]

    assert (today["pnl"], today["pct"], today["trades"]) == ("200.00", "2.0000", 2)
    assert today["series"] == [
        {"time": MIDNIGHT, "cum_pnl": "0.00"},
        {"time": "2026-11-12T09:00:00Z", "cum_pnl": "250.00"},
        {"time": "2026-11-12T10:00:00Z", "cum_pnl": "200.00"},
    ]


def test_win_rate_and_avg_r_are_the_last_20_rolling_points(
    client: TestClient, session: Session, alpha: Account
) -> None:
    # 5 losses (-1R) then 20 wins (+1R): the last window holds only wins.
    for i in range(25):
        win = i >= 5
        closed(session, alpha, OCT_20 + timedelta(hours=i), "100.00" if win else "-100.00",
               r_multiple=D(1) if win else D(-1))  # fmt: skip
    closed(session, alpha, TODAY, "-500.00", r_multiple=D(-5), **EXCLUDED)

    kpis = home(client)["kpis"]

    win_rate, avg_r = kpis["win_rate"], kpis["avg_r"]
    assert (win_rate["value"], win_rate["n"], win_rate["window"]) == ("100.0000", 20, 20)
    assert (avg_r["value"], avg_r["n"], avg_r["window"]) == ("1.0000", 20, 20)
    assert len(win_rate["series"]) == len(avg_r["series"]) == 20
    # The first shown point is trade 6: window 1..6 = 5 losses + 1 win.
    assert win_rate["series"][0] == {"time": "2026-10-20T14:00:00Z", "value": "16.6667"}
    assert avg_r["series"][0]["value"] == "-0.6667"
    assert win_rate["series"][-1]["time"] == "2026-10-21T09:00:00Z"  # excluded trade out


def test_rolling_kpis_without_trades(client: TestClient, alpha: Account) -> None:
    kpis = home(client)["kpis"]

    assert kpis["win_rate"] == {"value": None, "n": 0, "window": 20, "series": []}
    assert kpis["avg_r"] == {"value": None, "n": 0, "window": 20, "series": []}


def test_drawdown_from_the_running_peak_this_month(
    client: TestClient, session: Session, alpha: Account
) -> None:
    closed(session, alpha, OCT_20, "-999.00")  # last month
    closed(session, alpha, NOV_3, "200.00")
    closed(session, alpha, MON, "-500.00", **EXCLUDED)  # real money
    closed(session, alpha, TODAY, "100.00")

    drawdown = home(client)["kpis"]["drawdown"]

    assert (drawdown["pct"], drawdown["limit_pct"]) == ("-4.0000", "-10.0000")
    assert drawdown["series"] == [
        {"time": "2026-10-31T23:00:00Z", "pct": "0.0000"},
        {"time": "2026-11-03T09:00:00Z", "pct": "0.0000"},
        {"time": "2026-11-09T09:00:00Z", "pct": "-5.0000"},
        {"time": "2026-11-12T09:00:00Z", "pct": "-4.0000"},
    ]


def test_drawdown_without_a_size_is_null(client: TestClient, session: Session) -> None:
    add_account(session, "Sizeless", 5, reference_balance=D("0"))

    drawdown = home(client)["kpis"]["drawdown"]

    assert (drawdown["pct"], drawdown["series"]) == (None, [])


# --- open positions --------------------------------------------------------------------------


@pytest.fixture
def position(session: Session, alpha: Account) -> Trade:
    # buy 2650, initial SL 2640 (10 points = 1R), TP 2670 (2R)
    return open_position(
        session,
        alpha,
        mae_r=D("-0.4"),
        mfe_r=D("0.9"),
        excursion_status="running",
        described_at=TODAY,
    )


def test_open_position_with_a_fresh_snapshot(
    client: TestClient, data_dir: Path, alpha: Account, position: Trade
) -> None:
    at = NOW - timedelta(minutes=1)
    write_snapshot(
        data_dir, {str(alpha.id): {str(position.position_id): live("2655", "250.5", at)}}
    )

    data = home(client)

    [item] = data["open_positions"]
    assert item == {
        "trade_id": position.id,
        "symbol": "XAUUSD",
        "direction": "buy",
        "volume": "0.50000000",
        "account_id": alpha.id,
        "account_name": "Alpha",
        "open_time": "2026-11-12T09:00:00Z",
        "entry_price": "2650.00000000",
        "initial_sl": "2640.00000000",
        "tp": "2670.00000000",
        "current_price": "2655",
        "price_time": "2026-11-12T13:59:00Z",
        "pnl": "250.50",
        "r_now": "0.5000",
        "tp_r": "2.0000",
        "mae_r": "-0.4000",
        "mfe_r": "0.9000",
        "risk_pct": "1.0000",
        "described": True,
        "close_unconfirmed": False,
    }
    assert data["open_totals"] == {
        "pnl": "250.50",
        "risk_pct": "1.0000",
        "price_time": "2026-11-12T13:59:00Z",
    }


def test_stale_snapshot_keeps_only_the_price_time(
    client: TestClient, data_dir: Path, alpha: Account, position: Trade
) -> None:
    at = NOW - timedelta(minutes=6)
    write_snapshot(data_dir, {str(alpha.id): {str(position.position_id): live("2655", "250", at)}})

    data = home(client)

    [item] = data["open_positions"]
    assert (item["current_price"], item["pnl"], item["r_now"]) == (None, None, None)
    assert item["price_time"] == "2026-11-12T13:54:00Z"
    assert item["tp_r"] == "2.0000"  # from the stored SL / TP, not the snapshot
    assert data["open_totals"]["pnl"] is None


SYNC_AT = NOW - timedelta(minutes=2)


def _synced(session: Session, account: Account, at: datetime = SYNC_AT) -> None:
    session.add(SyncLog(account_id=account.id, started_at=at, ok=True))
    session.commit()


def _snapshot_of(account: Account, at: datetime = SYNC_AT) -> dict[str, Any]:
    """The account's entry is empty: its sync at ``at`` saw no position."""
    stamp = at.isoformat().replace("+00:00", "Z")
    return {str(account.id): {}, snap.SYNCED_KEY: {str(account.id): stamp}}


def test_position_mt5_no_longer_reports_is_close_unconfirmed(
    client: TestClient, session: Session, data_dir: Path, alpha: Account, position: Trade
) -> None:
    """Owner bug 2026-11-20: the latest successful sync of the account saw no such position
    (its close is not in the history yet): never a live card, the UI says so."""
    _synced(session, alpha)
    write_snapshot(data_dir, _snapshot_of(alpha))

    data = home(client)

    [item] = data["open_positions"]
    assert item["close_unconfirmed"] is True
    assert (item["current_price"], item["price_time"], item["pnl"]) == (None, None, None)
    assert data["open_totals"]["pnl"] is None


@pytest.mark.parametrize(
    "case", ["no-entry", "old-file-format", "snapshot-older-than-last-sync", "never-synced"]
)
def test_snapshot_not_from_the_latest_sync_is_not_unconfirmed(
    client: TestClient,
    session: Session,
    data_dir: Path,
    alpha: Account,
    position: Trade,
    case: str,
) -> None:
    """Unknown is not «closed»: no entry, a file without sync times, a snapshot write that
    failed or is still pending after a newer sync, or no successful sync at all."""
    if case != "never-synced":
        _synced(session, alpha)
    content = {
        "no-entry": {str(alpha.id + 999): {}},
        "old-file-format": {str(alpha.id): {}},
        "snapshot-older-than-last-sync": _snapshot_of(alpha, SYNC_AT - timedelta(minutes=15)),
        "never-synced": _snapshot_of(alpha),
    }[case]
    write_snapshot(data_dir, content)

    [item] = home(client)["open_positions"]
    assert item["close_unconfirmed"] is False


@pytest.mark.parametrize("content", [None, "{broken", "[]"])
def test_missing_or_broken_snapshot_never_fails(
    client: TestClient, data_dir: Path, position: Trade, content: str | None
) -> None:
    if content is not None:
        (data_dir / snap.SNAPSHOT_FILE).write_text(content, encoding="utf-8")

    data = home(client)

    [item] = data["open_positions"]
    assert (item["current_price"], item["price_time"], item["pnl"]) == (None, None, None)
    assert data["open_totals"] == {"pnl": None, "risk_pct": "1.0000", "price_time": None}


def test_open_positions_of_every_active_account_whatever_the_selection(
    client: TestClient, session: Session, alpha: Account, position: Trade
) -> None:
    """M8-10b fixes A: an open position is live risk, never hidden by the account filter."""
    beta = add_account(session, "Beta", 2, reference_balance=D("20000.00"))
    other = open_position(session, beta, symbol="EURUSD", initial_sl=None, risk_pct=None,
                          described_at=None)  # fmt: skip

    every = home(client)["open_positions"]
    only_beta = home(client, account_id=beta.id)

    assert [p["trade_id"] for p in every] == [position.id, other.id]
    assert [p["trade_id"] for p in only_beta["open_positions"]] == [position.id, other.id]
    item = only_beta["open_positions"][1]
    assert (item["tp_r"], item["risk_pct"], item["described"]) == (None, None, False)
    assert only_beta["open_totals"]["risk_pct"] is None


# --- M8-10b fixes 2026-11-20 -----------------------------------------------------------------


def test_open_position_of_another_account_shows_on_a_one_account_request(
    client: TestClient, session: Session, data_dir: Path
) -> None:
    """Real case: «FN Stellar Funded» selected, the only open position is on account 3."""
    funded = add_account(session, "FN Stellar Funded", 2, reference_balance=D("10000.00"))
    other = add_account(session, "FN Stellar 2-Step", 3, reference_balance=D("10000.00"))
    closed(session, funded, TODAY, "120.00")
    trade = open_position(session, other)
    at = NOW - timedelta(minutes=1)
    write_snapshot(data_dir, {str(other.id): {str(trade.position_id): live("2655", "77.76", at)}})

    data = home(client, account_id=funded.id)

    [item] = data["open_positions"]
    assert (item["trade_id"], item["account_id"]) == (trade.id, other.id)
    assert (item["account_name"], item["pnl"]) == ("FN Stellar 2-Step", "77.76")
    assert data["open_totals"]["pnl"] == "77.76"
    assert data["limits"]["account_id"] == funded.id
    assert data["kpis"]["today"]["pnl"] == "120.00"  # closed money stays the selection's


def test_open_positions_in_two_currencies_have_no_pnl_total_instead_of_409(
    client: TestClient, session: Session, data_dir: Path, alpha: Account
) -> None:
    euro = add_account(session, "Euro", 2, reference_balance=D("10000.00"))
    euro.currency = "EUR"
    session.commit()
    closed(session, alpha, TODAY, "10.00")
    usd, eur = open_position(session, alpha), open_position(session, euro)
    at = NOW - timedelta(minutes=1)
    write_snapshot(
        data_dir,
        {
            str(alpha.id): {str(usd.position_id): live("2655", "10", at)},
            str(euro.id): {str(eur.position_id): live("2655", "20", at)},
        },
    )

    data = home(client, account_id=alpha.id)

    assert [p["pnl"] for p in data["open_positions"]] == ["10.00", "20.00"]
    assert data["open_totals"]["pnl"] is None
    assert data["open_totals"]["risk_pct"] == "2.0000"


def synced(session: Session, account: Account, equity: str, at: datetime) -> None:
    account.balance = D("10000.00")
    account.equity = D(equity)
    account.balance_synced_at = at
    session.commit()


def test_limits_add_the_floating_pnl_of_a_fresh_balance_sync(
    client: TestClient, session: Session, alpha: Account
) -> None:
    closed(session, alpha, TODAY, "250.00")
    closed(session, alpha, MON, "100.00")
    open_position(session, alpha)
    synced(session, alpha, "10077.76", NOW - timedelta(minutes=1))

    limits = home(client, account_id=alpha.id)["limits"]

    assert (limits["floating_pnl"], limits["floating_included"]) == ("77.76", True)
    assert limits["day"]["pct"] == "3.2776"  # (250 + 77.76) / 10000
    assert limits["week"]["pct"] == "4.2776"
    assert limits["month"]["pct"] == "4.2776"
    assert limits["to_daily_stop_pct"] == "6.2776"  # 3.2776 - (-3)


def test_limits_with_a_stale_balance_sync_use_closed_trades_only(
    client: TestClient, session: Session, alpha: Account
) -> None:
    closed(session, alpha, TODAY, "250.00")
    open_position(session, alpha)
    synced(session, alpha, "10077.76", NOW - timedelta(minutes=6))

    limits = home(client, account_id=alpha.id)["limits"]

    assert (limits["floating_pnl"], limits["floating_included"]) == (None, False)
    assert (limits["day"]["pct"], limits["to_daily_stop_pct"]) == ("2.5000", "5.5000")


def test_limits_without_an_open_position_are_unchanged(
    client: TestClient, session: Session, alpha: Account
) -> None:
    closed(session, alpha, TODAY, "250.00")
    synced(session, alpha, "10000.00", NOW - timedelta(minutes=1))

    limits = home(client, account_id=alpha.id)["limits"]

    assert (limits["floating_pnl"], limits["floating_included"]) == ("0.00", True)
    assert (limits["day"]["pct"], limits["to_daily_stop_pct"]) == ("2.5000", "5.5000")


@pytest.mark.parametrize(
    ("at", "missing"),
    [
        (datetime(2026, 11, 12, 9, 59, tzinfo=UTC), False),  # 10:59 Brussels (UTC+1)
        (datetime(2026, 11, 12, 10, 0, tzinfo=UTC), True),  # 11:00
        (datetime(2026, 7, 16, 8, 59, tzinfo=UTC), False),  # Thu 10:59 Brussels (UTC+2)
        (datetime(2026, 7, 16, 9, 0, tzinfo=UTC), True),  # 11:00
    ],
)
def test_pre_ny_is_missing_only_from_the_premarket_start(
    client: TestClient, clock: list[datetime], at: datetime, missing: bool
) -> None:
    clock[0] = at

    assert home(client)["bias_today"]["pre_ny_missing"] is missing


def test_limits_count_the_entry_commission_an_open_trade_already_took_from_the_balance(
    client: TestClient, session: Session, alpha: Account
) -> None:
    """Real case «FN Stellar Funded 2» 2026-11-20: GBPUSD open with -7.56 entry commission
    (already in the MT5 balance), XAUUSD closed -96.91, floating +108.00 -> MT5 day result
    equity - day-start balance = +3.53 (0.0353 %), not 11.09."""
    closed(session, alpha, TODAY, "-96.91")
    open_position(session, alpha, net_pnl=D("-7.56"), commission=D("-7.56"))
    open_position(session, alpha, open_time=MON, net_pnl=D("-2.00"), commission=D("-2.00"))
    synced(session, alpha, "10108.00", NOW - timedelta(minutes=1))

    limits = home(client, account_id=alpha.id)["limits"]

    assert limits["day"]["pct"] == "0.0353"  # (-96.91 + 108.00 - 7.56) / 10000
    assert limits["week"]["pct"] == "0.0153"  # the Monday trade's -2.00 is this week's cash
    assert limits["to_daily_stop_pct"] == "3.0353"


# --- max loss KPI (follow-up 2026-11-20) -----------------------------------------------------


def test_max_loss_from_a_fresh_mt5_equity(
    client: TestClient, session: Session, alpha: Account
) -> None:
    """Real-like case: size 10 000, equity 10 056.25 -> floor 9 000, 10.5625 % to the limit."""
    closed(session, alpha, OCT_20, "56.25")
    synced(session, alpha, "10056.25", NOW - timedelta(minutes=1))

    kpi = home(client, account_id=alpha.id)["kpis"]["max_loss"]

    assert kpi == {
        "account_id": alpha.id,
        "account_name": "Alpha",
        "pct": "10.5625",
        "limit_pct": "-10.0000",
        "equity": "10056.25",
        "equity_source": "mt5",
        "series": [
            {"time": "2026-10-20T08:30:00Z", "pct": "10.0000"},
            {"time": "2026-10-20T09:00:00Z", "pct": "10.5625"},
            {"time": "2026-11-12T14:00:00Z", "pct": "10.5625"},
        ],
    }


def test_max_loss_with_a_stale_sync_uses_the_balance(
    client: TestClient, session: Session, alpha: Account
) -> None:
    synced(session, alpha, "10300.00", NOW - timedelta(minutes=6))  # balance 10 000

    kpi = home(client, account_id=alpha.id)["kpis"]["max_loss"]

    assert (kpi["equity"], kpi["equity_source"], kpi["pct"]) == ("10000.00", "balance", "10.0000")


def test_max_loss_never_synced_adds_every_closed_trade_and_open_trade_cash(
    client: TestClient, session: Session, alpha: Account
) -> None:
    closed(session, alpha, OCT_20, "-200.00")
    closed(session, alpha, TODAY, "-40.00", **EXCLUDED)  # real money: counts
    open_position(session, alpha, net_pnl=D("-7.56"), commission=D("-7.56"))

    kpi = home(client, account_id=alpha.id)["kpis"]["max_loss"]

    assert (kpi["equity"], kpi["equity_source"]) == ("9752.44", "trades")
    assert kpi["pct"] == "7.5244"  # (9752.44 - 9000) / 10000
    assert [p["pct"] for p in kpi["series"]] == ["10.0000", "8.0000", "7.6000", "7.5244"]


def test_max_loss_of_all_accounts_is_the_one_closest_to_its_floor(
    client: TestClient, session: Session, alpha: Account
) -> None:
    beta = add_account(session, "Beta", 2, reference_balance=D("20000.00"))
    gone = add_account(session, "Old", 3, status=AccountStatus.PASSED.value)
    add_account(session, "No size", 4, reference_balance=D("0.00"))
    closed(session, alpha, TODAY, "-300.00")  # 7 %
    closed(session, beta, TODAY, "-1000.00")  # 5 %: closest
    closed(session, gone, TODAY, "-1900.00")  # not active: not a candidate

    assert home(client)["kpis"]["max_loss"]["account_id"] == beta.id
    assert home(client)["kpis"]["max_loss"]["pct"] == "5.0000"
    assert home(client, account_id=gone.id)["kpis"]["max_loss"]["account_name"] == "Old"


def test_max_loss_is_null_without_account_limits_or_accounts(
    client: TestClient, alpha: Account, no_account_limits: None
) -> None:
    assert home(client)["kpis"]["max_loss"] is None


def test_max_loss_is_null_without_any_account(client: TestClient) -> None:
    assert home(client)["kpis"]["max_loss"] is None


def test_max_loss_and_month_bar_use_the_account_firm_rules_from_settings(
    client: TestClient, session: Session, alpha: Account
) -> None:
    """Real accounts: Settings «макс. просідання» 8 %, no profit target (funded) -> floor
    9 200 instead of the rules.yaml -10 % fallback; the month bar has no target."""
    alpha.max_drawdown_pct = D("8.0000")
    alpha.profit_target_pct = None
    session.commit()
    closed(session, alpha, OCT_20, "56.25")
    synced(session, alpha, "10056.25", NOW - timedelta(minutes=1))

    data = home(client, account_id=alpha.id)

    kpi = data["kpis"]["max_loss"]
    assert (kpi["limit_pct"], kpi["pct"]) == ("-8.0000", "8.5625")  # (10056.25 - 9200) / 10000
    month = data["limits"]["month"]
    assert (month["loss_pct"], month["profit_pct"]) == ("-8.0000", None)
