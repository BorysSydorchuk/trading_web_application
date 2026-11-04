"""Thin, injectable wrapper over the official `anthropic` SDK (read: one messages call).

The extraction service depends on the `ModelClient` protocol only, so tests use a fake
and never reach the real API. `AnthropicModelClient` creates the SDK client lazily (the
app starts without a key) and turns every SDK exception into an `AiCallError` with a
stable `kind` (docs/api.md "AI extraction" errors). No secrets in messages or logs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
import httpx2
from pydantic import SecretStr

from app.config import AnthropicEffort

logger = logging.getLogger(__name__)

AiErrorKind = Literal[
    "auth", "rate_limit", "overloaded", "timeout", "connection", "api", "refusal", "invalid_output"
]

OVERLOADED_STATUS = 529
SERVER_ERROR_MIN = 500
# Default SDK retries: none. Retryable errors go to our own one-attempt fallback, so the
# primary + fallback worst case stays within the 30 s target (requests set it explicitly).
SDK_MAX_RETRIES = 0
ERROR_DETAIL_MAX_CHARS = 200
# Connect timeout per attempt, and the extra HTTP time an abandoned call gets after the
# wall-clock deadline before httpx gives up.
CONNECT_TIMEOUT_S = 5.0
HTTP_GRACE_S = 5.0


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def is_zero(self) -> bool:
        return not (
            self.input_tokens
            or self.output_tokens
            or self.cache_creation_input_tokens
            or self.cache_read_input_tokens
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


@dataclass(frozen=True)
class ModelRequest:
    model: str
    system: str
    user_text: str
    schema: dict[str, Any]
    effort: AnthropicEffort
    max_tokens: int
    timeout_s: float
    max_retries: int


@dataclass(frozen=True)
class ModelReply:
    model: str  # the model that answered (from the response)
    stop_reason: str | None
    text: str | None  # first text block, None when there is none
    usage: TokenUsage


class AiCallError(Exception):
    """A failed AI call. `fallback_ok`: overload, 5xx, timeout or connection error."""

    def __init__(self, kind: AiErrorKind, message: str, *, fallback_ok: bool = False) -> None:
        super().__init__(message)
        self.kind: AiErrorKind = kind
        self.message = message
        self.fallback_ok = fallback_ok


class ModelClient(Protocol):
    def create(self, request: ModelRequest) -> ModelReply:
        """One messages call within `request.timeout_s` (wall clock). Raises AiCallError."""
        ...


def classify_error(exc: Exception) -> tuple[AiErrorKind, bool]:
    """(kind, fallback_ok) for an SDK exception; most specific class first."""
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return "auth", False
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limit", False
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == OVERLOADED_STATUS:
            return "overloaded", True
        return "api", exc.status_code >= SERVER_ERROR_MIN
    if isinstance(exc, anthropic.APITimeoutError):  # subclass of APIConnectionError
        return "timeout", True
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection", True
    return "api", False


def _api_error_detail(exc: anthropic.APIStatusError) -> str | None:
    """`<type>: <message>` from an Anthropic error body (no key in it), truncated."""
    body = exc.body
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    detail = f"{error.get('type', 'error')}: {error.get('message', '')}".strip()
    if len(detail) > ERROR_DETAIL_MAX_CHARS:
        detail = detail[: ERROR_DETAIL_MAX_CHARS - 3] + "..."
    return detail


def describe_error(exc: Exception) -> str:
    """Short English description for logs: class, HTTP status, request id, and for a 4xx
    the API error type and message (<= 200 chars). Never the key or the request body."""
    parts = [type(exc).__name__]
    if isinstance(exc, anthropic.APIStatusError):
        parts.append(f"HTTP {exc.status_code}")
        if exc.request_id:
            parts.append(f"request_id={exc.request_id}")
        detail = _api_error_detail(exc) if exc.status_code < SERVER_ERROR_MIN else None
        if detail:
            parts.append(f"({detail})")
    return " ".join(parts)


def _first_text(message: anthropic.types.Message) -> str | None:
    for block in message.content:
        if block.type == "text":
            return block.text
    return None


def _usage(message: anthropic.types.Message) -> TokenUsage:
    usage = message.usage
    return TokenUsage(
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=usage.cache_read_input_tokens or 0,
    )


class DeadlineExceeded(Exception):  # noqa: N818 - reads as "raise DeadlineExceeded"
    pass


def run_with_deadline[T](call: Callable[[], T], timeout_s: float) -> T:
    """Run `call` in a daemon thread and wait at most `timeout_s` (wall clock).

    Raises DeadlineExceeded when it is not done in time (the thread is abandoned and ends
    on its own HTTP timeout); exceptions of `call` are re-raised here.
    """
    done = threading.Event()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=run, name="ai-call", daemon=True).start()
    if not done.wait(timeout_s):
        raise DeadlineExceeded
    if "error" in box:
        raise box["error"]
    value: T = box["value"]
    return value


class AnthropicModelClient:
    """`ModelClient` on the real API. The SDK client is created on first use."""

    def __init__(self, api_key: SecretStr, *, http_client: httpx2.Client | None = None) -> None:
        self._api_key = api_key
        self._http_client = http_client  # tests pass a MockTransport client
        self._sdk: anthropic.Anthropic | None = None
        self._lock = threading.Lock()

    def _client(self) -> anthropic.Anthropic:
        with self._lock:
            if self._sdk is None:
                self._sdk = anthropic.Anthropic(
                    api_key=self._api_key.get_secret_value(),
                    max_retries=SDK_MAX_RETRIES,
                    http_client=self._http_client,
                )
            return self._sdk

    def create(self, request: ModelRequest) -> ModelReply:
        """One call, bounded by `request.timeout_s` of wall-clock time (httpx timeouts only
        bound each network read, so a slow answer could run far past them)."""
        try:
            message = run_with_deadline(lambda: self._send(request), request.timeout_s)
        except DeadlineExceeded:
            logger.warning(
                "AI call on %s abandoned after %.1f s (wall clock); it may still be billed",
                request.model,
                request.timeout_s,
            )
            raise AiCallError(
                "timeout", f"no answer within {request.timeout_s:.1f} s", fallback_ok=True
            ) from None
        except anthropic.AnthropicError as exc:
            kind, fallback_ok = classify_error(exc)
            raise AiCallError(kind, describe_error(exc), fallback_ok=fallback_ok) from exc
        return ModelReply(
            model=message.model,
            stop_reason=message.stop_reason,
            text=_first_text(message),
            usage=_usage(message),
        )

    def _send(self, request: ModelRequest) -> anthropic.types.Message:
        # No temperature/top_p/top_k and no `thinking` (5.5 models think adaptively;
        # `disabled` is rejected). No server-side `fallbacks`: we fall back ourselves.
        # The httpx timeout only lets an abandoned call end soon after the deadline.
        timeout = httpx2.Timeout(
            request.timeout_s + HTTP_GRACE_S, connect=min(CONNECT_TIMEOUT_S, request.timeout_s)
        )
        client = self._client().with_options(max_retries=request.max_retries, timeout=timeout)
        return client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            system=request.system,
            messages=[{"role": "user", "content": request.user_text}],
            output_config={
                "format": {"type": "json_schema", "schema": request.schema},
                "effort": request.effort,
            },
        )
