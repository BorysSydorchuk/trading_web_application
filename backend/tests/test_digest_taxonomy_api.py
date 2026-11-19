"""M8-04..08 merge B: digest snapshot breakdowns for the new journal fields (docs/api.md
"Merge B exact shapes"): `kind` on every entry, multi fields per value, show_if coverage, the
POI combination and the H1 x H4 matrix. Excluded trades (M8-01) stay out."""

# ruff: noqa: F811  (pytest fixtures imported from test_digests_api)
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Digest, Trade
from tests.test_digests_api import (  # noqa: F401
    _clean,
    accounts,
    closed,
    digest,
    session,
    set_now,
)


def day(d: int) -> datetime:
    return datetime(2026, 11, d, 9, tzinfo=UTC)


def seed(session: Session) -> dict[str, Trade]:
    a, _ = accounts(session)
    t: dict[str, Trade] = {}
    t["fvg"] = closed(
        session, a, day(9), "100.00", "1.0", h1_context="flow", h4_context="flow",
        poi_types=["fvg_h1", "fractal_h4"], fvg_types_h1=["post_manipulation"],
    )  # fmt: skip
    t["fractal"] = closed(
        session, a, day(10), "-50.00", "-1.0", h1_context="flow", h4_context="reversal",
        poi_types=["fractal_h4"],
    )  # fmt: skip
    t["same_pair"] = closed(
        session, a, day(11), "30.00", "0.5", h1_context="flow", h4_context="flow",
        poi_types=["fractal_h4", "fvg_h1"],
    )  # fmt: skip
    t["empty"] = closed(session, a, day(12), "10.00", None, h1_context="range")
    t["excluded"] = closed(
        session, a, day(12), "-999.00", "-9.0", h1_context="flow", h4_context="flow",
        poi_types=["fvg_h4"], excluded_from_stats=True, excluded_reason="тест",
        excluded_at=day(13),
    )  # fmt: skip
    return t


def groups(entry: dict[str, Any]) -> list[tuple[Any, int]]:
    return [(g["key"], g["trades"]) for g in entry["groups"]]


def test_every_breakdown_has_a_kind_and_the_new_entries_are_in_file_order(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    # Arrange
    seed(session)

    # Act
    breakdowns = digest(client)["metrics"]["breakdowns"]

    # Assert
    assert list(breakdowns)[5:11] == [
        "h1_context",
        "h4_context",
        "h1_context__x__h4_context",
        "poi_types",
        "poi_types__combo",
        "fvg_types_h1",
    ]
    assert "setup_context" not in breakdowns and "fvg_kind" not in breakdowns  # noqa: PT018
    kinds = {k: v["kind"] for k, v in breakdowns.items()}
    assert kinds["symbol"] == kinds["poi_types"] == "field"
    assert kinds["poi_types__combo"] == "combination"
    assert kinds["h1_context__x__h4_context"] == "matrix"


def test_multi_field_counts_each_value_and_excluded_trades_stay_out(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    seed(session)

    poi = digest(client)["metrics"]["breakdowns"]["poi_types"]

    assert groups(poi) == [("fractal_h4", 3), ("fvg_h1", 2), (None, 1)]
    assert poi["coverage"] == {"filled": 3, "total": 4}
    fvg_h1 = poi["groups"][1]
    assert (fvg_h1["net_pnl"], fvg_h1["total_r"], fvg_h1["win_rate"]) == (
        "130.00",
        "1.5000",
        "100.0000",
    )


def test_show_if_field_coverage_counts_only_trades_whose_parent_includes_it(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    seed(session)

    breakdowns = digest(client)["metrics"]["breakdowns"]

    assert groups(breakdowns["fvg_types_h1"]) == [("post_manipulation", 1), (None, 1)]
    assert breakdowns["fvg_types_h1"]["coverage"] == {"filled": 1, "total": 2}
    # the only fvg_h4 trade is excluded from the statistics
    assert breakdowns["fvg_types_h4"]["coverage"] == {"filled": 0, "total": 0}


def test_poi_combination_and_h1_h4_matrix(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    seed(session)

    breakdowns = digest(client)["metrics"]["breakdowns"]

    combo = breakdowns["poi_types__combo"]
    assert groups(combo) == [("fvg_h1 + fractal_h4", 2), ("fractal_h4", 1), (None, 1)]
    assert combo["coverage"] == {"filled": 3, "total": 4}
    matrix = breakdowns["h1_context__x__h4_context"]
    assert groups(matrix) == [
        (["flow", "flow"], 2),
        (["flow", "reversal"], 1),
        (["range", None], 1),
    ]
    assert matrix["coverage"] == {"filled": 3, "total": 4}
    assert matrix["groups"][0]["net_pnl"] == "130.00"


def test_an_old_snapshot_without_kind_still_loads(
    client: TestClient, session: Session, set_now: Callable[..., None]
) -> None:
    # Arrange: a digest stored before merge B (breakdown entries without `kind`)
    old_entry = {"groups": [{"key": "ob", "trades": 1}], "coverage": {"filled": 1, "total": 1}}
    stored = Digest(
        kind="weekly",
        period_start=date(2026, 11, 2),
        period_end=date(2026, 11, 8),
        metrics={"breakdowns": {"entry_model": old_entry}, "trade_ids": []},
    )
    session.add(stored)
    session.commit()

    # Act
    response = client.get(f"/api/digests/{stored.id}")

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["metrics"]["breakdowns"] == {"entry_model": old_entry}
