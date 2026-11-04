"""Fake `ModelClient` for tests: replays scripted replies/errors, records requests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.client import AiCallError, ModelReply, ModelRequest, TokenUsage

USAGE = TokenUsage(input_tokens=1830, output_tokens=210)


def _wire_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def to_wire(entries: Mapping[str, Any]) -> dict[str, Any]:
    """Per-key entries (`{key: {"value", "evidence"}}`, the fixtures' `model_output`
    format) as the schema answer `{"fields": [{"key", "value", "evidence"}]}` the model
    sends. A list value becomes one item per element; a missing evidence becomes ""."""
    items: list[dict[str, str]] = []
    for key, entry in entries.items():
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            entry = {"value": entry, "evidence": ""}
        value, evidence = entry.get("value"), entry.get("evidence")
        if value is None:
            continue
        for one in value if isinstance(value, list) else [value]:
            items.append({"key": key, "value": _wire_value(one), "evidence": str(evidence or "")})
    return {"fields": items}


def reply(
    output: Mapping[str, Any] | None = None,
    *,
    model: str = "claude-sonnet-5-5",
    stop_reason: str = "end_turn",
    text: str | None = None,
    usage: TokenUsage = USAGE,
) -> ModelReply:
    """A reply whose text is `text` as is, or the per-key entries `output` in wire format."""
    body = text if text is not None else json.dumps(to_wire(output or {}), ensure_ascii=False)
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
