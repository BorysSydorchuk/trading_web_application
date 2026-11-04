"""AI warm-up job (docs/api.md M3 "AI warm-up"): schema hash, state file, backoff (fake model)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.config_files import ConfigError, JournalFieldsConfig, get_journal_fields
from app.domain.extraction import build_extraction_schema
from app.services.ai import warmup
from app.services.ai.client import AiCallError, ModelClient, ModelReply, ModelRequest
from app.services.ai.usage_log import summarise_month, usage_log_path
from app.services.ai.warmup import (
    RETRY_AFTER_FAILURE_S,
    WARMUP_TEXT,
    WarmupJob,
    WarmupState,
    read_state,
    schema_hash,
    warmup_state_path,
    write_state,
)
from tests.services.ai_fakes import FakeClient, overloaded, reply

NOW = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
MODEL = "claude-sonnet-5-5"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def ai_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "anthropic_api_key": SecretStr("test-key"),
            "anthropic_model_extraction": MODEL,
            "data_dir": tmp_path / "data",
            "log_dir": tmp_path / "logs",
        }
    )


@pytest.fixture
def config() -> JournalFieldsConfig:
    return get_journal_fields()


def make_job(
    settings: Settings, client: FakeClient, clock: Clock | None = None
) -> tuple[WarmupJob, list[int]]:
    """The job plus a list that counts client_factory calls."""
    created: list[int] = []

    def factory(_settings: Settings) -> ModelClient:
        created.append(1)
        return client

    job = WarmupJob(settings, client_factory=factory, clock=clock or Clock(), now=lambda: NOW)
    return job, created


def usage_lines(settings: Settings) -> list[dict[str, Any]]:
    path = usage_log_path(settings)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def store_current(settings: Settings, config: JournalFieldsConfig, model: str = MODEL) -> None:
    digest = schema_hash(build_extraction_schema(config), model)
    write_state(warmup_state_path(settings), WarmupState(schema_hash=digest, model=model, at=NOW))


# --- schema_hash ---


def test_schema_hash_is_stable_and_key_order_independent(config: JournalFieldsConfig) -> None:
    schema = build_extraction_schema(config)
    reordered = dict(reversed(list(schema.items())))

    assert schema_hash(schema, MODEL) == schema_hash(reordered, MODEL)
    assert len(schema_hash(schema, MODEL)) == 64


def test_schema_hash_changes_with_model_and_schema(config: JournalFieldsConfig) -> None:
    schema = build_extraction_schema(config)
    fewer = build_extraction_schema(config.model_copy(update={"fields": config.fields[1:]}))

    assert schema_hash(schema, MODEL) != schema_hash(schema, "claude-opus-5-5")
    assert schema_hash(schema, MODEL) != schema_hash(fewer, MODEL)


# --- state file ---


def test_state_round_trip_and_atomic_write(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "ai_warmup.json"
    write_state(path, WarmupState(schema_hash="abc", model=MODEL, at=NOW))

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_hash": "abc",
        "model": MODEL,
        "at": "2026-11-04T09:30:00.000Z",
    }
    assert read_state(path) == WarmupState(schema_hash="abc", model=MODEL, at=NOW)
    assert [p.name for p in path.parent.iterdir()] == ["ai_warmup.json"]  # no temp left


def test_missing_state_is_none(tmp_path: Path) -> None:
    assert read_state(tmp_path / "ai_warmup.json") is None


@pytest.mark.parametrize("content", ["", "{not json", "[]", '{"schema_hash": "x"}'])
def test_broken_state_is_none(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "ai_warmup.json"
    path.write_text(content, encoding="utf-8")

    assert read_state(path) is None
    assert "is broken" in caplog.text


# --- job ---


def test_no_api_key_makes_no_call(settings: Settings, tmp_path: Path) -> None:
    no_key = settings.model_copy(update={"anthropic_api_key": SecretStr(""), "data_dir": tmp_path})
    client = FakeClient([])
    job, created = make_job(no_key, client)

    assert job.run_once() is False
    assert client.requests == []
    assert created == []
    assert not warmup_state_path(no_key).exists()


def test_broken_journal_fields_makes_no_call(
    ai_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> JournalFieldsConfig:
        raise ConfigError(Path("journal_fields.yaml"), ["fields: broken"])

    monkeypatch.setattr(warmup, "get_journal_fields", broken)
    client = FakeClient([])
    job, _ = make_job(ai_settings, client)

    job()  # never raises
    assert client.requests == []


def test_same_hash_makes_no_call(ai_settings: Settings, config: JournalFieldsConfig) -> None:
    store_current(ai_settings, config)
    client = FakeClient([])
    job, created = make_job(ai_settings, client)

    assert job.run_once() is False
    assert client.requests == []
    assert created == []


def test_no_state_runs_one_call_writes_state_and_logs_usage(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    client = FakeClient([reply()])
    job, _ = make_job(ai_settings, client)

    assert job.run_once() is True
    job()  # second cycle: hash is stored now, no call

    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.model == MODEL
    assert request.user_text == WARMUP_TEXT
    assert request.schema == build_extraction_schema(config)  # the real extraction schema
    assert request.timeout_s == 28.0  # same deadline as a user extraction
    state = read_state(warmup_state_path(ai_settings))
    assert state == WarmupState(
        schema_hash=schema_hash(build_extraction_schema(config), MODEL), model=MODEL, at=NOW
    )
    [line] = usage_lines(ai_settings)
    assert line["purpose"] == "warmup"
    assert line["trade_id"] is None
    assert line["ok"] is True
    assert line["requested_model"] == MODEL
    month = summarise_month(usage_log_path(ai_settings), NOW)
    assert month.calls == 1  # counted in the monthly total like any call
    assert month.cost_usd > 0


def test_changed_schema_runs_exactly_one_call(
    ai_settings: Settings, config: JournalFieldsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_current(ai_settings, config)
    changed = config.model_copy(update={"fields": config.fields[1:]})
    monkeypatch.setattr(warmup, "get_journal_fields", lambda: changed)
    client = FakeClient([reply()])
    job, _ = make_job(ai_settings, client)

    job()
    job()

    assert len(client.requests) == 1
    state = read_state(warmup_state_path(ai_settings))
    assert state is not None
    assert state.schema_hash == schema_hash(build_extraction_schema(changed), MODEL)


def test_changed_model_runs_one_call(ai_settings: Settings, config: JournalFieldsConfig) -> None:
    store_current(ai_settings, config, model="claude-old-model")
    client = FakeClient([reply()])
    job, _ = make_job(ai_settings, client)

    job()
    job()

    assert len(client.requests) == 1
    state = read_state(warmup_state_path(ai_settings))
    assert state is not None
    assert state.model == MODEL


def test_broken_state_file_triggers_warmup(ai_settings: Settings) -> None:
    path = warmup_state_path(ai_settings)
    path.parent.mkdir(parents=True)
    path.write_text("{oops", encoding="utf-8")
    client = FakeClient([reply()])
    job, _ = make_job(ai_settings, client)

    assert job.run_once() is True
    assert read_state(path) is not None


def test_failure_writes_no_state_and_backs_off_one_hour(
    ai_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock()
    client = FakeClient([overloaded(), reply()])
    job, _ = make_job(ai_settings, client, clock)

    job()
    assert len(client.requests) == 1  # no fallback attempt for the warm-up
    assert not warmup_state_path(ai_settings).exists()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("AI warm-up failed (overloaded)" in r.getMessage() for r in warnings)
    [line] = usage_lines(ai_settings)
    assert (line["purpose"], line["ok"], line["error_kind"]) == ("warmup", False, "overloaded")

    clock.t += RETRY_AFTER_FAILURE_S - 1
    job()
    assert len(client.requests) == 1  # still in backoff

    clock.t += 1
    job()
    assert len(client.requests) == 2
    assert read_state(warmup_state_path(ai_settings)) is not None


def test_unexpected_error_never_raises_and_backs_off(
    ai_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    class Exploding:
        calls = 0

        def create(self, request: ModelRequest) -> ModelReply:
            self.calls += 1
            raise RuntimeError("bug")

    client = Exploding()
    job = WarmupJob(ai_settings, client_factory=lambda _s: client, now=lambda: NOW)

    job()
    job()

    assert client.calls == 1
    assert "AI warm-up: unexpected error" in caplog.text
    assert not warmup_state_path(ai_settings).exists()


def test_refusal_is_a_failure(ai_settings: Settings) -> None:
    client = FakeClient([AiCallError("refusal", "model refused")])
    job, _ = make_job(ai_settings, client)

    assert job.run_once() is False
    assert not warmup_state_path(ai_settings).exists()
