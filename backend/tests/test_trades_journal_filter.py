"""M8-04..08 merge B: `GET /api/trades?journal=<key>:<value>` (docs/api.md "Merge B exact
shapes"). Same key = any of; different keys = all; `null` = empty; multi = array contains."""

# ruff: noqa: F811  (pytest fixtures imported from test_trades_api)
from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.models import Trade
from tests.test_trades_api import (  # noqa: F401
    _clean,
    add_account,
    add_trade,
    add_violation,
    session,
)


def ids(client: TestClient, *journal: str, **params: Any) -> list[int]:
    query: list[tuple[str, Any]] = [("journal", j) for j in journal] + list(params.items())
    response = client.get("/api/trades", params=query)
    assert response.status_code == 200, response.text
    return sorted(item["id"] for item in response.json()["items"])


def journal_error(client: TestClient, *journal: str) -> str:
    response = client.get("/api/trades", params=[("journal", j) for j in journal])
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    message: str = error["details"]["fields"]["journal"]
    return message


def three_trades(session: Session) -> tuple[Trade, Trade, Trade]:
    account = add_account(session, "Alpha", 1)
    flow = add_trade(
        session,
        account,
        h1_context="flow",
        h4_context="flow",
        poi_types=["fvg_h1", "fractal_h4"],
        fvg_types_h1=["post_manipulation"],
        followed_plan=True,
    )
    reversal = add_trade(
        session,
        account,
        h1_context="reversal",
        h4_context="flow",
        poi_types=["fractal_h1"],
        followed_plan=False,
    )
    empty = add_trade(session, account)
    return flow, reversal, empty


def test_enum_filter_same_key_is_any_of(client: TestClient, session: Session) -> None:
    # Arrange
    flow, reversal, _ = three_trades(session)

    # Act
    one = ids(client, "h1_context:flow")
    both = ids(client, "h1_context:flow", "h1_context:reversal")

    # Assert
    assert one == [flow.id]
    assert both == sorted([flow.id, reversal.id])


def test_different_keys_must_all_match(client: TestClient, session: Session) -> None:
    # Arrange
    flow, reversal, _ = three_trades(session)

    # Act
    result = ids(client, "h4_context:flow", "h1_context:reversal")

    # Assert
    assert result == [reversal.id]
    assert flow.id not in result


def test_null_matches_empty_values(client: TestClient, session: Session) -> None:
    # Arrange
    flow, reversal, empty = three_trades(session)

    # Act
    enum_null = ids(client, "h1_context:null")
    multi_null = ids(client, "poi_types:null")
    show_if_null_or_value = ids(client, "fvg_types_h1:null", "fvg_types_h1:post_manipulation")

    # Assert
    assert enum_null == [empty.id]
    assert multi_null == [empty.id]
    assert show_if_null_or_value == sorted([flow.id, reversal.id, empty.id])


def test_multi_filter_matches_when_the_array_contains_the_value(
    client: TestClient, session: Session
) -> None:
    # Arrange
    flow, reversal, _ = three_trades(session)

    # Act
    fractal_h4 = ids(client, "poi_types:fractal_h4")
    any_fractal = ids(client, "poi_types:fractal_h4", "poi_types:fractal_h1")
    nothing = ids(client, "poi_types:other")

    # Assert
    assert fractal_h4 == [flow.id]
    assert any_fractal == sorted([flow.id, reversal.id])
    assert nothing == []


def test_bool_filter_true_false_and_null(client: TestClient, session: Session) -> None:
    # Arrange
    flow, reversal, empty = three_trades(session)

    # Act / Assert
    assert ids(client, "followed_plan:true") == [flow.id]
    assert ids(client, "followed_plan:false") == [reversal.id]
    assert ids(client, "followed_plan:null") == [empty.id]


def test_rule_violations_filter_uses_the_violation_rows(
    client: TestClient, session: Session
) -> None:
    # Arrange
    flow, reversal, empty = three_trades(session)
    add_violation(session, flow, "daily_risk")
    add_violation(session, reversal, "entry_weak_poi", source="user")

    # Act
    daily = ids(client, "rule_violations:daily_risk")
    either = ids(client, "rule_violations:daily_risk", "rule_violations:entry_weak_poi")
    none = ids(client, "rule_violations:null")
    deprecated = ids(client, "rule_violations:daily_stop_loss_pct")

    # Assert
    assert daily == [flow.id]
    assert either == sorted([flow.id, reversal.id])
    assert none == [empty.id]
    assert deprecated == []


def test_journal_filter_combines_with_other_filters_and_total(
    client: TestClient, session: Session
) -> None:
    # Arrange
    flow, reversal, _ = three_trades(session)

    # Act
    response = client.get(
        "/api/trades",
        params=[("journal", "h4_context:flow"), ("status", "needs_description"), ("limit", 1)],
    )

    # Assert
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["items"][0]["id"] in {flow.id, reversal.id}


def test_unknown_key_is_422(client: TestClient, session: Session) -> None:
    three_trades(session)

    message = journal_error(client, "no_such_field:flow")

    assert "no_such_field" in message


def test_legacy_key_is_422(client: TestClient, session: Session) -> None:
    three_trades(session)

    message = journal_error(client, "setup_context:yes")

    assert "setup_context" in message


def test_unknown_option_is_422(client: TestClient, session: Session) -> None:
    three_trades(session)

    message = journal_error(client, "h1_context:sideways")

    assert "sideways" in message


def test_non_filterable_types_and_bad_format_are_422(client: TestClient, session: Session) -> None:
    three_trades(session)

    assert "quality_rating" in journal_error(client, "quality_rating:4")
    assert "mistakes" in journal_error(client, "mistakes:null")
    assert "bias_alignment" in journal_error(client, "bias_alignment:aligned")
    assert journal_error(client, "h1_context")
    assert "maybe" in journal_error(client, "followed_plan:maybe")


EXTRA_FIELDS = """
  - key: my_phase
    label: "Фаза"
    type: enum
    options:
      - { value: trend, label: "тренд" }
      - { value: flat, label: "флет" }
    required: false
    analytics: true
    storage: extra

  - key: my_tags
    label: "Теги"
    type: multi_enum
    options:
      - { value: news, label: "новини" }
      - { value: gap, label: "гап" }
    required: false
    analytics: false
    storage: extra

  - key: my_flag
    label: "Прапорець"
    type: bool
    required: false
    analytics: false
    storage: extra
"""


@pytest.fixture
def extra_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    config = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", config)
    path = config / "journal_fields.yaml"
    path.write_text(path.read_text(encoding="utf-8") + EXTRA_FIELDS, encoding="utf-8")
    monkeypatch.setenv(CONFIG_DIR_ENV, str(config))
    reload_config()
    yield
    reload_config()


def test_extra_storage_fields_filter_through_the_jsonb_values(
    client: TestClient, session: Session, extra_fields: None
) -> None:
    # Arrange
    account = add_account(session, "Alpha", 1)
    trend = add_trade(
        session, account, extra={"my_phase": "trend", "my_tags": ["news", "gap"], "my_flag": True}
    )
    flat = add_trade(session, account, extra={"my_phase": "flat", "my_tags": [], "my_flag": False})
    bare = add_trade(session, account)

    # Act / Assert
    assert ids(client, "my_phase:trend") == [trend.id]
    assert ids(client, "my_phase:null") == [bare.id]
    assert ids(client, "my_tags:gap") == [trend.id]
    assert ids(client, "my_tags:null") == sorted([flat.id, bare.id])
    assert ids(client, "my_flag:true") == [trend.id]
    assert ids(client, "my_flag:false") == [flat.id]
    assert ids(client, "my_flag:null") == [bare.id]
