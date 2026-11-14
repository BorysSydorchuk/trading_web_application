"""Digest snapshot + journal texts → short factual AI summary (POST /api/digests/{id}/ai-summary).

Same call rules as the trade extraction (app.services.ai.extraction.call_model: primary
model, fallback rule, deadline, one usage line per attempt), on ANTHROPIC_MODEL_SUMMARY with
the ``digest_summary.md`` prompt. The answer is a list of observations; the output guard
strips them, keeps at most ``MAX_OBSERVATIONS`` and caps the text at ``MAX_SUMMARY_CHARS``.
An empty answer is an ``invalid_output`` (502 ai_error). Nothing is saved here.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.domain.extraction import InvalidAnswer
from app.services.ai.client import ModelClient
from app.services.ai.extraction import (
    CallSpec,
    ExtractionSettings,
    UsageSummary,
    call_model,
    usage_summary,
)
from app.services.ai.prompt import digest_summary_system_prompt
from app.services.ai.usage_log import UsageLog

logger = logging.getLogger(__name__)

PURPOSE = "digest_summary"
MAX_OBSERVATIONS = 7
MAX_SUMMARY_CHARS = 4000
# One journal text in the input is cut to this many characters (keeps the call bounded).
MAX_JOURNAL_TEXT_CHARS = 3000
TRUNCATED_MARK = " […]"
# Snapshot parts the model reads; charts (curve points) and trade_ids add only noise.
SNAPSHOT_KEYS: tuple[str, ...] = (
    "currency",
    "combined",
    "by_account",
    "breakdowns",
    "rules",
    "bias",
)
JOURNAL_TEXT_FIELDS: tuple[str, ...] = ("mistakes", "lesson", "raw_text")

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"observations": {"type": "array", "items": {"type": "string"}}},
    "required": ["observations"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class TradeTexts:
    """Journal texts of one period trade (None / blank texts are left out of the input)."""

    id: int
    symbol: str
    net_pnl: Decimal | None
    r_multiple: Decimal | None
    mistakes: str | None
    lesson: str | None
    raw_text: str | None


@dataclass(frozen=True)
class SummaryInput:
    kind: str
    period_start: date
    period_end: date
    snapshot: Mapping[str, Any]
    trades: Sequence[TradeTexts]


@dataclass(frozen=True)
class SummaryOutcome:
    text: str
    usage: UsageSummary


def _clip(text: str) -> str:
    if len(text) <= MAX_JOURNAL_TEXT_CHARS:
        return text
    return text[:MAX_JOURNAL_TEXT_CHARS].rstrip() + TRUNCATED_MARK


def _trade_json(trade: TradeTexts) -> dict[str, Any] | None:
    texts = {
        name: _clip(value.strip())
        for name in JOURNAL_TEXT_FIELDS
        if (value := getattr(trade, name)) and value.strip()
    }
    if not texts:
        return None
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "net_pnl": None if trade.net_pnl is None else str(trade.net_pnl),
        "r_multiple": None if trade.r_multiple is None else str(trade.r_multiple),
        **texts,
    }


def build_user_text(inp: SummaryInput) -> str:
    """The user message: period, the snapshot numbers and the trades' journal texts (JSON)."""
    trades = [t for t in (_trade_json(trade) for trade in inp.trades) if t is not None]
    payload = {
        "period": {
            "kind": inp.kind,
            "start": inp.period_start.isoformat(),
            "end": inp.period_end.isoformat(),
        },
        "snapshot": {key: inp.snapshot[key] for key in SNAPSHOT_KEYS if key in inp.snapshot},
        "trades": trades,
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def summary_text(answer: Mapping[str, Any]) -> str:
    """Output guard: stripped non-empty observations (at most 7), one per line, capped at
    MAX_SUMMARY_CHARS. Raises InvalidAnswer for a wrong shape or an empty summary."""
    observations = answer.get("observations")
    if not isinstance(observations, list) or not all(isinstance(o, str) for o in observations):
        raise InvalidAnswer("observations is not a list of strings")
    lines = [" ".join(o.split()) for o in observations]
    kept = [line for line in lines if line][:MAX_OBSERVATIONS]
    text = "\n".join(kept)[:MAX_SUMMARY_CHARS].strip()
    if not text:
        raise InvalidAnswer("empty summary")
    return text


def _utc_now() -> datetime:
    return datetime.now(UTC)


def summarise_digest(
    inp: SummaryInput,
    *,
    client: ModelClient,
    settings: ExtractionSettings,
    usage_log: UsageLog,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utc_now,
) -> SummaryOutcome:
    """One summary call. Raises ExtractionFailed (kind per docs/api.md) and PromptError."""
    call = call_model(
        CallSpec(
            system=digest_summary_system_prompt(),
            schema=SUMMARY_SCHEMA,
            text=build_user_text(inp),
            convert=summary_text,
            purpose=PURPOSE,
        ),
        client=client,
        settings=settings,
        usage_log=usage_log,
        clock=clock,
        now=now,
    )
    text: str = call.output
    logger.info(
        "AI digest summary %s %s: %d lines on %s",
        inp.kind,
        inp.period_start,
        text.count("\n") + 1,
        call.reply.model,
    )
    return SummaryOutcome(text=text, usage=usage_summary(call, clock))
