"""Bias note text → per-symbol bias fields (POST /api/bias/notes/extract, PRD 6.6).

Same call rules as the trade extraction (app.services.ai.extraction.call_model: model,
fallback, 28 s deadline, one usage line per attempt), with the bias prompt and schema; the
answer goes through app.domain.bias_extraction's guards. Nothing is saved here.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config_files.bias import BiasConfig
from app.domain.bias_extraction import (
    BiasDropped,
    BiasEntryResult,
    answer_values,
    apply_bias_guards,
    build_bias_schema,
)
from app.domain.extraction import NumberWords
from app.models.enums import BiasKind
from app.services.ai.client import ModelClient
from app.services.ai.extraction import (
    CallSpec,
    ExtractionSettings,
    UsageSummary,
    call_model,
    usage_summary,
)
from app.services.ai.prompt import extract_bias_system_prompt
from app.services.ai.usage_log import UsageLog

logger = logging.getLogger(__name__)

PURPOSE = "bias_extract"


@dataclass(frozen=True)
class BiasExtractionOutcome:
    entries: list[BiasEntryResult]
    dropped: list[BiasDropped]
    usage: UsageSummary


def _utc_now() -> datetime:
    return datetime.now(UTC)


def extract_bias_fields(
    text: str,
    kind: BiasKind,
    *,
    config: BiasConfig,
    number_words: NumberWords,
    client: ModelClient,
    settings: ExtractionSettings,
    usage_log: UsageLog,
    purpose: str = PURPOSE,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utc_now,
) -> BiasExtractionOutcome:
    """Run the bias extraction. Raises ExtractionFailed (kind per docs/api.md) and
    PromptError when the prompt file is missing."""
    call = call_model(
        CallSpec(
            system=extract_bias_system_prompt(config, kind),
            schema=build_bias_schema(config),
            text=text,
            convert=answer_values,
            purpose=purpose,
        ),
        client=client,
        settings=settings,
        usage_log=usage_log,
        clock=clock,
        now=now,
    )
    guarded = apply_bias_guards(config, call.output, text, number_words)
    if guarded.dropped:
        logger.info(
            "AI bias extraction (%s): dropped %s",
            kind.value,
            ", ".join(f"{d.symbol}.{d.key}:{d.reason}" for d in guarded.dropped),
        )
    return BiasExtractionOutcome(
        entries=guarded.entries, dropped=guarded.dropped, usage=usage_summary(call, clock)
    )
