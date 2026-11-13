"""M6-04 (RED): digests API (docs/api.md "Digests API", "Norm and deviation", "Charts data").

Routes: ``POST /api/digests``, ``GET /api/digests``, ``GET /api/digests/{id}``,
``GET /api/digests/by-period``, ``PATCH /api/digests/{id}``, ``GET /api/digests/suggestion``.
``now`` comes from ``Depends(utc_now)``.

Response shape pinned here (additions to api.md are marked NEW):
- Digest: ``{id, kind, period_start, period_end, generated_at, what_worked, what_to_fix,
  focus_next, ai_summary, reviewed, next_bias_note_id, metrics}`` (``reviewed`` on the full
  digest too: NEW).
- ``metrics`` = snapshot ``{currency, combined, by_account, breakdowns, rules, bias, charts,
  trade_ids}`` (``currency`` NEW).
- ``combined`` = ``{norm_available, metrics: {<name>: {value, norm_mean, norm_sd, deviation}},
  best_trade, worst_trade}``; ``by_account[]`` = the same plus ``account_id``, ``account_name``
  (NEW), ordered by account id; only accounts with a trade in the period. Metric names: trades,
  wins, losses, breakeven, violations (counts: ints), net_pnl, max_drawdown (money, 2 dp strings),
  net_pnl_pct, max_drawdown_pct, win_rate, total_r, avg_win_r, avg_loss_r, expectancy_r,
  profit_factor (4 dp strings, null when undefined). ``total_r`` also has ``n`` (NEW). Norm
  numbers use the metric's own format (money 2 dp, rest 4 dp).
- ``breakdowns``: ``{<field>: {groups: [{key, trades, net_pnl, total_r, win_rate}], coverage:
  {filled, total}}}``; order = symbol, session, hour, weekday, bias_alignment, then the
  ``analytics: true`` journal fields in file order (columns and ``extra``), skipping relation /
  multi_enum fields (rule_violations) and bias_alignment (already a trade field) (NEW decision).
- ``rules``: ``{rules: [{rule_key, violations, trades, pnl}], violated_trades, violated_pnl}``.
- ``bias``: ``{daily|weekly|monthly: {accuracy: {value, marked, total}, aligned: {trades,
  net_pnl, total_r}, counter: {...}}}``. Weekly digest: daily = pre_london/pre_ny notes inside
  the week, weekly = the week's note, monthly = the note of the month of the period start (NEW).
- ``charts``: ``{equity: {combined: [{time, cum_pnl}], by_account: [{account_id, points}]},
  r_distribution: [{lower, upper, count}], hour_heatmap: [{weekday, hour, trades, net_pnl}]}``.
- Mixed currencies among the accounts that have a trade in the period -> 409 ``mixed_currency``
  (NEW scope decision).
- Periods with no trades are generated normally (zeros, ``norm_available`` as usual).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
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
from app.models import Account, BiasEntry, BiasNote, Trade
from app.models.trade import RuleViolation
from tests.test_trades_api import add_account, add_trade

D = Decimal
# Sat 2026-11-14 12:00 UTC: the week Mon 9 - Sun 15 Nov has started, the month too.
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
WEEK = "2026-11-09"
MONTH = "2026-11-01"
ROOT_SIZE = D("10000.00")


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts, digests, bias_notes RESTART IDENTITY CASCADE"))

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
def set_now(app: FastAPI) -> Callable[[datetime], None]:
    def _set(value: datetime) -> None:
        app.dependency_overrides[utc_now] = lambda: value

    _set(NOW)
    return _set


def closed(
    db: Session, account: Account, close: datetime, pnl: str, r: str | None, **kw: Any
) -> Trade:
    fields: dict[str, Any] = {
        "open_time": close - timedelta(minutes=30),
        "close_time": close,
        "net_pnl": D(pnl),
        "r_multiple": None if r is None else D(r),
        "status": "complete",
    }
    # add_trade() has a positional parameter named `session`: set the trade column afterwards.
    trading_session = kw.pop("session", None)
    trade = add_trade(db, account, **(fields | kw))
    if trading_session is not None:
        trade.session = trading_session
        db.commit()
    return trade


def post(client: TestClient, kind: str = "weekly", day: str = WEEK) -> Any:
    return client.post("/api/digests", json={"kind": kind, "date": day})


def digest(client: TestClient, kind: str = "weekly", day: str = WEEK) -> dict[str, Any]:
    response = post(client, kind, day)
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def accounts(session: Session) -> tuple[Account, Account]:
    a = add_account(session, "Alpha", 1, reference_balance=ROOT_SIZE)
    b = add_account(session, "Beta", 2, reference_balance=D("20000.00"))
    return a, b


def euro_account(session: Session) -> Account:
    account = add_account(session, "Euro", 9, reference_balance=D("1000.00"))
    account.currency = "EUR"
    session.commit()
    return account


@pytest.fixture
def fixture_week(session: Session) -> dict[str, Trade]:
    """Hand-calculated week Mon 2026-11-09 (CET, UTC+1), accounts Alpha 10 000 / Beta 20 000.

    id acct  pnl    R    close(UTC)  symbol  model  bias(day/week/month; override)
    t1  A   +200   2.0   Mon 09:00   XAUUSD  ob     aligned / aligned / counter
    t2  A   -100  -1.0   Mon 14:00   XAUUSD  ob     counter / aligned / counter
    t3  B   +300   3.0   Tue 10:00   GER40   fvg    auto counter, override aligned / counter / -
    t4  B   -100  -1.0   Wed 10:00   GER40   -      -
    t5  A      0   0.0   Thu 10:00   XAUUSD  -      -         (breakeven)
    t6  A   +100  none   Fri 10:00   EURUSD  -      -         (no R)
    Excluded: archived account trade, open trade, previous Sunday 23:30 Brussels (22:30 UTC),
    next Monday 00:30 Brussels (Sun 23:30 UTC).
    """
    a, b = accounts(session)
    old = add_account(session, "Old", 3, status="archived", reference_balance=D("5000.00"))
    t1 = closed(
        session, a, datetime(2026, 11, 9, 9, tzinfo=UTC), "200.00", "2.0",
        entry_model="ob", bias_alignment="aligned", bias_alignment_weekly="aligned",
        bias_alignment_monthly="counter", session="london", hour=9, weekday=0,
    )  # fmt: skip
    t2 = closed(
        session, a, datetime(2026, 11, 9, 14, tzinfo=UTC), "-100.00", "-1.0",
        entry_model="ob", bias_alignment="counter", bias_alignment_weekly="aligned",
        bias_alignment_monthly="counter", session="ny", hour=14, weekday=0,
    )  # fmt: skip
    t3 = closed(
        session, b, datetime(2026, 11, 10, 10, tzinfo=UTC), "300.00", "3.0",
        symbol="GER40", entry_model="fvg", bias_alignment="counter",
        bias_alignment_override="aligned", bias_alignment_weekly="counter",
        session="london", hour=10, weekday=1,
    )  # fmt: skip
    t4 = closed(
        session, b, datetime(2026, 11, 11, 10, tzinfo=UTC), "-100.00", "-1.0", symbol="GER40",
        session="london", hour=10, weekday=2,
    )  # fmt: skip
    t5 = closed(session, a, datetime(2026, 11, 12, 10, tzinfo=UTC), "0.00", "0.0")
    t6 = closed(session, a, datetime(2026, 11, 13, 10, tzinfo=UTC), "100.00", None, symbol="EURUSD")
    closed(session, old, datetime(2026, 11, 10, 10, tzinfo=UTC), "-5000.00", "-9.0")
    add_trade(
        session, a, status="open", close_time=None, net_pnl=None, gross_pnl=None,
        open_time=datetime(2026, 11, 13, 9, tzinfo=UTC),
    )  # fmt: skip
    closed(session, a, datetime(2026, 11, 8, 22, 30, tzinfo=UTC), "999.00", "9.0")
    closed(session, a, datetime(2026, 11, 15, 23, 30, tzinfo=UTC), "888.00", "8.0")
    session.add_all(
        [
            RuleViolation(trade_id=t2.id, rule_key="min_planned_rr", source="auto"),
            RuleViolation(trade_id=t2.id, rule_key="max_risk_pct", source="auto"),
            RuleViolation(trade_id=t4.id, rule_key="max_risk_pct", source="auto"),
        ]
    )
    session.commit()
    return {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6}


def add_note(
    session: Session,
    kind: str,
    day: str,
    marks: list[bool | None],
    symbols: str = "XAUUSD GER40 EURUSD",
) -> BiasNote:
    note = BiasNote(kind=kind, period_date=date.fromisoformat(day))
    names = symbols.split()
    note.entries = [
        BiasEntry(symbol=names[i], direction="bullish", was_correct=m) for i, m in enumerate(marks)
    ]
    session.add(note)
    session.commit()
    return note


# --- create / regenerate ---------------------------------------------------------------------


def test_post_creates_201_and_regenerate_is_200_with_the_same_id(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    first = post(client)
    second = post(client)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["kind"] == "weekly"
    assert (first.json()["period_start"], first.json()["period_end"]) == (WEEK, "2026-11-15")
    assert first.json()["generated_at"].endswith("Z") or "+00:00" in first.json()["generated_at"]


@pytest.mark.parametrize(
    ("kind", "given", "start", "end"),
    [
        ("weekly", "2026-11-12", "2026-11-09", "2026-11-15"),
        ("weekly", "2026-11-15", "2026-11-09", "2026-11-15"),
        ("monthly", "2026-11-13", "2026-11-01", "2026-11-30"),
        ("monthly", "2026-02-27", "2026-02-01", "2026-02-28"),
    ],
)
def test_date_is_normalised_to_monday_or_the_first(
    client: TestClient, set_now: Callable[..., None], kind: str, given: str, start: str, end: str
) -> None:
    body = digest(client, kind, given)

    assert (body["period_start"], body["period_end"]) == (start, end)


def test_two_dates_of_one_week_hit_the_same_digest(
    client: TestClient, set_now: Callable[..., None]
) -> None:
    assert post(client, "weekly", "2026-11-10").status_code == 201
    assert post(client, "weekly", "2026-11-13").status_code == 200


@pytest.mark.parametrize(
    ("kind", "day"), [("weekly", "2026-11-16"), ("monthly", "2026-12-01"), ("weekly", "2027-01-04")]
)
def test_future_period_is_422_period_in_future(
    client: TestClient, set_now: Callable[..., None], kind: str, day: str
) -> None:
    response = post(client, kind, day)

    assert response.status_code == 422
    assert error_code(response) == "period_in_future"


def test_current_incomplete_period_is_allowed(
    client: TestClient, set_now: Callable[..., None]
) -> None:
    set_now(datetime(2026, 11, 9, 0, 5, tzinfo=UTC))  # Mon 01:05 Brussels, the week just started

    assert post(client, "weekly", "2026-11-09").status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "daily", "date": WEEK},
        {"kind": "weekly", "date": "not-a-date"},
        {"kind": "weekly"},
        {"date": WEEK},
        {},
    ],
)
def test_invalid_create_body_is_422(
    client: TestClient, set_now: Callable[..., None], payload: dict[str, Any]
) -> None:
    assert client.post("/api/digests", json=payload).status_code == 422


def test_regenerate_keeps_review_and_ai_summary_and_refreshes_the_numbers(
    client: TestClient,
    session: Session,
    fixture_week: dict[str, Trade],
    set_now: Callable[..., None],
) -> None:
    created = digest(client)
    patched = client.patch(
        f"/api/digests/{created['id']}",
        json={"what_worked": "plan", "what_to_fix": "risk", "focus_next": "patience"},
    )
    assert patched.status_code == 200
    session.execute(text("UPDATE digests SET ai_summary = 'AI text'"))
    session.commit()
    a = session.get(Account, fixture_week["t1"].account_id)
    assert a is not None
    closed(session, a, datetime(2026, 11, 13, 12, tzinfo=UTC), "50.00", "1.0")

    again = digest(client)

    assert again["metrics"]["combined"]["metrics"]["trades"]["value"] == 7
    assert (again["what_worked"], again["what_to_fix"], again["focus_next"]) == (
        "plan",
        "risk",
        "patience",
    )
    assert again["ai_summary"] == "AI text"
    assert again["generated_at"] >= created["generated_at"]


# --- the hand-calculated week (ROADMAP M6 acceptance) ----------------------------------------


def combined(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = body["metrics"]["combined"]["metrics"]
    return out


def test_fixture_week_matches_the_hand_calculation(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    m = combined(digest(client))

    assert [m[k]["value"] for k in ("trades", "wins", "losses", "breakeven", "violations")] == [
        6,
        3,
        2,
        1,
        2,  # t2 and t4 (a trade with two violations counts once)
    ]
    assert m["net_pnl"]["value"] == "400.00"  # 200-100+300-100+0+100
    assert m["win_rate"]["value"] == "50.0000"  # 3 of 6, breakeven is not a win
    assert m["total_r"]["value"] == "3.0000"  # 2-1+3-1+0, t6 has no R
    assert m["total_r"]["n"] == 5
    assert m["avg_win_r"]["value"] == "2.5000"  # (2+3)/2
    assert m["avg_loss_r"]["value"] == "-1.0000"
    assert m["expectancy_r"]["value"] == "0.6000"  # 3 / 5
    assert m["profit_factor"]["value"] == "3.0000"  # 600 / 200
    assert m["max_drawdown"]["value"] == "100.00"
    assert m["net_pnl_pct"]["value"] == "1.3333"  # 400 / (10 000 + 20 000)
    assert m["max_drawdown_pct"]["value"] == "0.3333"


def test_best_and_worst_trade_in_the_combined_block(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    block = digest(client)["metrics"]["combined"]

    assert block["best_trade"]["trade_id"] == fixture_week["t3"].id
    assert block["best_trade"]["net_pnl"] == "300.00"
    assert block["best_trade"]["symbol"] == "GER40"
    assert block["worst_trade"]["trade_id"] == fixture_week["t2"].id  # tie with t4: earlier close
    assert block["worst_trade"]["net_pnl"] == "-100.00"


def test_by_account_blocks_have_their_own_numbers_in_account_order(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    blocks = digest(client)["metrics"]["by_account"]

    assert [(b["account_name"], b["norm_available"]) for b in blocks] == [
        ("Alpha", False),
        ("Beta", False),
    ]
    alpha, beta = (b["metrics"] for b in blocks)
    assert (alpha["trades"]["value"], alpha["net_pnl"]["value"]) == (4, "200.00")
    assert alpha["net_pnl_pct"]["value"] == "2.0000"  # 200 / 10 000
    assert alpha["win_rate"]["value"] == "50.0000"
    assert alpha["total_r"]["value"] == "1.0000"
    assert alpha["max_drawdown"]["value"] == "100.00"
    assert alpha["max_drawdown_pct"]["value"] == "1.0000"
    assert (beta["trades"]["value"], beta["net_pnl"]["value"]) == (2, "200.00")
    assert beta["net_pnl_pct"]["value"] == "1.0000"  # 200 / 20 000
    assert beta["total_r"]["value"] == "2.0000"
    assert beta["profit_factor"]["value"] == "3.0000"


def test_only_non_archived_accounts_closed_trades_by_brussels_close_date(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    body = digest(client)

    assert body["metrics"]["trade_ids"] == sorted(t.id for t in fixture_week.values())
    assert [b["account_name"] for b in body["metrics"]["by_account"]] == ["Alpha", "Beta"]
    assert body["metrics"]["currency"] == "USD"


def test_metric_blocks_without_history_have_null_norm_and_no_deviation(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    block = digest(client)["metrics"]["combined"]

    assert block["norm_available"] is False
    assert block["metrics"]["win_rate"] == {
        "value": "50.0000",
        "norm_mean": None,
        "norm_sd": None,
        "deviation": None,
    }
    assert all(v["deviation"] is None for v in block["metrics"].values())


def test_empty_period_has_zero_counts_and_null_ratios(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    accounts(session)
    body = digest(client)

    m = combined(body)
    assert (m["trades"]["value"], m["net_pnl"]["value"], m["total_r"]["value"]) == (
        0,
        "0.00",
        "0.0000",
    )
    assert m["win_rate"]["value"] is None and m["profit_factor"]["value"] is None  # noqa: PT018
    assert body["metrics"]["trade_ids"] == []
    assert body["metrics"]["by_account"] == []


# --- breakdowns, rules, bias, charts ---------------------------------------------------------

REAL_BREAKDOWN_ORDER = [
    "symbol",
    "session",
    "hour",
    "weekday",
    "bias_alignment",
    "setup_context",
    "poi_type",
    "fvg_kind",
    "entry_model",
    "exit_reason",
    "followed_plan",
    "emotion_before",
    "emotion_after",
    "quality_rating",
]


def test_breakdown_fields_are_trade_fields_then_analytics_journal_fields(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    breakdowns = digest(client)["metrics"]["breakdowns"]

    assert list(breakdowns) == REAL_BREAKDOWN_ORDER
    assert "rule_violations" not in breakdowns and "chart_links" not in breakdowns  # noqa: PT018


def test_symbol_breakdown_uses_canonical_symbols_with_formatted_numbers(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    b = digest(client)["metrics"]["breakdowns"]["symbol"]

    assert b["coverage"] == {"filled": 6, "total": 6}
    assert [g["key"] for g in b["groups"]] == ["EURUSD", "GER40", "XAUUSD"]
    ger = b["groups"][1]
    assert ger == {
        "key": "GER40",
        "trades": 2,
        "net_pnl": "200.00",
        "total_r": "2.0000",
        "win_rate": "50.0000",
    }


def test_journal_column_breakdown_has_a_null_group_and_coverage(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    b = digest(client)["metrics"]["breakdowns"]["entry_model"]

    assert b["coverage"] == {"filled": 3, "total": 6}  # shown as "заповнено 3/6"
    assert [(g["key"], g["trades"]) for g in b["groups"]] == [("fvg", 1), ("ob", 2), (None, 3)]
    ob = b["groups"][1]
    assert (ob["net_pnl"], ob["total_r"], ob["win_rate"]) == ("100.00", "1.0000", "50.0000")


def test_bias_alignment_breakdown_uses_the_effective_value(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    b = digest(client)["metrics"]["breakdowns"]["bias_alignment"]

    by_key = {g["key"]: g for g in b["groups"]}
    assert by_key["aligned"]["trades"] == 2  # t1 and t3 (override beats the auto "counter")
    assert by_key["counter"]["trades"] == 1


def test_time_breakdowns_group_by_session_hour_and_weekday(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    breakdowns = digest(client)["metrics"]["breakdowns"]

    assert {g["key"]: g["trades"] for g in breakdowns["session"]["groups"]} == {
        "london": 3,
        "ny": 1,
        None: 2,
    }
    assert {g["key"]: g["trades"] for g in breakdowns["weekday"]["groups"]}[0] == 2
    assert breakdowns["hour"]["coverage"] == {"filled": 4, "total": 6}


@pytest.fixture
def extra_field_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    path = config / "journal_fields.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + '\n  - key: my_extra\n    label: "Extra"\n    type: enum\n    options:\n'
        + '      - { value: a, label: "A" }\n      - { value: b, label: "B" }\n'
        + "    required: false\n    analytics: true\n    storage: extra\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield
    reload_config()


def test_an_extra_storage_analytics_field_appears_without_code_changes(
    client: TestClient,
    session: Session,
    extra_field_config: None,
    set_now: Callable[..., None],
) -> None:
    a, _ = accounts(session)
    closed(
        session, a, datetime(2026, 11, 9, 9, tzinfo=UTC), "10.00", "1.0", extra={"my_extra": "a"}
    )
    closed(
        session, a, datetime(2026, 11, 10, 9, tzinfo=UTC), "-5.00", "-1.0", extra={"my_extra": "b"}
    )
    closed(session, a, datetime(2026, 11, 11, 9, tzinfo=UTC), "7.00", "1.0")

    breakdowns = digest(client)["metrics"]["breakdowns"]

    assert list(breakdowns)[-1] == "my_extra"  # last in file order
    assert breakdowns["my_extra"]["coverage"] == {"filled": 2, "total": 3}
    assert [(g["key"], g["trades"]) for g in breakdowns["my_extra"]["groups"]] == [
        ("a", 1),
        ("b", 1),
        (None, 1),
    ]


def test_rules_section_counts_violations_trades_and_signed_pnl(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    rules = digest(client)["metrics"]["rules"]

    assert rules["rules"] == [
        {"rule_key": "max_risk_pct", "violations": 2, "trades": 2, "pnl": "-200.00"},
        {"rule_key": "min_planned_rr", "violations": 1, "trades": 1, "pnl": "-100.00"},
    ]
    assert (rules["violated_trades"], rules["violated_pnl"]) == (2, "-200.00")


def test_bias_sections_daily_weekly_monthly(
    client: TestClient,
    session: Session,
    fixture_week: dict[str, Trade],
    set_now: Callable[..., None],
) -> None:
    add_note(session, "pre_london", "2026-11-09", [True, False])
    add_note(session, "pre_ny", "2026-11-09", [True])
    add_note(session, "pre_london", "2026-11-10", [None])
    add_note(session, "pre_london", "2026-11-02", [False])  # previous week: ignored
    add_note(session, "weekly", WEEK, [True])
    add_note(session, "monthly", MONTH, [False, False])

    bias = digest(client)["metrics"]["bias"]

    assert list(bias) == ["daily", "weekly", "monthly"]
    assert bias["daily"]["accuracy"] == {"value": "66.6667", "marked": 3, "total": 4}
    assert bias["daily"]["aligned"] == {"trades": 2, "net_pnl": "500.00", "total_r": "5.0000"}
    assert bias["daily"]["counter"] == {"trades": 1, "net_pnl": "-100.00", "total_r": "-1.0000"}
    assert bias["weekly"]["accuracy"] == {"value": "100.0000", "marked": 1, "total": 1}
    assert bias["weekly"]["aligned"] == {"trades": 2, "net_pnl": "100.00", "total_r": "1.0000"}
    assert bias["weekly"]["counter"] == {"trades": 1, "net_pnl": "300.00", "total_r": "3.0000"}
    assert bias["monthly"]["accuracy"] == {"value": "0.0000", "marked": 2, "total": 2}
    assert bias["monthly"]["aligned"] == {"trades": 0, "net_pnl": "0.00", "total_r": "0.0000"}
    assert bias["monthly"]["counter"] == {"trades": 2, "net_pnl": "100.00", "total_r": "1.0000"}


def test_bias_accuracy_is_null_without_entries(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    accuracy = digest(client)["metrics"]["bias"]["daily"]["accuracy"]

    assert accuracy == {"value": None, "marked": 0, "total": 0}


def test_charts_equity_r_distribution_and_heatmap(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    charts = digest(client)["metrics"]["charts"]

    points = charts["equity"]["combined"]
    assert [p["cum_pnl"] for p in points] == [
        "0.00",
        "200.00",
        "100.00",
        "400.00",
        "300.00",
        "300.00",
        "400.00",
    ]
    assert points[0]["time"].startswith("2026-11-08T23:00:00")  # Monday 00:00 Brussels in UTC
    assert [(e["account_id"], len(e["points"])) for e in charts["equity"]["by_account"]] == [
        (fixture_week["t1"].account_id, 5),
        (fixture_week["t3"].account_id, 3),
    ]
    buckets = {b["lower"]: b["count"] for b in charts["r_distribution"]}
    assert sum(buckets.values()) == 5  # t6 has no R
    assert buckets["-1.0000"] == 2 and buckets["3.0000"] == 1  # noqa: PT018
    cells = {(c["weekday"], c["hour"]): c for c in charts["hour_heatmap"]}
    assert cells[(0, 9)] == {"weekday": 0, "hour": 9, "trades": 1, "net_pnl": "200.00"}


def test_mixed_currencies_in_the_period_are_409(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    eur = euro_account(session)
    closed(session, a, datetime(2026, 11, 9, 9, tzinfo=UTC), "10.00", "1.0")
    closed(session, eur, datetime(2026, 11, 9, 10, tzinfo=UTC), "10.00", "1.0")

    response = post(client)

    assert response.status_code == 409
    assert error_code(response) == "mixed_currency"


def test_a_foreign_currency_account_without_trades_in_the_period_does_not_block(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    euro_account(session)
    closed(session, a, datetime(2026, 11, 9, 9, tzinfo=UTC), "10.00", "1.0")

    assert post(client).status_code == 201


# --- norm and deviation end to end -----------------------------------------------------------


def seed_history(session: Session, account: Account, weeks: int = 5) -> None:
    """Five prior weeks from Mon 2026-10-05 (25 weekdays): win rates 100, 50, 100, 50, 100 %.

    Weekly win rate mean 80, population SD sqrt(600) = 24.4949; total R per week 2, 0, 2, 0, 2:
    mean 1.2, SD sqrt(0.96) = 0.9798.
    """
    starts = [date(2026, 10, 5) + timedelta(weeks=i) for i in range(weeks)]
    for i, start in enumerate(starts):
        second_wins = i % 2 == 0
        closed(
            session,
            account,
            datetime(start.year, start.month, start.day, 10, tzinfo=UTC),
            "100.00",
            "1.0",
        )
        pnl, r = ("100.00", "1.0") if second_wins else ("-100.00", "-1.0")
        day = start + timedelta(days=1)
        closed(session, account, datetime(day.year, day.month, day.day, 10, tzinfo=UTC), pnl, r)


def test_week_with_a_much_worse_win_rate_is_red_with_the_norm_numbers(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    seed_history(session, a)
    closed(session, a, datetime(2026, 11, 10, 10, tzinfo=UTC), "-100.00", "-1.0")
    closed(session, a, datetime(2026, 11, 11, 10, tzinfo=UTC), "-100.00", "-1.0")

    block = digest(client)["metrics"]["combined"]

    assert block["norm_available"] is True
    win_rate = block["metrics"]["win_rate"]
    assert win_rate["value"] == "0.0000"
    assert (win_rate["norm_mean"], win_rate["norm_sd"]) == ("80.0000", "24.4949")
    assert win_rate["deviation"] == "worse"
    assert block["metrics"]["total_r"]["deviation"] == "worse"  # -2 < 1.2 - 0.98


def test_week_with_a_much_better_total_r_is_green(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    seed_history(session, a)
    closed(session, a, datetime(2026, 11, 10, 10, tzinfo=UTC), "500.00", "5.0")
    closed(session, a, datetime(2026, 11, 11, 10, tzinfo=UTC), "500.00", "5.0")

    metrics = combined(digest(client))

    assert metrics["total_r"]["value"] == "10.0000"
    assert (metrics["total_r"]["norm_mean"], metrics["total_r"]["norm_sd"]) == ("1.2000", "0.9798")
    assert metrics["total_r"]["deviation"] == "better"
    assert metrics["win_rate"]["deviation"] is None  # 100 is not beyond 80 + 24.49


def test_history_of_nineteen_trading_days_gives_no_norm_at_all(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    seed_history(session, a, weeks=4)  # Mon Oct 5 .. Fri Oct 30 would be exactly 20 weekdays
    session.execute(text("DELETE FROM trades WHERE close_time < '2026-10-06'"))
    session.commit()
    closed(session, a, datetime(2026, 11, 3, 10, tzinfo=UTC), "-100.00", "-1.0")

    block = digest(client, day="2026-11-02")["metrics"]["combined"]

    assert block["norm_available"] is False  # first trade Tue Oct 6: 19 weekdays before Nov 2
    assert all(v["deviation"] is None for v in block["metrics"].values())


def test_exactly_twenty_trading_days_of_history_gives_a_norm(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    seed_history(session, a, weeks=4)  # first trade Mon Oct 5: exactly 20 weekdays before Nov 2
    closed(session, a, datetime(2026, 11, 3, 10, tzinfo=UTC), "-100.00", "-1.0")

    block = digest(client, day="2026-11-02")["metrics"]["combined"]

    assert block["norm_available"] is True


def test_norm_is_per_account_each_with_its_own_history(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, b = accounts(session)
    seed_history(session, a)
    closed(session, a, datetime(2026, 11, 10, 10, tzinfo=UTC), "-100.00", "-1.0")
    closed(session, b, datetime(2026, 11, 10, 11, tzinfo=UTC), "-100.00", "-1.0")  # B: no history

    blocks = digest(client)["metrics"]["by_account"]

    assert [(x["account_name"], x["norm_available"]) for x in blocks] == [
        ("Alpha", True),
        ("Beta", False),
    ]
    assert blocks[0]["metrics"]["win_rate"]["deviation"] == "worse"
    assert blocks[1]["metrics"]["win_rate"]["deviation"] is None


def test_deviation_sigma_comes_from_rules_yaml(
    client: TestClient,
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    set_now: Callable[..., None],
) -> None:
    a, _ = accounts(session)
    seed_history(session, a)
    closed(session, a, datetime(2026, 11, 10, 10, tzinfo=UTC), "-100.00", "-1.0")  # win rate 0
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    rules = config / "rules.yaml"
    rules.write_text(
        rules.read_text(encoding="utf-8") + "\ndigest:\n  deviation_sigma: 4\n", encoding="utf-8"
    )
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    try:
        win_rate = combined(digest(client))["win_rate"]
    finally:
        reload_config()

    assert win_rate["deviation"] is None  # 0 is inside 80 - 4 x 24.49
    assert win_rate["norm_mean"] == "80.0000"


# --- list, get, by-period, patch -------------------------------------------------------------


def test_list_is_newest_first_filtered_by_kind_with_summary_numbers(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    digest(client, "weekly", "2026-11-02")
    digest(client, "weekly", WEEK)
    digest(client, "monthly", MONTH)

    weekly = client.get("/api/digests", params={"kind": "weekly"}).json()["items"]
    everything = client.get("/api/digests").json()["items"]

    assert [i["period_start"] for i in weekly] == [WEEK, "2026-11-02"]
    assert len(everything) == 3
    item = weekly[0]
    assert set(item) == {
        "id", "kind", "period_start", "period_end", "generated_at", "trades", "net_pnl",
        "net_pnl_pct", "total_r", "win_rate", "reviewed",
    }  # fmt: skip
    assert (item["trades"], item["net_pnl"], item["net_pnl_pct"]) == (6, "400.00", "1.3333")
    assert (item["total_r"], item["win_rate"], item["reviewed"]) == ("3.0000", "50.0000", False)


def test_list_with_an_unknown_kind_is_422_and_empty_list_is_ok(client: TestClient) -> None:
    assert client.get("/api/digests", params={"kind": "daily"}).status_code == 422
    assert client.get("/api/digests").json() == {"items": []}


def test_get_by_id_returns_the_full_digest_and_404_for_unknown(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)

    got = client.get(f"/api/digests/{created['id']}")

    assert got.status_code == 200
    assert got.json() == created
    assert client.get("/api/digests/99999").status_code == 404


def test_get_by_period_normalises_the_date_and_404s_when_missing(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)

    found = client.get("/api/digests/by-period", params={"kind": "weekly", "date": "2026-11-12"})
    missing = client.get("/api/digests/by-period", params={"kind": "weekly", "date": "2026-11-02"})
    wrong_kind = client.get("/api/digests/by-period", params={"kind": "monthly", "date": WEEK})

    assert found.status_code == 200 and found.json()["id"] == created["id"]  # noqa: PT018
    assert missing.status_code == 404
    assert wrong_kind.status_code == 404


def test_patch_saves_review_fields_and_marks_the_digest_reviewed(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)

    response = client.patch(f"/api/digests/{created['id']}", json={"what_worked": "entries"})

    assert response.status_code == 200
    body = response.json()
    assert (body["what_worked"], body["what_to_fix"], body["focus_next"]) == ("entries", None, None)
    assert body["reviewed"] is True
    listed = client.get("/api/digests").json()["items"][0]
    assert listed["reviewed"] is True


def test_patch_empty_string_clears_the_field_to_null_and_omitted_fields_stay(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)
    client.patch(f"/api/digests/{created['id']}", json={"what_worked": "a", "focus_next": "b"})

    body = client.patch(f"/api/digests/{created['id']}", json={"what_worked": ""}).json()

    assert (body["what_worked"], body["focus_next"]) == (None, "b")
    assert body["reviewed"] is True


def test_clearing_every_review_field_makes_the_digest_unreviewed_again(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)
    client.patch(f"/api/digests/{created['id']}", json={"what_to_fix": "x"})

    body = client.patch(f"/api/digests/{created['id']}", json={"what_to_fix": ""}).json()

    assert body["reviewed"] is False


def test_patch_text_limit_is_ten_thousand_characters(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)
    url = f"/api/digests/{created['id']}"

    assert client.patch(url, json={"focus_next": "я" * 10_000}).status_code == 200
    assert client.patch(url, json={"focus_next": "я" * 10_001}).status_code == 422
    assert client.get(url).json()["focus_next"] == "я" * 10_000  # the rejected one saved nothing


def test_patch_unknown_digest_and_invalid_types(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)

    assert client.patch("/api/digests/99999", json={"what_worked": "x"}).status_code == 404
    assert client.patch(f"/api/digests/{created['id']}", json={"what_worked": 5}).status_code == 422


def test_patch_cannot_change_snapshot_or_ai_summary(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)

    client.patch(f"/api/digests/{created['id']}", json={"ai_summary": "forged", "metrics": {}})
    after = client.get(f"/api/digests/{created['id']}").json()

    assert after["ai_summary"] is None
    assert after["metrics"] == created["metrics"]


def test_review_text_keeps_unicode_and_special_characters(
    client: TestClient, fixture_week: dict[str, Trade], set_now: Callable[..., None]
) -> None:
    created = digest(client)
    text_value = "Що спрацювало: 'вхід' \"OB\" \U0001f680 <b>; DROP TABLE digests;--"

    body = client.patch(f"/api/digests/{created['id']}", json={"what_worked": text_value}).json()

    assert body["what_worked"] == text_value


# --- next bias note id -----------------------------------------------------------------------


def test_next_bias_note_id_points_at_the_next_period_note_or_is_null(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    accounts(session)
    assert digest(client)["next_bias_note_id"] is None
    assert digest(client, "monthly", MONTH)["next_bias_note_id"] is None
    add_note(session, "weekly", "2026-11-02", [True])  # not the next week
    add_note(session, "monthly", "2026-11-01", [True])  # not the next month
    next_week = add_note(session, "weekly", "2026-11-16", [None])
    next_month = add_note(session, "monthly", "2026-12-01", [None])

    weekly = digest(client)
    monthly = digest(client, "monthly", MONTH)

    assert weekly["next_bias_note_id"] == next_week.id
    assert monthly["next_bias_note_id"] == next_month.id
    assert client.get(f"/api/digests/{weekly['id']}").json()["next_bias_note_id"] == next_week.id


# --- suggestion ------------------------------------------------------------------------------


def suggestion(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/digests/suggestion")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def trade_on(session: Session, day: str, hour: int = 10) -> None:
    a = session.query(Account).first() or add_account(
        session, "Alpha", 1, reference_balance=ROOT_SIZE
    )
    when = datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)
    closed(session, a, when, "10.00", "1.0")


def weekly_of(client: TestClient) -> str | None:
    value = suggestion(client)["weekly"]
    return None if value is None else str(value["period_start"])


def test_no_trades_means_no_suggestion(client: TestClient, set_now: Callable[..., None]) -> None:
    set_now(datetime(2026, 11, 6, 15, 0, tzinfo=UTC))

    assert suggestion(client) == {"weekly": None, "monthly": None}


def test_weekly_appears_on_friday_at_16_brussels_not_a_minute_earlier(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-11-02")

    set_now(datetime(2026, 11, 6, 14, 59, tzinfo=UTC))  # Fri 15:59 Brussels (UTC+1)
    assert weekly_of(client) is None
    set_now(datetime(2026, 11, 6, 15, 0, tzinfo=UTC))  # Fri 16:00
    assert weekly_of(client) == "2026-11-02"


def test_weekly_uses_brussels_summer_time_offset(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-06-01")

    set_now(datetime(2026, 6, 5, 13, 59, tzinfo=UTC))  # Fri 15:59 CEST (UTC+2)
    assert weekly_of(client) is None
    set_now(datetime(2026, 6, 5, 14, 0, tzinfo=UTC))
    assert weekly_of(client) == "2026-06-01"


def test_weekly_not_before_friday_even_on_the_first_trade_week(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-11-02")

    set_now(datetime(2026, 11, 5, 20, 0, tzinfo=UTC))  # Thursday evening

    assert weekly_of(client) is None


def test_weekly_persists_over_the_weekend_and_next_week_until_a_review_is_saved(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-11-02")
    for moment in (
        datetime(2026, 11, 7, 12, 0, tzinfo=UTC),  # Saturday
        datetime(2026, 11, 8, 20, 0, tzinfo=UTC),  # Sunday
        datetime(2026, 11, 10, 9, 0, tzinfo=UTC),  # Tuesday of the next week
    ):
        set_now(moment)
        assert weekly_of(client) == "2026-11-02", moment


def test_a_generated_but_unreviewed_digest_keeps_the_suggestion(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-11-02")
    set_now(datetime(2026, 11, 7, 12, 0, tzinfo=UTC))
    digest(client, "weekly", "2026-11-02")

    assert weekly_of(client) == "2026-11-02"


@pytest.mark.parametrize("field", ["what_worked", "what_to_fix", "focus_next"])
def test_saving_any_review_field_removes_the_suggestion(
    client: TestClient, session: Session, set_now: Callable[..., None], field: str
) -> None:
    trade_on(session, "2026-11-02")
    set_now(datetime(2026, 11, 7, 12, 0, tzinfo=UTC))
    created = digest(client, "weekly", "2026-11-02")

    client.patch(f"/api/digests/{created['id']}", json={field: "done"})

    assert weekly_of(client) is None


def test_oldest_unreviewed_week_is_suggested_first_then_the_next(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-10-05")
    trade_on(session, "2026-10-13")
    trade_on(session, "2026-10-20")
    set_now(datetime(2026, 10, 23, 15, 0, tzinfo=UTC))  # Fri 16:00 Brussels (CEST ended Oct 25)
    assert weekly_of(client) == "2026-10-05"

    first = digest(client, "weekly", "2026-10-05")
    client.patch(f"/api/digests/{first['id']}", json={"focus_next": "ok"})
    assert weekly_of(client) == "2026-10-12"

    second = digest(client, "weekly", "2026-10-12")
    client.patch(f"/api/digests/{second['id']}", json={"focus_next": "ok"})
    assert weekly_of(client) == "2026-10-19"


def test_nothing_is_suggested_for_periods_before_the_first_closed_trade(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-11-09")

    set_now(datetime(2026, 11, 6, 15, 0, tzinfo=UTC))  # Fri of the week before the first trade

    assert suggestion(client) == {"weekly": None, "monthly": None}


def test_open_and_archived_trades_do_not_start_the_history(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a = add_account(session, "Alpha", 1, reference_balance=ROOT_SIZE)
    old = add_account(session, "Old", 2, status="archived")
    add_trade(session, a, status="open", close_time=None, net_pnl=None, gross_pnl=None,
              open_time=datetime(2026, 11, 2, 9, tzinfo=UTC))  # fmt: skip
    closed(session, old, datetime(2026, 11, 2, 10, tzinfo=UTC), "10.00", "1.0")
    set_now(datetime(2026, 11, 6, 15, 0, tzinfo=UTC))

    assert weekly_of(client) is None


def test_monthly_from_16_brussels_on_the_last_weekday_of_the_month(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-11-03")  # Nov 30 is a Monday: the last weekday of November

    set_now(datetime(2026, 11, 30, 14, 59, tzinfo=UTC))
    assert suggestion(client)["monthly"] is None
    set_now(datetime(2026, 11, 30, 15, 0, tzinfo=UTC))
    assert suggestion(client)["monthly"] == {"period_start": "2026-11-01"}


def test_monthly_last_weekday_skips_the_weekend_at_month_end(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-10-05")  # Oct 31 is a Saturday: the last weekday is Fri Oct 30

    set_now(datetime(2026, 10, 29, 15, 0, tzinfo=UTC))  # Thursday 16:00
    assert suggestion(client)["monthly"] is None
    set_now(datetime(2026, 10, 30, 15, 0, tzinfo=UTC))  # Friday 16:00 (CET again)
    assert suggestion(client)["monthly"] == {"period_start": "2026-10-01"}
    assert weekly_of(client) == "2026-10-05"  # oldest unreviewed week, not the current one


def test_monthly_persists_into_the_next_month_until_reviewed(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    trade_on(session, "2026-10-05")
    set_now(datetime(2026, 11, 3, 12, 0, tzinfo=UTC))
    assert suggestion(client)["monthly"] == {"period_start": "2026-10-01"}

    created = digest(client, "monthly", "2026-10-01")
    client.patch(f"/api/digests/{created['id']}", json={"what_to_fix": "done"})

    assert suggestion(client)["monthly"] is None


def test_suggestion_is_not_shadowed_by_the_id_route(client: TestClient) -> None:
    response = client.get("/api/digests/suggestion")

    assert response.status_code == 200
    assert set(response.json()) == {"weekly", "monthly"}
