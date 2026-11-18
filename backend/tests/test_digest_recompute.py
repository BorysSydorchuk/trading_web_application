# ruff: noqa: F811  (pytest fixtures imported from test_trade_exclusion)
"""M8-01b: exclude / include recomputes the saved digests of the trade's week and month.

Numbers only: review texts and the AI summary text are kept; a saved AI summary is marked
stale (``ai_summary_stale_at``) when the numbers changed, until «Оновити підсумок».
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Account, Digest, Trade
from app.services.digests import store_ai_summary
from tests.test_trade_exclusion import (  # noqa: F401  (fixtures)
    NOW,
    _clean,
    _now,
    account,
    exclude,
    include,
    ok,
    session,
    week,
)
from tests.test_trades_api import add_trade

WEEK = "2026-11-09"
MONTH = "2026-11-01"
EARLIER = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)


def create(client: TestClient, kind: str, day: str) -> dict[str, Any]:
    response = client.post("/api/digests", json={"kind": kind, "date": day})
    assert response.status_code in (200, 201), response.text
    data: dict[str, Any] = response.json()
    return data


def stored(session: Session, digest_id: int) -> Digest:
    session.expire_all()
    digest = session.get(Digest, digest_id)
    assert digest is not None
    return digest


def with_review_and_summary(session: Session, digest_id: int) -> None:
    digest = stored(session, digest_id)
    digest.what_worked, digest.ai_summary = "терпіння", "Факт: 3 угоди."
    digest.generated_at = EARLIER
    session.commit()


def trades_of(digest: Digest) -> int:
    value: int = digest.metrics["combined"]["metrics"]["trades"]["value"]
    return value


def test_exclude_recomputes_the_week_and_month_digests(
    client: TestClient, session: Session, week: dict[str, Trade]
) -> None:
    weekly, monthly = create(client, "weekly", WEEK), create(client, "monthly", MONTH)
    for d in (weekly, monthly):
        assert d["metrics"]["combined"]["metrics"]["trades"]["value"] == 3

    ok(exclude(client, week["test"].id))

    for d in (weekly, monthly):
        digest = stored(session, d["id"])
        assert trades_of(digest) == 2
        assert week["test"].id not in digest.metrics["trade_ids"]
        assert digest.metrics["by_account"][0]["metrics"]["trades"]["value"] == 2
        assert digest.metrics["excluded"]["trades"] == 1
        assert digest.generated_at == NOW


def test_review_text_and_ai_summary_are_kept_and_the_summary_is_marked_stale(
    client: TestClient, session: Session, week: dict[str, Trade]
) -> None:
    weekly = create(client, "weekly", WEEK)
    with_review_and_summary(session, weekly["id"])

    ok(exclude(client, week["test"].id))

    digest = stored(session, weekly["id"])
    assert (digest.what_worked, digest.ai_summary) == ("терпіння", "Факт: 3 угоди.")
    assert digest.ai_summary_stale_at == NOW
    body = ok(client.get(f"/api/digests/{weekly['id']}"))
    assert body["ai_summary_stale_at"] == "2026-11-12T14:00:00Z"


def test_a_digest_without_ai_summary_is_not_marked_stale(
    client: TestClient, session: Session, week: dict[str, Trade]
) -> None:
    weekly = create(client, "weekly", WEEK)

    ok(exclude(client, week["test"].id))

    assert stored(session, weekly["id"]).ai_summary_stale_at is None


def test_include_restores_the_numbers(
    client: TestClient, session: Session, week: dict[str, Trade]
) -> None:
    weekly = create(client, "weekly", WEEK)
    baseline = stored(session, weekly["id"]).metrics

    ok(exclude(client, week["test"].id))
    ok(include(client, week["test"].id))

    assert stored(session, weekly["id"]).metrics == baseline


def test_new_ai_summary_clears_the_stale_mark(
    client: TestClient, session: Session, week: dict[str, Trade]
) -> None:
    weekly = create(client, "weekly", WEEK)
    with_review_and_summary(session, weekly["id"])
    ok(exclude(client, week["test"].id))

    out = store_ai_summary(session, weekly["id"], "Факт: 2 угоди.")

    assert out.ai_summary_stale_at is None
    assert stored(session, weekly["id"]).ai_summary_stale_at is None


def test_other_periods_and_missing_digests_are_untouched(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade]
) -> None:
    other = create(client, "weekly", "2026-11-02")
    with_review_and_summary(session, other["id"])
    before = stored(session, other["id"]).metrics

    ok(exclude(client, week["test"].id))

    digest = stored(session, other["id"])
    assert digest.metrics == before
    assert (digest.generated_at, digest.ai_summary_stale_at) == (EARLIER, None)
    assert session.query(Digest).count() == 1  # no digest is created for the trade's week


def test_excluding_an_open_trade_touches_no_digest(
    client: TestClient, session: Session, account: Account, week: dict[str, Trade]
) -> None:
    weekly = create(client, "weekly", WEEK)
    with_review_and_summary(session, weekly["id"])
    trade = add_trade(session, account, status="open", close_time=None, net_pnl=None)

    ok(exclude(client, trade.id))

    digest = stored(session, weekly["id"])
    assert (digest.generated_at, digest.ai_summary_stale_at) == (EARLIER, None)
