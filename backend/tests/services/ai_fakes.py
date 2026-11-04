"""Fake `ModelClient` for tests: replays scripted replies/errors, records requests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.client import AiCallError, ModelReply, ModelRequest, TokenUsage

USAGE = TokenUsage(input_tokens=1830, output_tokens=210)


def reply(
    output: Any = None,
    *,
    model: str = "claude-sonnet-5-5",
    stop_reason: str = "end_turn",
    text: str | None = None,
    usage: TokenUsage = USAGE,
) -> ModelReply:
    body = text if text is not None else json.dumps(output if output is not None else {})
    return ModelReply(model=model, stop_reason=stop_reason, text=body, usage=usage)


def overloaded() -> AiCallError:
    return AiCallError("overloaded", "OverloadedError HTTP 529", fallback_ok=True)


@dataclass
class FakeClient:
    script: Sequence[ModelReply | AiCallError]
    requests: list[ModelRequest] = field(default_factory=list)

    def create(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        step = self.script[len(self.requests) - 1]
        if isinstance(step, AiCallError):
            raise step
        return step
