"""AI warm-up job (docs/api.md M3 "AI warm-up"): schema hash, state file, backoff (fake model)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.config_files import ConfigError, JournalFieldsConfig, get_journal_fields
from app.domain.extraction import NumberWords, build_extraction_schema
from app.services.ai import warmup
from app.services.ai.client import AiCallError, ModelClient, ModelReply, ModelRequest
from app.services.ai.prompt import PromptError
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


def test_broken_extraction_yaml_makes_no_call(
    ai_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> NumberWords:
        raise ConfigError(Path("extraction.yaml"), ["number_words: broken"])

    monkeypatch.setattr(warmup, "get_number_words", broken)
    client = FakeClient([])
    job, _ = make_job(ai_settings, client)

    job()  # never raises
    assert client.requests == []
    assert not warmup_state_path(ai_settings).exists()


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


def test_state_write_error_logs_error_and_backs_off(
    ai_settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def failing_write(_path: Path, _state: WarmupState) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(warmup, "write_state", failing_write)
    clock = Clock()
    client = FakeClient([reply(), reply()])
    job, _ = make_job(ai_settings, client, clock)

    job()
    assert len(client.requests) == 1  # the call itself succeeded
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("AI warm-up done, but cannot write" in r.getMessage() for r in errors)
    assert not warmup_state_path(ai_settings).exists()

    clock.t += RETRY_AFTER_FAILURE_S - 1
    job()
    assert len(client.requests) == 1  # no paid call every minute


def test_prompt_error_logs_warning_and_backs_off(
    ai_settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []

    def missing_prompt(text: str, **_kwargs: object) -> None:
        calls.append(text)
        raise PromptError("Cannot read prompt extract_trade.md")

    monkeypatch.setattr(warmup, "extract_trade_fields", missing_prompt)
    clock = Clock()
    job, _ = make_job(ai_settings, FakeClient([]), clock)

    job()
    clock.t += RETRY_AFTER_FAILURE_S - 1
    job()

    assert calls == [WARMUP_TEXT]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("AI warm-up failed (Cannot read prompt" in r.getMessage() for r in warnings)
    assert not warmup_state_path(ai_settings).exists()


def test_refusal_is_a_failure(ai_settings: Settings) -> None:
    client = FakeClient([AiCallError("refusal", "model refused")])
    job, _ = make_job(ai_settings, client)

    assert job.run_once() is False
    assert not warmup_state_path(ai_settings).exists()


# --- time-based warm-up (M4-02): stale at start, Mon-Fri 07:30 Brussels ---

MONDAY_0730 = datetime(2026, 11, 9, 6, 30, tzinfo=UTC)  # 07:30 Europe/Brussels (winter)


class Now:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def timed_job(
    settings: Settings, client: FakeClient, now: Now, clock: Clock | None = None
) -> WarmupJob:
    return WarmupJob(settings, client_factory=lambda _s: client, clock=clock or Clock(), now=now)


def store_at(settings: Settings, config: JournalFieldsConfig, at: datetime) -> None:
    digest = schema_hash(build_extraction_schema(config), MODEL)
    write_state(warmup_state_path(settings), WarmupState(schema_hash=digest, model=MODEL, at=at))


def log_line(settings: Settings, at: datetime, *, error_kind: str | None = None) -> None:
    path = usage_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "ts": at.isoformat().replace("+00:00", "Z"),
        "purpose": "extraction",
        "ok": error_kind is None,
        "error_kind": error_kind,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def test_start_with_recent_success_in_usage_log_makes_no_call(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    store_at(ai_settings, config, MONDAY_0730 - timedelta(days=3))
    log_line(ai_settings, MONDAY_0730 - timedelta(hours=2))  # a user extraction
    client = FakeClient([])
    job = timed_job(ai_settings, client, Now(MONDAY_0730))

    assert job.run_once() is False
    assert client.requests == []


def test_start_with_old_success_makes_one_call_and_updates_state(
    ai_settings: Settings, config: JournalFieldsConfig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    store_at(ai_settings, config, MONDAY_0730 - timedelta(hours=21))
    log_line(ai_settings, MONDAY_0730 - timedelta(hours=20, minutes=1))
    now = Now(MONDAY_0730)
    client = FakeClient([reply()])
    job = timed_job(ai_settings, client, now)

    job()
    job()

    assert len(client.requests) == 1
    assert "no successful AI call in the last 20 h" in caplog.text
    state = read_state(warmup_state_path(ai_settings))
    assert state is not None
    assert state.at == MONDAY_0730
    assert usage_lines(ai_settings)[-1]["purpose"] == "warmup"


def test_start_with_no_success_at_all_makes_one_call(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    store_at(ai_settings, config, MONDAY_0730 - timedelta(hours=30))
    log_line(ai_settings, MONDAY_0730 - timedelta(hours=1), error_kind="timeout")  # no success
    client = FakeClient([reply()])
    job = timed_job(ai_settings, client, Now(MONDAY_0730))

    assert job.run_once() is True
    assert len(client.requests) == 1


def test_hash_change_and_old_success_make_one_call(
    ai_settings: Settings, config: JournalFieldsConfig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    digest = "old-hash"
    old = MONDAY_0730 - timedelta(days=2)
    write_state(
        warmup_state_path(ai_settings), WarmupState(schema_hash=digest, model=MODEL, at=old)
    )
    client = FakeClient([reply()])
    job = timed_job(ai_settings, client, Now(MONDAY_0730))

    job()
    job()

    assert len(client.requests) == 1
    assert "extraction schema changed; no successful AI call in the last 20 h" in caplog.text


def test_start_check_runs_once_per_worker_start(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    store_at(ai_settings, config, MONDAY_0730 - timedelta(hours=1))
    now = Now(MONDAY_0730)
    client = FakeClient([])
    job = timed_job(ai_settings, client, now)

    job()
    now.at += timedelta(hours=22)  # a quiet day later, no 07:30 request
    job()

    assert client.requests == []


def test_weekday_0730_request_makes_one_call(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    store_at(ai_settings, config, MONDAY_0730 - timedelta(hours=1))
    now = Now(MONDAY_0730 - timedelta(minutes=5))
    client = FakeClient([reply()])
    job = timed_job(ai_settings, client, now)
    job()  # start: recent success, no call
    assert client.requests == []

    now.at = MONDAY_0730
    job.request_daily()
    now.at += timedelta(seconds=40)
    job()
    job()

    assert len(client.requests) == 1


def test_no_daily_request_no_call(ai_settings: Settings, config: JournalFieldsConfig) -> None:
    # Saturday 07:30 Brussels: the cron does not fire (test_worker), so no request is made.
    saturday = datetime(2026, 11, 14, 6, 30, tzinfo=UTC)
    store_at(ai_settings, config, saturday - timedelta(hours=1))
    client = FakeClient([])
    job = timed_job(ai_settings, client, Now(saturday))

    job()

    assert client.requests == []


def test_daily_request_older_than_grace_is_dropped(
    ai_settings: Settings, config: JournalFieldsConfig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    store_at(ai_settings, config, MONDAY_0730 - timedelta(hours=1))
    now = Now(MONDAY_0730)
    client = FakeClient([])
    job = timed_job(ai_settings, client, now)
    job.request_daily()

    now.at += timedelta(minutes=31)  # e.g. the PC slept right after 07:30
    job()

    assert client.requests == []
    assert "07:30 warm-up is skipped" in caplog.text


def test_daily_request_without_key_makes_no_call(settings: Settings, tmp_path: Path) -> None:
    no_key = settings.model_copy(update={"anthropic_api_key": SecretStr(""), "data_dir": tmp_path})
    client = FakeClient([])
    job = timed_job(no_key, client, Now(MONDAY_0730))
    job.request_daily()

    job()

    assert client.requests == []


def test_daily_failure_backs_off_and_is_dropped_after_grace(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    store_at(ai_settings, config, MONDAY_0730 - timedelta(hours=1))
    clock = Clock()
    now = Now(MONDAY_0730)
    client = FakeClient([AiCallError("auth", "invalid key")])
    job = timed_job(ai_settings, client, now, clock)
    job()  # start: recent success
    job.request_daily()

    job()  # fails (auth)
    clock.t += 60
    now.at += timedelta(minutes=1)
    job()  # in backoff
    clock.t += RETRY_AFTER_FAILURE_S
    now.at += timedelta(hours=1)
    job()  # backoff over, but the 07:30 request expired

    assert len(client.requests) == 1


def test_stale_start_failure_backs_off_then_retries(
    ai_settings: Settings, config: JournalFieldsConfig
) -> None:
    store_at(ai_settings, config, MONDAY_0730 - timedelta(days=3))
    clock = Clock()
    now = Now(MONDAY_0730)
    client = FakeClient([overloaded(), reply()])
    job = timed_job(ai_settings, client, now, clock)

    job()
    clock.t += RETRY_AFTER_FAILURE_S - 1
    job()
    assert len(client.requests) == 1

    clock.t += 1
    now.at += timedelta(hours=1)
    job()
    job()
    assert len(client.requests) == 2
