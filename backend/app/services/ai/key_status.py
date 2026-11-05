"""AI key status (docs/api.md "AI key status"): is ANTHROPIC_API_KEY accepted?

The API checks the key once in a background thread at start with `models.retrieve(<extraction
model>)` (no tokens billed), again every 5 min while the API is unreachable, on demand
(`POST /api/ai/check`), and marks it invalid when an extraction gets an auth error. The state
lives in memory (thread-safe); each change is logged once, the key never.

States: `not_configured` (no key), `checking` (first check not finished), `ok`, `invalid_key`
(401/403), `unreachable` (timeout, connection error, 5xx/529, unknown SDK error). Any other
API error (e.g. 404 for an unknown model id, 429) means the key was accepted: `ok`, with a
WARNING naming the error.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.config import Settings
from app.services.ai.client import AiCallError, ModelLookup

logger = logging.getLogger(__name__)

KeyState = Literal["not_configured", "checking", "ok", "invalid_key", "unreachable"]

CHECK_TIMEOUT_S = 10.0
RECHECK_UNREACHABLE_S = 300.0
_AUTH_STATUSES = frozenset({401, 403})


@dataclass(frozen=True)
class KeyStatus:
    state: KeyState
    checked_at: datetime | None  # UTC, end of the last finished check; None before one


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _state_for(error: AiCallError) -> KeyState:
    if error.kind == "auth" or error.status_code in _AUTH_STATUSES:
        return "invalid_key"
    if error.fallback_ok or error.status_code is None:
        return "unreachable"  # timeout, connection, 5xx/529, unknown SDK error
    return "ok"  # the API answered with a non-auth 4xx: the key itself was accepted


_LOG_LEVEL: dict[KeyState, int] = {
    "ok": logging.INFO,
    "invalid_key": logging.WARNING,
    "unreachable": logging.WARNING,
    "checking": logging.INFO,
    "not_configured": logging.INFO,
}
_LOG_TEXT: dict[KeyState, str] = {
    "ok": "AI key: accepted",
    "invalid_key": "AI key: REJECTED by the Anthropic API (invalid or revoked key)",
    "unreachable": "AI key: Anthropic API not reachable, re-checking every "
    f"{RECHECK_UNREACHABLE_S / 60:.0f} min",
    "checking": "AI key: checking",
    "not_configured": "AI key: ANTHROPIC_API_KEY is not set",
}


class KeyStatusTracker:
    """Thread-safe in-memory key state. `settings` is read on every call (like the endpoints),
    `lookup` builds the client for the current settings (tests pass a fake)."""

    def __init__(
        self,
        settings: Callable[[], Settings],
        lookup: Callable[[Settings], ModelLookup],
        *,
        now: Callable[[], datetime] = _utc_now,
        timeout_s: float = CHECK_TIMEOUT_S,
        recheck_s: float = RECHECK_UNREACHABLE_S,
    ) -> None:
        self._settings = settings
        self._lookup = lookup
        self._now = now
        self._timeout_s = timeout_s
        self._recheck_s = recheck_s
        self._lock = threading.Lock()  # guards _status, _logged, _running
        self._status = KeyStatus("checking", None)
        self._logged: KeyState | None = None
        self._running: threading.Event | None = None  # set when the running check ends
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- reading ---

    def status(self) -> KeyStatus:
        if not self._settings().ai_configured:
            self._log_change("not_configured", None)
            return KeyStatus("not_configured", None)
        with self._lock:
            return self._status

    # --- checking ---

    def check(self) -> KeyStatus:
        """Check now (blocking, at most ~timeout_s). A check already running is joined
        instead of starting a second call."""
        settings = self._settings()
        if not settings.ai_configured:
            return self.status()
        with self._lock:
            running = self._running
            if running is None:
                self._running = threading.Event()
        if running is not None:
            running.wait(self._timeout_s + 1.0)
            return self.status()
        try:
            state, detail = self._call(settings)
            self._set(state, detail)
        finally:
            with self._lock:
                done, self._running = self._running, None
            if done is not None:
                done.set()
        return self.status()

    def _call(self, settings: Settings) -> tuple[KeyState, str | None]:
        model = settings.anthropic_model_extraction
        try:
            self._lookup(settings).retrieve_model(model, self._timeout_s)
        except AiCallError as exc:
            return _state_for(exc), exc.message
        except Exception as exc:  # a bug here must not kill the checker thread
            logger.exception("AI key check: unexpected error")
            return "unreachable", type(exc).__name__
        return "ok", None

    def mark_invalid(self, detail: str) -> None:
        """An extraction got an auth error: the key is rejected (no extra call)."""
        if self._settings().ai_configured:
            self._set("invalid_key", detail)

    def _set(self, state: KeyState, detail: str | None) -> None:
        with self._lock:
            self._status = KeyStatus(state, self._now())
        self._log_change(state, detail)

    def _log_change(self, state: KeyState, detail: str | None) -> None:
        with self._lock:
            if state == self._logged:
                return
            self._logged = state
        if state == "ok" and detail:
            logger.warning("AI key: accepted, but the model check answered %s", detail)
            return
        message = _LOG_TEXT[state] + (f" ({detail})" if detail else "")
        logger.log(_LOG_LEVEL[state], message)

    # --- background ---

    def start(self) -> None:
        """Background thread: check now, then every recheck_s while the state is unreachable
        (also when a later on-demand check made it unreachable)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ai-key-check", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 1.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout_s)

    def _loop(self) -> None:
        self.check()
        while not self._stop.wait(self._recheck_s):
            if self.status().state == "unreachable":
                self.check()
