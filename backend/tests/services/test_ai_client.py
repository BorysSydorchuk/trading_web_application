"""AnthropicModelClient on the real SDK with a mock HTTP transport (never the network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from app.services.ai.client import (
    AiCallError,
    AnthropicModelClient,
    ModelRequest,
    classify_error,
    describe_error,
)

KEY = "sk-ant-test-not-a-real-key"
URL = "https://api.anthropic.com/v1/messages"


def request(**kw: Any) -> ModelRequest:
    data: dict[str, Any] = {
        "model": "claude-sonnet-5-5",
        "system": "SYSTEM",
        "user_text": "опис угоди",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "effort": "medium",
        "max_tokens": 4000,
        "timeout_s": 5.0,
        "max_retries": 0,
    }
    return ModelRequest(**(data | kw))


def message(text: str = '{"lesson": null}', **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [
            {"type": "thinking", "thinking": "…", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 1830,
            "output_tokens": 210,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 12,
        },
    }
    return body | kw


Handler = Callable[[httpx2.Request], httpx2.Response]


def client_with(handler: Handler) -> AnthropicModelClient:
    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return AnthropicModelClient(SecretStr(KEY), http_client=http)


def status_error(status: int) -> Handler:
    def handler(req: httpx2.Request) -> httpx2.Response:
        body = {"type": "error", "error": {"type": "x", "message": "boom"}}
        return httpx2.Response(status, json=body, headers={"request-id": "req_1"})

    return handler


def test_request_body_matches_the_contract() -> None:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, json=message())

    reply = client_with(handler).create(request())

    body = json.loads(seen[0].content)
    assert str(seen[0].url) == URL
    assert KEY in seen[0].headers["authorization"]
    assert seen[0].headers["x-stainless-read-timeout"] == "5.0"  # per-attempt timeout
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 4000
    assert body["system"] == "SYSTEM"
    assert body["messages"] == [{"role": "user", "content": "опис угоди"}]
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": request().schema},
        "effort": "medium",
    }
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "fallbacks"):
        assert forbidden not in body
    assert reply.text == '{"lesson": null}'  # first text block, thinking skipped
    assert reply.model == "claude-sonnet-5-5"
    assert reply.stop_reason == "end_turn"
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (1830, 210)
    assert reply.usage.cache_read_input_tokens == 12


def test_sdk_client_is_created_lazily() -> None:
    client = AnthropicModelClient(SecretStr(KEY))
    assert client._sdk is None


def test_reply_without_text_block() -> None:
    body = message(content=[], stop_reason="refusal")
    reply = client_with(lambda _: httpx2.Response(200, json=body)).create(request())
    assert reply.text is None
    assert reply.stop_reason == "refusal"


@pytest.mark.parametrize(
    ("status", "kind", "fallback_ok"),
    [
        (400, "api", False),
        (401, "auth", False),
        (403, "auth", False),
        (404, "api", False),
        (429, "rate_limit", False),
        (500, "api", True),
        (503, "api", True),
        (529, "overloaded", True),
    ],
)
def test_status_errors_are_classified(status: int, kind: str, fallback_ok: bool) -> None:
    with pytest.raises(AiCallError) as caught:
        client_with(status_error(status)).create(request())
    assert (caught.value.kind, caught.value.fallback_ok) == (kind, fallback_ok)
    assert f"HTTP {status}" in caught.value.message
    assert KEY not in caught.value.message


def test_sdk_retries_once_with_max_retries_1() -> None:
    calls: list[int] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return status_error(529)(req)

    with pytest.raises(AiCallError):
        client_with(handler).create(request(max_retries=1))
    assert len(calls) == 2


def test_timeout_and_connection_errors() -> None:
    def timeout(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=req)

    def refused(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=req)

    with pytest.raises(AiCallError) as caught:
        client_with(timeout).create(request())
    assert (caught.value.kind, caught.value.fallback_ok) == ("timeout", True)
    with pytest.raises(AiCallError) as caught:
        client_with(refused).create(request())
    assert (caught.value.kind, caught.value.fallback_ok) == ("connection", True)


def test_classify_unknown_sdk_error_as_api() -> None:
    assert classify_error(anthropic.AnthropicError("x")) == ("api", False)
    assert describe_error(ValueError("secret body")) == "ValueError"


def test_describe_error_adds_api_type_and_message_for_4xx() -> None:
    def handler(req: httpx2.Request) -> httpx2.Response:
        body = {"type": "error", "error": {"type": "invalid_request_error", "message": "x" * 500}}
        return httpx2.Response(400, json=body, headers={"request-id": "req_9"})

    with pytest.raises(AiCallError) as caught:
        client_with(handler).create(request())
    message = caught.value.message
    assert message.startswith("BadRequestError HTTP 400 request_id=req_9 (invalid_request_error: x")
    assert message.endswith("...)")
    detail = message[message.index("(") + 1 : -1]
    assert len(detail) == 200
    assert KEY not in message


def test_describe_error_has_no_body_detail_for_5xx() -> None:
    with pytest.raises(AiCallError) as caught:
        client_with(status_error(500)).create(request())
    assert caught.value.message == "InternalServerError HTTP 500 request_id=req_1"
