"""Extraction service: fallback, refusal, invalid output, usage log lines (fake model)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.config_files import JournalFieldsConfig, get_journal_fields, get_number_words
from app.services.ai.client import AiCallError, ModelReply, TokenUsage
from app.services.ai.extraction import (
    FALLBACK_TIMEOUT_MAX_S,
    MIN_FALLBACK_S,
    PRIMARY_TIMEOUT_S,
    TOTAL_BUDGET_S,
    ExtractionFailed,
    ExtractionOutcome,
    ExtractionSettings,
    extract_trade_fields,
)
from app.services.ai.prompt import FIELDS_PLACEHOLDER
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, overloaded, reply

TEXT = "Вхід по IFVG M5, закрив по тейку. Урок: терпіння."
GOOD = {
    "entry_model": {"value": "ifvg_m5", "evidence": "Вхід по IFVG M5"},
    "exit_reason": {"value": "tp", "evidence": "закрив по тейку"},
}
SETTINGS = ExtractionSettings("claude-sonnet-5-5", "claude-opus-5-5", "medium")
NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


@pytest.fixture
def log(tmp_path: Path) -> UsageLog:
    return UsageLog(tmp_path / "ai_usage.jsonl")


def lines(log: UsageLog) -> list[dict[str, Any]]:
    if not log.path.exists():
        return []
    return [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]


class Clock:
    def __init__(self, step: float = 0.0) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def run(
    client: FakeClient,
    config: JournalFieldsConfig,
    log: UsageLog,
    text: str = TEXT,
    clock: Clock | None = None,
) -> ExtractionOutcome:
    return extract_trade_fields(
        text,
        trade_id=10,
        config=config,
        number_words=get_number_words(),
        client=client,
        settings=SETTINGS,
        usage_log=log,
        clock=clock or Clock(),
        now=lambda: NOW,
    )


def test_success_result_and_request(config: JournalFieldsConfig, log: UsageLog) -> None:
    client = FakeClient([reply(GOOD)])
    outcome = run(client, config, log)

    assert outcome.fields == {"entry_model": "ifvg_m5", "exit_reason": "tp"}
    assert outcome.ai_filled_fields == ["entry_model", "exit_reason"]
    assert "chart_links" in outcome.missing_required
    assert outcome.dropped == []
    usage = outcome.usage
    assert (usage.model, usage.fallback_used) == ("claude-sonnet-5-5", False)
    assert (usage.input_tokens, usage.output_tokens) == (1830, 210)
    assert str(usage.cost_usd) == "0.0058"  # 1830 * 2.00 + 210 * 10.00 per million

    req = client.requests[0]
    assert (req.model, req.effort, req.max_tokens) == ("claude-sonnet-5-5", "medium", 4000)
    assert (req.timeout_s, req.max_retries) == (PRIMARY_TIMEOUT_S, 0)  # no SDK retries
    assert req.user_text == TEXT
    assert FIELDS_PLACEHOLDER not in req.system
    assert "`ifvg_m5`: IFVG M5" in req.system
    keys = req.schema["properties"]["fields"]["items"]["properties"]["key"]["enum"]
    assert {"entry_model", "lesson"} <= set(keys)


def test_success_usage_line_has_no_text_values_or_key(
    config: JournalFieldsConfig, log: UsageLog
) -> None:
    run(FakeClient([reply(GOOD)]), config, log)
    [line] = lines(log)
    assert line == {
        "ts": "2026-11-04T09:30:00.000Z",
        "purpose": "extract",
        "trade_id": 10,
        "requested_model": "claude-sonnet-5-5",
        "model": "claude-sonnet-5-5",
        "fallback_used": False,
        "input_tokens": 1830,
        "output_tokens": 210,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cost_usd": "0.0058",
        "ok": True,
        "error_kind": None,
        "duration_ms": 0,
    }
    raw = log.path.read_text(encoding="utf-8")
    for secret in ("IFVG", "тейку", "ifvg_m5", "sk-ant"):
        assert secret not in raw


@pytest.mark.parametrize(
    "error",
    [
        overloaded(),
        AiCallError("api", "InternalServerError HTTP 500", fallback_ok=True),
        AiCallError("timeout", "APITimeoutError", fallback_ok=True),
        AiCallError("connection", "APIConnectionError", fallback_ok=True),
    ],
)
def test_fallback_on_overload_5xx_timeout_connection(
    config: JournalFieldsConfig, log: UsageLog, error: AiCallError
) -> None:
    client = FakeClient([error, reply(GOOD, model="claude-opus-5-5")])
    outcome = run(client, config, log)

    assert [r.model for r in client.requests] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    fallback = client.requests[1]
    assert fallback.max_retries == 0  # one attempt only
    assert MIN_FALLBACK_S <= fallback.timeout_s <= FALLBACK_TIMEOUT_MAX_S
    assert PRIMARY_TIMEOUT_S < TOTAL_BUDGET_S
    assert (outcome.usage.model, outcome.usage.fallback_used) == ("claude-opus-5-5", True)
    assert str(outcome.usage.cost_usd) == "0.0115"  # opus: 1830 * 4 + 210 * 20 per million
    first, second = lines(log)
    assert (first["ok"], first["error_kind"], first["model"]) == (False, error.kind, None)
    assert (first["fallback_used"], first["cost_usd"], first["input_tokens"]) == (
        False,
        "0.0000",
        0,
    )
    assert (second["ok"], second["model"], second["fallback_used"]) == (
        True,
        "claude-opus-5-5",
        True,
    )
    assert second["requested_model"] == "claude-opus-5-5"


@pytest.mark.parametrize(
    "error",
    [
        AiCallError("api", "BadRequestError HTTP 400"),
        AiCallError("auth", "AuthenticationError HTTP 401"),
        AiCallError("rate_limit", "RateLimitError HTTP 429"),
    ],
)
def test_no_fallback_on_4xx(config: JournalFieldsConfig, log: UsageLog, error: AiCallError) -> None:
    client = FakeClient([error])
    with pytest.raises(ExtractionFailed) as caught:
        run(client, config, log)
    assert caught.value.kind == error.kind
    assert len(client.requests) == 1
    assert len(lines(log)) == 1


def test_refusal_is_not_retried_and_logged_as_prompt_bug(
    config: JournalFieldsConfig, log: UsageLog, caplog: pytest.LogCaptureFixture
) -> None:
    client = FakeClient([reply(text="", stop_reason="refusal")])
    with caplog.at_level(logging.ERROR), pytest.raises(ExtractionFailed) as caught:
        run(client, config, log)
    assert caught.value.kind == "refusal"
    assert len(client.requests) == 1
    [line] = lines(log)
    assert (line["ok"], line["error_kind"], line["model"]) == (
        False,
        "refusal",
        "claude-sonnet-5-5",
    )
    assert line["input_tokens"] == 1830
    assert line["cost_usd"] == "0.0058"
    assert any("prompt bug" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("fake_reply", "why"),
    [
        (reply(GOOD, stop_reason="max_tokens"), "max_tokens"),
        (reply(text="not json"), "bad JSON"),
        (reply(text="[1, 2]"), "not an object"),
        (ModelReply("m", "end_turn", None, TokenUsage()), "no text block"),
    ],
)
def test_invalid_output(
    config: JournalFieldsConfig, log: UsageLog, fake_reply: Any, why: str
) -> None:
    client = FakeClient([fake_reply])
    with pytest.raises(ExtractionFailed) as caught:
        run(client, config, log)
    assert caught.value.kind == "invalid_output", why
    assert len(client.requests) == 1
    assert lines(log)[0]["error_kind"] == "invalid_output"


def test_fallback_failure_reports_the_fallback_error(
    config: JournalFieldsConfig, log: UsageLog
) -> None:
    timeout = AiCallError("timeout", "APITimeoutError", fallback_ok=True)
    client = FakeClient([overloaded(), timeout])
    with pytest.raises(ExtractionFailed) as caught:
        run(client, config, log)
    assert caught.value.kind == "timeout"
    assert [x["error_kind"] for x in lines(log)] == ["overloaded", "timeout"]


def test_no_fallback_when_the_time_budget_is_spent(
    config: JournalFieldsConfig, log: UsageLog
) -> None:
    client = FakeClient([overloaded(), reply(GOOD)])
    clock = Clock(step=(TOTAL_BUDGET_S - MIN_FALLBACK_S) / 2 + 0.5)
    with pytest.raises(ExtractionFailed) as caught:
        run(client, config, log, clock=clock)
    assert caught.value.kind == "overloaded"
    assert len(client.requests) == 1


def test_unknown_model_cost_is_null(
    config: JournalFieldsConfig, log: UsageLog, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        outcome = run(FakeClient([reply(GOOD, model="claude-mystery-9")]), config, log)
    assert outcome.usage.cost_usd is None
    assert lines(log)[0]["cost_usd"] is None
    assert any("not in config/ai_pricing.yaml" in r.getMessage() for r in caplog.records)


def test_model_question_and_invented_field_are_dropped(
    config: JournalFieldsConfig, log: UsageLog
) -> None:
    """PRD 6.5: a model that asks a question or fills an unmentioned field gets nothing in."""
    output = GOOD | {
        "mistakes": {"value": "Чому ти не чекав?", "evidence": "Урок: терпіння"},
        "quality_rating": {"value": 3, "evidence": "якість сетапу 3"},
        "followed_plan": {"value": True, "evidence": "по плану"},
    }
    outcome = run(FakeClient([reply(output)]), config, log)
    assert outcome.fields == {"entry_model": "ifvg_m5", "exit_reason": "tp"}
    assert {(d.key, d.reason) for d in outcome.dropped} == {
        ("mistakes", "question"),
        ("quality_rating", "evidence_not_in_text"),
        ("followed_plan", "evidence_not_in_text"),
    }


def test_no_fallback_after_a_primary_timeout(config: JournalFieldsConfig, log: UsageLog) -> None:
    """A primary timeout spends the budget: the fallback would not fit in 30 s."""
    timeout = AiCallError("timeout", "no answer within 28.0 s", fallback_ok=True)
    client = FakeClient([timeout, reply(GOOD)])
    clock = Clock(step=PRIMARY_TIMEOUT_S / 3)  # start, attempt start, attempt end
    with pytest.raises(ExtractionFailed) as caught:
        run(client, config, log, clock=clock)
    assert caught.value.kind == "timeout"
    assert len(client.requests) == 1


def test_fast_failure_leaves_the_fallback_most_of_the_budget(
    config: JournalFieldsConfig, log: UsageLog
) -> None:
    client = FakeClient([overloaded(), reply(GOOD, model="claude-opus-5-5")])
    run(client, config, log, clock=Clock(step=0.5))
    assert client.requests[1].timeout_s == FALLBACK_TIMEOUT_MAX_S


def test_answer_with_wrong_shape_is_invalid_output(
    config: JournalFieldsConfig, log: UsageLog
) -> None:
    client = FakeClient([reply(text='{"entry_model": {"value": "ifvg_m5", "evidence": "x"}}')])
    with pytest.raises(ExtractionFailed) as caught:
        run(client, config, log)
    assert caught.value.kind == "invalid_output"
    assert lines(log)[0]["error_kind"] == "invalid_output"
