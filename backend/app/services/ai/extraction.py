"""Trade description → journal fields (POST /api/trades/{id}/extract, PRD 6.5).

One call on ANTHROPIC_MODEL_EXTRACTION; on overload / 5xx / timeout / connection error
(no SDK retries) one attempt on ANTHROPIC_MODEL_FALLBACK, all within the
30 s target. Never a fallback on refusal (a prompt bug). Every attempt is one line in
logs/ai_usage.jsonl. The answer then goes through the guards in app.domain.extraction.
Nothing is saved here.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.config import AnthropicEffort
from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.extraction import (
    Dropped,
    apply_guards,
    build_extraction_schema,
    extraction_missing,
)
from app.services.ai.client import (
    AiCallError,
    AiErrorKind,
    ModelClient,
    ModelReply,
    ModelRequest,
    TokenUsage,
)
from app.services.ai.prompt import extract_trade_system_prompt
from app.services.ai.usage_log import UsageLog, UsageRecord, cost_for, utc_ts

logger = logging.getLogger(__name__)

PURPOSE = "extract"
MAX_TOKENS = 4000
# Time budget (PRD 6.5: under 30 s). Primary: one try (no SDK retries) of at most
# PRIMARY_TIMEOUT_S; the fallback gets min(FALLBACK_TIMEOUT_MAX_S, what is left of the
# budget) and is skipped when less than MIN_FALLBACK_S remain. Worst case 12 + 15 = 27 s.
TOTAL_BUDGET_S = 30.0
PRIMARY_TIMEOUT_S = 12.0
PRIMARY_MAX_RETRIES = 0
FALLBACK_TIMEOUT_MAX_S = 15.0
FALLBACK_MAX_RETRIES = 0
MIN_FALLBACK_S = 5.0


@dataclass(frozen=True)
class UsageSummary:
    model: str
    fallback_used: bool
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    duration_ms: int


@dataclass(frozen=True)
class ExtractionOutcome:
    fields: dict[str, Any]
    ai_filled_fields: list[str]
    missing_required: list[str]
    dropped: list[Dropped]
    usage: UsageSummary


class ExtractionFailed(Exception):  # noqa: N818 - reads as "raise ExtractionFailed"
    def __init__(self, kind: AiErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: AiErrorKind = kind
        self.message = message


@dataclass(frozen=True)
class ExtractionSettings:
    primary_model: str
    fallback_model: str
    effort: AnthropicEffort


def parse_reply(reply: ModelReply) -> dict[str, Any]:
    """The JSON object of a reply. Raises AiCallError refusal / invalid_output."""
    if reply.stop_reason == "refusal":
        raise AiCallError("refusal", "model refused to answer")
    if reply.stop_reason == "max_tokens":
        raise AiCallError("invalid_output", "output cut off at max_tokens")
    if reply.text is None:
        raise AiCallError("invalid_output", "no text block in the reply")
    try:
        data = json.loads(reply.text)
    except ValueError:
        raise AiCallError("invalid_output", "reply is not valid JSON") from None
    if not isinstance(data, dict):
        raise AiCallError("invalid_output", "reply is not a JSON object")
    return data


@dataclass
class _Run:
    """Attempts of one extraction; writes one usage line per attempt."""

    client: ModelClient
    log: UsageLog
    trade_id: int
    system: str
    schema: dict[str, Any]
    text: str
    effort: AnthropicEffort
    clock: Callable[[], float]
    now: Callable[[], datetime]
    usage: TokenUsage = field(default_factory=TokenUsage)
    costs: list[Decimal | None] = field(default_factory=list)

    def attempt(
        self, model: str, timeout_s: float, retries: int, *, fallback: bool
    ) -> tuple[ModelReply, dict[str, Any]]:
        request = ModelRequest(
            model, self.system, self.text, self.schema, self.effort, MAX_TOKENS, timeout_s, retries
        )
        started = self.clock()
        reply: ModelReply | None = None
        try:
            reply = self.client.create(request)
            output = parse_reply(reply)
        except AiCallError as exc:
            self._record(model, reply, started, fallback, exc.kind)
            raise
        self._record(model, reply, started, fallback, None)
        return reply, output

    def _record(
        self,
        requested: str,
        reply: ModelReply | None,
        started: float,
        fallback: bool,
        error: AiErrorKind | None,
    ) -> None:
        usage = reply.usage if reply is not None else TokenUsage()
        answered = reply.model if reply is not None else None
        cost = cost_for(answered, usage)
        self.usage = self.usage + usage
        self.costs.append(cost)
        self.log.append(
            UsageRecord(
                ts=utc_ts(self.now()),
                purpose=PURPOSE,
                trade_id=self.trade_id,
                requested_model=requested,
                model=answered,
                fallback_used=fallback,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
                cost_usd=None if cost is None else str(cost),
                ok=error is None,
                error_kind=error,
                duration_ms=round((self.clock() - started) * 1000),
            )
        )

    def total_cost(self) -> Decimal | None:
        if any(c is None for c in self.costs):
            return None
        return sum((c for c in self.costs if c is not None), Decimal("0.0000"))


def _failed(trade_id: int, exc: AiCallError) -> ExtractionFailed:
    if exc.kind == "refusal":
        logger.error("AI extraction refused for trade %s: prompt bug, check the prompt", trade_id)
    else:
        logger.error("AI extraction failed for trade %s: %s (%s)", trade_id, exc.kind, exc.message)
    return ExtractionFailed(exc.kind, exc.message)


def _call_with_fallback(
    run: _Run, settings: ExtractionSettings, started: float
) -> tuple[ModelReply, dict[str, Any], bool]:
    try:
        reply, output = run.attempt(
            settings.primary_model, PRIMARY_TIMEOUT_S, PRIMARY_MAX_RETRIES, fallback=False
        )
        return reply, output, False
    except AiCallError as exc:
        remaining = TOTAL_BUDGET_S - (run.clock() - started)
        if not exc.fallback_ok or remaining < MIN_FALLBACK_S:
            raise _failed(run.trade_id, exc) from exc
        logger.warning(
            "AI extraction trade %s: %s on %s (%s), falling back to %s",
            run.trade_id,
            exc.kind,
            settings.primary_model,
            exc.message,
            settings.fallback_model,
        )
    try:
        timeout = min(remaining, FALLBACK_TIMEOUT_MAX_S)
        reply, output = run.attempt(
            settings.fallback_model, timeout, FALLBACK_MAX_RETRIES, fallback=True
        )
    except AiCallError as exc:
        raise _failed(run.trade_id, exc) from exc
    return reply, output, True


def _utc_now() -> datetime:
    return datetime.now(UTC)


def extract_trade_fields(
    text: str,
    *,
    trade_id: int,
    config: JournalFieldsConfig,
    client: ModelClient,
    settings: ExtractionSettings,
    usage_log: UsageLog,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utc_now,
) -> ExtractionOutcome:
    """Run the extraction. Raises ExtractionFailed (kind per docs/api.md)."""
    run = _Run(
        client=client,
        log=usage_log,
        trade_id=trade_id,
        system=extract_trade_system_prompt(config),
        schema=build_extraction_schema(config),
        text=text,
        effort=settings.effort,
        clock=clock,
        now=now,
    )
    started = clock()
    reply, output, fallback_used = _call_with_fallback(run, settings, started)
    guarded = apply_guards(config, output, text)
    if guarded.dropped:
        logger.info(
            "AI extraction trade %s: dropped %s",
            trade_id,
            ", ".join(f"{d.key}:{d.reason}" for d in guarded.dropped),
        )
    return ExtractionOutcome(
        fields=guarded.fields,
        ai_filled_fields=guarded.ai_filled_fields,
        missing_required=extraction_missing(config, guarded.fields),
        dropped=guarded.dropped,
        usage=UsageSummary(
            model=reply.model,
            fallback_used=fallback_used,
            input_tokens=run.usage.input_tokens,
            output_tokens=run.usage.output_tokens,
            cost_usd=run.total_cost(),
            duration_ms=round((clock() - started) * 1000),
        ),
    )
