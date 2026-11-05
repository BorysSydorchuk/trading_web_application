"""AI key status tracker with a fake model lookup (never the network)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.services.ai.client import AiCallError
from app.services.ai.key_status import KeyStatus, KeyStatusTracker

KEY = "sk-ant-test-key-status-secret"
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def settings_with(key: str = KEY) -> Settings:
    return get_settings().model_copy(update={"anthropic_api_key": SecretStr(key)})


@dataclass
class FakeLookup:
    """Replays a script (None = success, AiCallError = failure); the last step repeats."""

    script: Sequence[AiCallError | None] = (None,)
    calls: list[tuple[str, float]] = field(default_factory=list)
    delay_s: float = 0.0

    def retrieve_model(self, model: str, timeout_s: float) -> None:
        self.calls.append((model, timeout_s))
        if self.delay_s:
            time.sleep(self.delay_s)
        step = self.script[min(len(self.calls), len(self.script)) - 1]
        if step is not None:
            raise step


def tracker(
    lookup: FakeLookup, key: str = KEY, **kw: float
) -> tuple[KeyStatusTracker, Callable[[], Settings]]:
    current = settings_with(key)

    def settings() -> Settings:
        return current

    return KeyStatusTracker(settings, lambda _: lookup, now=lambda: NOW, **kw), settings


def http_error(status: int) -> AiCallError:
    kind = {401: "auth", 403: "auth", 429: "rate_limit", 529: "overloaded"}.get(status, "api")
    return AiCallError(
        kind,  # type: ignore[arg-type]
        f"Error HTTP {status}",
        fallback_ok=status >= 500,
        status_code=status,
    )


def test_not_configured_without_key() -> None:
    lookup = FakeLookup()
    keys, _ = tracker(lookup, key="  ")
    assert keys.status() == KeyStatus("not_configured", None)
    assert keys.check() == KeyStatus("not_configured", None)
    assert lookup.calls == []


def test_checking_until_the_first_check_ends() -> None:
    keys, _ = tracker(FakeLookup())
    assert keys.status() == KeyStatus("checking", None)


def test_ok_uses_the_extraction_model_and_timeout() -> None:
    lookup = FakeLookup()
    keys, settings = tracker(lookup)
    assert keys.check() == KeyStatus("ok", NOW)
    assert lookup.calls == [(settings().anthropic_model_extraction, 10.0)]


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (http_error(401), "invalid_key"),
        (http_error(403), "invalid_key"),
        (AiCallError("timeout", "no answer within 10.0 s", fallback_ok=True), "unreachable"),
        (AiCallError("connection", "APIConnectionError", fallback_ok=True), "unreachable"),
        (http_error(500), "unreachable"),
        (http_error(503), "unreachable"),
        (http_error(529), "unreachable"),
        (AiCallError("api", "AnthropicError"), "unreachable"),  # no HTTP status
        (http_error(404), "ok"),  # key accepted, model id unknown
        (http_error(429), "ok"),  # key accepted, rate limited
    ],
)
def test_check_result_states(error: AiCallError, state: str) -> None:
    keys, _ = tracker(FakeLookup([error]))
    assert keys.check() == KeyStatus(state, NOW)  # type: ignore[arg-type]


def test_unexpected_exception_is_unreachable(caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        def retrieve_model(self, model: str, timeout_s: float) -> None:
            raise RuntimeError("bug")

    keys = KeyStatusTracker(settings_with, lambda _: Broken(), now=lambda: NOW)
    assert keys.check().state == "unreachable"
    assert "unexpected error" in caplog.text


def test_transitions_and_each_change_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.services.ai.key_status")
    timeout = AiCallError("timeout", "no answer", fallback_ok=True)
    lookup = FakeLookup([timeout, timeout, None, http_error(401), http_error(401)])
    keys, _ = tracker(lookup)
    states = [keys.check().state for _ in range(5)]
    assert states == ["unreachable", "unreachable", "ok", "invalid_key", "invalid_key"]
    records = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert len(records) == 3  # one line per change
    assert records[0][0] == logging.WARNING
    assert "not reachable" in records[0][1]
    assert records[1] == (logging.INFO, "AI key: accepted")
    assert records[2][0] == logging.WARNING
    assert "REJECTED" in records[2][1]
    assert "HTTP 401" in records[2][1]


def test_key_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    lookup = FakeLookup([http_error(401), None, http_error(404)])
    keys, _ = tracker(lookup)
    for _ in range(3):
        keys.check()
    keys.mark_invalid("AuthenticationError HTTP 401")
    assert caplog.records
    assert KEY not in caplog.text


def test_extraction_auth_error_marks_invalid_without_a_call() -> None:
    lookup = FakeLookup()
    keys, _ = tracker(lookup)
    keys.check()
    keys.mark_invalid("AuthenticationError HTTP 401")
    assert keys.status() == KeyStatus("invalid_key", NOW)
    assert len(lookup.calls) == 1


def test_mark_invalid_without_key_stays_not_configured() -> None:
    keys, _ = tracker(FakeLookup(), key="")
    keys.mark_invalid("x")
    assert keys.status().state == "not_configured"


def test_concurrent_checks_share_one_call() -> None:
    lookup = FakeLookup(delay_s=0.3)
    keys, _ = tracker(lookup)
    results: list[KeyStatus] = []
    threads = [threading.Thread(target=lambda: results.append(keys.check())) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert [r.state for r in results] == ["ok", "ok", "ok"]
    assert len(lookup.calls) == 1


def wait_for(predicate: Callable[[], bool], timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_background_rechecks_while_unreachable_then_stops_calling() -> None:
    timeout = AiCallError("timeout", "no answer", fallback_ok=True)
    lookup = FakeLookup([timeout, timeout, None])
    keys, _ = tracker(lookup, recheck_s=0.02)
    keys.start()
    try:
        assert wait_for(lambda: keys.status().state == "ok")
        time.sleep(0.15)  # several recheck periods: no more calls once ok
        assert len(lookup.calls) == 3
    finally:
        keys.stop()


def test_background_does_not_recheck_invalid_key() -> None:
    lookup = FakeLookup([http_error(401)])
    keys, _ = tracker(lookup, recheck_s=0.02)
    keys.start()
    try:
        assert wait_for(lambda: keys.status().state == "invalid_key")
        time.sleep(0.1)
        assert len(lookup.calls) == 1
    finally:
        keys.stop()


def test_background_without_key_makes_no_call() -> None:
    lookup = FakeLookup()
    keys, _ = tracker(lookup, key="", recheck_s=0.02)
    keys.start()
    time.sleep(0.05)
    keys.stop()
    assert lookup.calls == []
    assert keys.status().state == "not_configured"
