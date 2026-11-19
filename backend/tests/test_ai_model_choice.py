"""M8-13: choose the Claude model per call type (Settings default + one-off override).

Fake model client only: no live AI call.
"""

# ruff: noqa: F811  (pytest fixtures imported from other test modules)
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config_files.ai_models import load_ai_models
from app.config_files.loader import ConfigError
from app.models import Account
from app.services.ai.model_choice import CHOICE_FILE
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, reply
from tests.test_ai_api import (  # noqa: F401 (fixtures)
    OUTPUT,
    _clean,
    account,
    extract,
    session,
    usage_log,
    use_model,
)
from tests.test_trades_api import add_trade

SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"


@pytest.fixture(autouse=True)
def _no_choice() -> Iterator[None]:
    path = get_settings().data_dir / CHOICE_FILE
    path.unlink(missing_ok=True)
    yield
    path.unlink(missing_ok=True)


def models(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/ai/models")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def test_lists_the_models_and_starts_with_the_env_defaults(client: TestClient) -> None:
    data = models(client)
    settings = get_settings()

    assert [m["id"] for m in data["models"]] == [SONNET, OPUS]
    assert data["models"][0]["approx_usd"]["trade_extraction"] == "0.01"
    assert data["defaults"] == {
        "trade_extraction": settings.anthropic_model_extraction,
        "bias_extraction": settings.anthropic_model_extraction,
        "digest_summary": settings.anthropic_model_summary,
    }


def test_owner_default_is_saved_per_call_type(client: TestClient) -> None:
    response = client.put("/api/ai/models/defaults", json={"trade_extraction": OPUS})

    assert response.status_code == 200, response.text
    assert response.json()["defaults"]["trade_extraction"] == OPUS
    assert models(client)["defaults"]["trade_extraction"] == OPUS
    stored = json.loads((get_settings().data_dir / CHOICE_FILE).read_text(encoding="utf-8"))
    assert stored == {"trade_extraction": OPUS}


def test_an_unknown_default_is_422(client: TestClient) -> None:
    response = client.put("/api/ai/models/defaults", json={"digest_summary": "claude-x"})

    assert response.status_code == 422
    assert "model" in response.json()["error"]["details"]["fields"]


def test_extraction_uses_the_owner_default(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    client.put("/api/ai/models/defaults", json={"trade_extraction": OPUS})
    trade = add_trade(session, account)
    model = use_model(app, FakeClient([reply(OUTPUT, model=OPUS)]))

    assert extract(client, trade.id).status_code == 200
    assert model.requests[0].model == OPUS
    line = json.loads(usage_log.path.read_text(encoding="utf-8").splitlines()[-1])
    assert (line["requested_model"], line["model"]) == (OPUS, OPUS)  # what was used


def test_a_one_off_model_overrides_the_default(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    trade = add_trade(session, account)
    model = use_model(app, FakeClient([reply(OUTPUT, model=OPUS)]))

    response = extract(client, trade.id, {"text": "Вхід по IFVG M5", "model": OPUS})

    assert response.status_code == 200, response.text
    assert model.requests[0].model == OPUS
    assert (
        models(client)["defaults"]["trade_extraction"] == get_settings().anthropic_model_extraction
    )


def test_an_unknown_one_off_model_is_422_and_no_call_is_made(
    app: FastAPI, client: TestClient, session: Session, account: Account, usage_log: UsageLog
) -> None:
    trade = add_trade(session, account)
    model = use_model(app, FakeClient([]))

    response = extract(client, trade.id, {"text": "Вхід по IFVG M5", "model": "claude-x"})

    assert response.status_code == 422
    assert model.requests == []
    assert not usage_log.path.exists()


def test_bias_extraction_takes_its_own_model(
    app: FastAPI, client: TestClient, usage_log: UsageLog
) -> None:
    model = use_model(app, FakeClient([reply(text=json.dumps({"entries": []}))]))

    response = client.post(
        "/api/bias/notes/extract",
        json={"text": "EURUSD вниз", "kind": "pre_london", "model": OPUS},
    )

    assert response.status_code == 200, response.text
    assert model.requests[0].model == OPUS


def test_a_broken_models_file_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "ai_models.yaml"
    path.write_text(
        "models:\n  - id: a\n    label: A\n    approx_usd: {trade_extraction: '1'}\n"
        "  - id: a\n    label: B\n    approx_usd:\n      trade_extraction: '1'\n"
        "      bias_extraction: '1'\n      digest_summary: '1'\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        load_ai_models(path)
    text = str(caught.value)
    assert "bias_extraction" in text  # missing call type in the first entry
