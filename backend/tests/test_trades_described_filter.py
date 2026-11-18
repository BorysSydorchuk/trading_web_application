"""M8-15: `GET /api/trades?described=` (Journal «Опис»: з описом / без опису).

"Described" = the owner saved a journal (`described_at` set), open trades included (M8-02).
"""

# ruff: noqa: F811  (pytest fixtures imported from test_trades_api)
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.test_trades_api import _clean, add_account, add_trade, session  # noqa: F401

SAVED = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)


def ids(client: TestClient, **params: Any) -> list[int]:
    response = client.get("/api/trades", params=params)
    assert response.status_code == 200, response.text
    return sorted(item["id"] for item in response.json()["items"])


def test_described_filter_splits_open_trades_with_and_without_a_description(
    client: TestClient, session: Session
) -> None:
    account = add_account(session, "Alpha", 1)
    open_described = add_trade(
        session, account, status="open", close_time=None, net_pnl=None, described_at=SAVED
    )
    open_bare = add_trade(session, account, status="open", close_time=None, net_pnl=None)
    closed = add_trade(session, account, status="needs_description")

    assert ids(client, status="open", described="true") == [open_described.id]
    assert ids(client, status="open", described="false") == [open_bare.id]
    assert ids(client, described="false") == sorted([open_bare.id, closed.id])
    assert ids(client) == sorted([open_described.id, open_bare.id, closed.id])
