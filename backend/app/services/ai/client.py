"""Thin, injectable wrapper over the official `anthropic` SDK (read: one messages call).

The extraction service depends on the `ModelClient` protocol only, so tests use a fake
and never reach the real API. `AnthropicModelClient` creates the SDK client lazily (the
app starts without a key) and turns every SDK exception into an `AiCallError` with a
stable `kind` (docs/api.md "AI extraction" errors). No secrets in messages or logs.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
import httpx2
from pydantic import SecretStr

logger = logging.getLogger(__name__)

AiErrorKind = Literal[
    "auth", "rate_limit", "overloaded", "timeout", "connection", "api", "refusal", "invalid_output"
]

OVERLOADED_STATUS = 529
SERVER_ERROR_MIN = 500
# SDK retries per attempt (after the first try). Kept small so primary + fallback fit 30 s.
SDK_MAX_RETRIES = 1


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
    effort: str
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
        """One messages call (with the SDK's own retries). Raises AiCallError."""
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


def describe_error(exc: Exception) -> str:
    """Short English description for logs: class, HTTP status, request id. No body/key."""
    parts = [type(exc).__name__]
    if isinstance(exc, anthropic.APIStatusError):
        parts.append(f"HTTP {exc.status_code}")
        if exc.request_id:
            parts.append(f"request_id={exc.request_id}")
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
        # No temperature/top_p/top_k and no `thinking` (5.5 models think adaptively;
        # `disabled` is rejected). No server-side `fallbacks`: we fall back ourselves.
        client = self._client().with_options(
            max_retries=request.max_retries, timeout=request.timeout_s
        )
        try:
            message = client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.user_text}],
                output_config={
                    "format": {"type": "json_schema", "schema": request.schema},
                    "effort": request.effort,  # type: ignore[typeddict-item]
                },
            )
        except anthropic.AnthropicError as exc:
            kind, fallback_ok = classify_error(exc)
            raise AiCallError(kind, describe_error(exc), fallback_ok=fallback_ok) from exc
        return ModelReply(
            model=message.model,
            stop_reason=message.stop_reason,
            text=_first_text(message),
            usage=_usage(message),
        )
