"""POST /api/bias/notes/extract (docs/api.md M4 "Bias extraction"). Fake model only."""

# ruff: noqa: RUF001 - Ukrainian/Russian sample texts

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.ai import get_usage_log
from app.config import REPO_ROOT, get_settings
from app.config_files import reload_config
from app.config_files.loader import CONFIG_DIR_ENV
from app.services.ai.client import AiCallError
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, overloaded, reply
from tests.services.test_ai_key_status import FakeLookup
from tests.test_ai_api import error, use_key_tracker, use_model

URL = "/api/bias/notes/extract"
TEXT = "Золото бичаче від 2650, впевненість 2. Дакс шорт? Не знаю. Фібер без угод."
ENTRIES = [
    {"symbol": "XAUUSD", "key": "direction", "value": "bullish", "evidence": "Золото бичаче"},
    {"symbol": "XAUUSD", "key": "key_levels", "value": "2650", "evidence": "від 2650"},
    {"symbol": "XAUUSD", "key": "confidence", "value": "2", "evidence": "впевненість 2"},
    {"symbol": "GER40", "key": "narrative", "value": "шорт?", "evidence": "Не знаю"},
    {"symbol": "EURUSD", "key": "direction", "value": "no_trade", "evidence": "Фібер без угод"},
    {"symbol": "GBPUSD", "key": "direction", "value": "bearish", "evidence": "Дакс шорт"},
]


def answer(entries: list[dict[str, str]] = ENTRIES, **kwargs: Any) -> Any:
    return reply(text=json.dumps({"entries": entries}, ensure_ascii=False), **kwargs)


def post(client: TestClient, body: Any = None) -> Any:
    return client.post(URL, json=body if body is not None else {"kind": "pre_ny", "text": TEXT})


@pytest.fixture
def usage_log(app: FastAPI, tmp_path: Path) -> UsageLog:
    log = UsageLog(tmp_path / "ai_usage.jsonl")
    app.dependency_overrides[get_usage_log] = lambda: log
    return log


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A writable copy of the real config dir, active via CONFIG_DIR."""
    target = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", target)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(target))
    reload_config()
    yield target
    reload_config()


def lines(log: UsageLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


def test_extract_bias_groups_guarded_values_per_symbol(
    app: FastAPI, client: TestClient, usage_log: UsageLog
) -> None:
    model = use_model(app, FakeClient([answer()]))

    response = post(client)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["entries"] == [
        {
            "symbol": "EURUSD",
            "fields": {"direction": "no_trade"},
            "evidence": {"direction": "Фібер без угод"},
        },
        {
            "symbol": "XAUUSD",
            "fields": {"direction": "bullish", "key_levels": "2650", "confidence": 2},
            "evidence": {
                "direction": "Золото бичаче",
                "key_levels": "від 2650",
                "confidence": "впевненість 2",
            },
        },
    ]
    assert data["dropped"] == [
        {"symbol": "GBPUSD", "key": "direction", "reason": "symbol_not_in_text"},
        {"symbol": "GER40", "key": "narrative", "reason": "question"},
    ]
    assert data["usage"]["model"] == "claude-sonnet-5-5"
    assert data["usage"]["fallback_used"] is False
    assert data["usage"]["cost_usd"] == "0.0058"
    request = model.requests[0]
    assert request.user_text == TEXT
    assert "This note is `pre_ny`" in request.system
    assert request.schema["properties"]["entries"]["items"]["properties"]["symbol"]["enum"] == [
        "EURUSD",
        "GBPUSD",
        "XAUUSD",
        "GER40",
    ]
    [line] = lines(usage_log)
    assert (line["purpose"], line["trade_id"], line["ok"]) == ("bias_extract", None, True)


def test_extract_bias_empty_answer(app: FastAPI, client: TestClient, usage_log: UsageLog) -> None:
    use_model(app, FakeClient([answer([])]))
    data = post(client, {"kind": "weekly", "text": "Нічого цікавого."}).json()
    assert (data["entries"], data["dropped"]) == ([], [])


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"text": TEXT}, "kind"),
        ({"kind": "daily", "text": TEXT}, "kind"),
        ({"kind": "pre_ny"}, "text"),
        ({"kind": "pre_ny", "text": "   "}, "text"),
        ({"kind": "pre_ny", "text": "x" * 20001}, "text"),
        ({"kind": "pre_ny", "text": TEXT, "symbol": "XAUUSD"}, "symbol"),
    ],
)
def test_extract_bias_validation(
    app: FastAPI, client: TestClient, body: dict[str, Any], field: str
) -> None:
    model = use_model(app, FakeClient([]))
    err = error(post(client, body), 422, "validation_error")
    assert field in err["details"]["fields"]
    assert model.requests == []


def test_extract_bias_without_key_is_ai_not_configured(
    client: TestClient, usage_log: UsageLog
) -> None:
    assert not get_settings().ai_configured  # conftest empties ANTHROPIC_API_KEY
    error(post(client), 503, "ai_not_configured")
    assert not usage_log.path.exists()


@pytest.mark.parametrize(
    ("name", "content"),
    [("bias.yaml", "symbols: []\n"), ("extraction.yaml", "number_words:\n  4: []\n")],
)
def test_extract_bias_broken_config_is_config_error_before_any_call(
    app: FastAPI,
    client: TestClient,
    usage_log: UsageLog,
    cfg_dir: Path,
    name: str,
    content: str,
) -> None:
    (cfg_dir / name).write_text(content, encoding="utf-8")
    model = use_model(app, FakeClient([answer()]))

    err = error(post(client), 500, "config_error")

    assert err["details"]["file"] == name
    assert model.requests == []
    assert not usage_log.path.exists()


def test_extract_bias_config_error_comes_before_ai_not_configured(
    client: TestClient, usage_log: UsageLog, cfg_dir: Path
) -> None:
    (cfg_dir / "bias.yaml").write_text("symbols: []\n", encoding="utf-8")
    error(post(client), 500, "config_error")


def test_extract_bias_uses_aliases_from_config(
    app: FastAPI, client: TestClient, usage_log: UsageLog, cfg_dir: Path
) -> None:
    path = cfg_dir / "bias.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("[золото,", "[жовтий,"), encoding="utf-8"
    )
    entries = [
        {"symbol": "XAUUSD", "key": "direction", "value": "bullish", "evidence": "жовтий вгору"}
    ]
    model = use_model(app, FakeClient([answer(entries)]))

    data = post(client, {"kind": "pre_london", "text": "жовтий вгору"}).json()

    assert data["entries"][0]["fields"] == {"direction": "bullish"}
    assert "жовтий" in model.requests[0].system


@pytest.mark.parametrize(
    ("script", "kind"),
    [
        ([AiCallError("rate_limit", "RateLimitError HTTP 429")], "rate_limit"),
        ([overloaded(), overloaded()], "overloaded"),
        ([reply(text="", stop_reason="refusal")], "refusal"),
        ([reply(text='{"fields": []}')], "invalid_output"),
    ],
)
def test_extract_bias_ai_errors(
    app: FastAPI, client: TestClient, usage_log: UsageLog, script: list[Any], kind: str
) -> None:
    use_model(app, FakeClient(script))
    err = error(post(client), 502, "ai_error")
    assert err["details"] == {"kind": kind}
    assert [line["purpose"] for line in lines(usage_log)] == ["bias_extract"] * len(script)


def test_extract_bias_fallback(app: FastAPI, client: TestClient, usage_log: UsageLog) -> None:
    use_model(app, FakeClient([overloaded(), answer(model="claude-opus-5-5")]))
    usage = post(client).json()["usage"]
    assert (usage["model"], usage["fallback_used"]) == ("claude-opus-5-5", True)
    assert len(lines(usage_log)) == 2


def test_extract_bias_auth_error_marks_key_invalid(
    app: FastAPI, client: TestClient, usage_log: UsageLog
) -> None:
    tracker = use_key_tracker(app, FakeLookup([None]))
    client.post("/api/ai/check")
    use_model(app, FakeClient([AiCallError("auth", "AuthenticationError HTTP 401")]))

    err = error(post(client), 502, "ai_error")

    assert err["details"] == {"kind": "auth"}
    assert tracker.status().state == "invalid_key"
