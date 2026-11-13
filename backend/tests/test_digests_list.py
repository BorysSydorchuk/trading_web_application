# ruff: noqa: F811
"""M6-06a (RED): digest list virtual rows and ``digests.reviewed_at`` (docs/api.md, Digests API).

Virtual rows: past/started weeks and months with >= 1 closed trade (non-archived accounts,
Brussels close date) and no created digest. Created rows carry ``reviewed_at``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.test_digests_api import (  # noqa: F401  (fixtures are used by name)
    NOW,
    WEEK,
    _clean,
    accounts,
    add_account,
    closed,
    digest,
    session,
    set_now,
)
from tests.test_trades_api import add_trade

VIRTUAL_KEYS = {
    "id", "kind", "period_start", "period_end", "generated_at", "trades", "net_pnl",
    "net_pnl_pct", "total_r", "win_rate", "reviewed", "reviewed_at",
}  # fmt: skip


def items(client: TestClient, kind: str | None = None) -> list[dict[str, Any]]:
    params = {"kind": kind} if kind else {}
    response = client.get("/api/digests", params=params)
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["items"]
    return rows


def starts(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(r["kind"], r["period_start"]) for r in rows]


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


LATER = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)

# --- A. virtual rows -------------------------------------------------------------------------


def test_past_weeks_and_months_with_closed_trades_are_listed_as_virtual_rows(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 10, 28, 10, tzinfo=UTC), "100.50", "1.0")
    closed(session, a, datetime(2026, 10, 29, 10, tzinfo=UTC), "-20.25", "-0.5")

    weekly = items(client, "weekly")
    monthly = items(client, "monthly")

    assert starts(weekly) == [("weekly", "2026-10-26")]
    assert starts(monthly) == [("monthly", "2026-10-01")]
    row = weekly[0]
    assert set(row) == VIRTUAL_KEYS
    assert (row["id"], row["generated_at"]) == (None, None)
    assert (row["period_start"], row["period_end"]) == ("2026-10-26", "2026-11-01")
    assert (row["trades"], row["net_pnl"]) == (2, "80.25")
    assert (row["net_pnl_pct"], row["total_r"], row["win_rate"]) == (None, None, None)
    assert (row["reviewed"], row["reviewed_at"]) == (False, None)
    assert (monthly[0]["period_start"], monthly[0]["period_end"]) == ("2026-10-01", "2026-10-31")


def test_net_pnl_of_a_virtual_row_always_has_two_decimals(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 10, 28, 10, tzinfo=UTC), "0", None)

    assert items(client, "weekly")[0]["net_pnl"] == "0.00"


def test_periods_without_trades_are_not_listed(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 10, 7, 10, tzinfo=UTC), "10.00", None)
    closed(session, a, datetime(2026, 10, 28, 10, tzinfo=UTC), "10.00", None)

    assert starts(items(client, "weekly")) == [("weekly", "2026-10-26"), ("weekly", "2026-10-05")]


def test_no_trades_means_an_empty_list(client: TestClient, set_now: Callable[..., None]) -> None:
    assert items(client) == []


def test_archived_accounts_and_open_trades_are_ignored(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    old = add_account(session, "Old", 3, status="archived")
    closed(session, old, datetime(2026, 10, 28, 10, tzinfo=UTC), "50.00", None)
    a, _ = accounts(session)
    add_trade(
        session, a, status="open", close_time=None, net_pnl=None, gross_pnl=None,
        open_time=datetime(2026, 10, 14, 9, tzinfo=UTC),
    )  # fmt: skip

    assert items(client) == []


def test_sunday_2330_brussels_belongs_to_that_week_and_month_boundary_uses_brussels(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 11, 8, 22, 30, tzinfo=UTC), "10.00", None)  # Sun 23:30 CET
    closed(session, a, datetime(2026, 10, 31, 23, 30, tzinfo=UTC), "5.00", None)  # Sun 1 Nov 00:30

    weekly = items(client, "weekly")
    monthly = items(client, "monthly")

    # 8 Nov 23:30 Brussels is still the week of Mon 2 Nov; 1 Nov 00:30 Brussels (a Sunday) is
    # the week of Mon 26 Oct and already November.
    assert [(r["period_start"], r["trades"]) for r in weekly] == [
        ("2026-11-02", 1),
        ("2026-10-26", 1),
    ]
    assert [(r["period_start"], r["trades"]) for r in monthly] == [("2026-11-01", 2)]


def test_the_current_started_week_and_month_with_a_trade_are_listed(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 11, 12, 10, tzinfo=UTC), "10.00", None)

    assert starts(items(client, "weekly")) == [("weekly", WEEK)]
    assert starts(items(client, "monthly")) == [("monthly", "2026-11-01")]
    assert len(items(client)) == 2


def test_a_period_that_has_not_started_is_not_listed(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 11, 15, 23, 30, tzinfo=UTC), "10.00", None)  # Mon 16 Nov

    assert items(client, "weekly") == []


def test_created_and_virtual_rows_are_merged_newest_first_never_both_for_a_period(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 11, 10, 10, tzinfo=UTC), "10.00", None)  # week 9 Nov
    closed(session, a, datetime(2026, 11, 3, 10, tzinfo=UTC), "20.00", None)  # week 2 Nov
    closed(session, a, datetime(2026, 10, 14, 10, tzinfo=UTC), "30.00", None)  # week 12 Oct
    created = digest(client, "weekly", "2026-11-02")

    rows = items(client, "weekly")

    assert [(r["period_start"], r["id"]) for r in rows] == [
        (WEEK, None),
        ("2026-11-02", created["id"]),
        ("2026-10-12", None),
    ]
    assert (rows[1]["generated_at"] is None, rows[1]["net_pnl_pct"] is None) == (False, False)


def test_post_replaces_the_virtual_row_with_the_created_row(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    a, _ = accounts(session)
    closed(session, a, datetime(2026, 11, 10, 10, tzinfo=UTC), "10.00", "1.0")
    assert items(client, "weekly")[0]["id"] is None

    created = digest(client, "weekly", WEEK)

    rows = items(client, "weekly")
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["generated_at"] is not None


def test_a_created_digest_of_a_period_without_trades_stays_listed(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client, "weekly", "2026-11-02")

    assert [(r["id"], r["trades"]) for r in items(client, "weekly")] == [(created["id"], 0)]


# --- B. reviewed_at --------------------------------------------------------------------------


def test_a_new_digest_has_reviewed_at_null(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)

    assert created["reviewed_at"] is None
    assert client.get(f"/api/digests/{created['id']}").json()["reviewed_at"] is None
    assert items(client, "weekly")[0]["reviewed_at"] is None


def test_patch_with_text_sets_reviewed_at_to_the_pinned_now(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)

    body = client.patch(f"/api/digests/{created['id']}", json={"what_worked": "entries"}).json()

    assert parse(body["reviewed_at"]) == NOW
    assert body["reviewed_at"].endswith(("Z", "+00:00"))
    assert parse(client.get(f"/api/digests/{created['id']}").json()["reviewed_at"]) == NOW
    row = items(client, "weekly")[0]
    assert (row["reviewed"], parse(row["reviewed_at"])) == (True, NOW)


def test_a_later_patch_changing_text_updates_reviewed_at(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)
    url = f"/api/digests/{created['id']}"
    client.patch(url, json={"what_worked": "a"})
    set_now(LATER)

    body = client.patch(url, json={"what_worked": "b"}).json()

    assert parse(body["reviewed_at"]) == LATER


def test_patch_adding_a_second_field_updates_reviewed_at(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)
    url = f"/api/digests/{created['id']}"
    client.patch(url, json={"what_worked": "a"})
    set_now(LATER)

    body = client.patch(url, json={"focus_next": "b"}).json()

    assert parse(body["reviewed_at"]) == LATER


def test_patch_clearing_all_three_fields_sets_reviewed_at_null(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)
    url = f"/api/digests/{created['id']}"
    client.patch(url, json={"what_worked": "a", "focus_next": "b"})

    body = client.patch(url, json={"what_worked": "", "focus_next": ""}).json()

    assert (body["reviewed"], body["reviewed_at"]) == (False, None)
    assert client.get(url).json()["reviewed_at"] is None


def test_clearing_one_of_two_fields_keeps_the_review_and_refreshes_reviewed_at(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)
    url = f"/api/digests/{created['id']}"
    client.patch(url, json={"what_worked": "a", "focus_next": "b"})
    set_now(LATER)

    body = client.patch(url, json={"what_worked": ""}).json()

    assert (body["reviewed"], parse(body["reviewed_at"])) == (True, LATER)


def test_patch_that_changes_nothing_review_related_keeps_reviewed_at(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)
    url = f"/api/digests/{created['id']}"
    client.patch(url, json={"what_worked": "a"})
    set_now(LATER)

    same_text = client.patch(url, json={"what_worked": "a"}).json()
    empty_patch = client.patch(url, json={}).json()

    assert parse(same_text["reviewed_at"]) == NOW
    assert parse(empty_patch["reviewed_at"]) == NOW


def test_patch_on_an_unreviewed_digest_that_changes_nothing_keeps_null(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)

    body = client.patch(f"/api/digests/{created['id']}", json={"what_worked": ""}).json()

    assert body["reviewed_at"] is None


def test_regenerate_keeps_reviewed_at(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    created = digest(client)
    client.patch(f"/api/digests/{created['id']}", json={"what_to_fix": "x"})
    set_now(LATER)

    again = client.post("/api/digests", json={"kind": "weekly", "date": WEEK})

    assert again.status_code == 200
    assert parse(again.json()["reviewed_at"]) == NOW
    assert parse(items(client, "weekly")[0]["reviewed_at"]) == NOW
