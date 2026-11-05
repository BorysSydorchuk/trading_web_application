"""POST /api/trades/{id}/extract, POST /api/bias/notes/extract, GET /api/ai/usage and
POST /api/ai/check (docs/api.md M2 "AI extraction", "AI usage", M3 "AI key status", M4 "Bias
extraction")."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.config_files import config_error
from app.api.trades import journal_context
from app.config import get_settings
from app.config_files import ConfigError, get_bias_config, get_number_words
from app.db import get_db
from app.domain.extraction import NumberWords
from app.errors import ApiError
from app.models import Trade
from app.models.enums import BiasKind
from app.schemas import ai as schemas
from app.services.ai.bias_extraction import BiasExtractionOutcome, extract_bias_fields
from app.services.ai.client import ModelClient, shared_client
from app.services.ai.extraction import (
    ExtractionFailed,
    ExtractionOutcome,
    ExtractionSettings,
    extract_trade_fields,
)
from app.services.ai.key_status import KeyStatus, KeyStatusTracker
from app.services.ai.usage_log import UsageLog, summarise_month, usage_log_path
from app.services.trade_journal import check_describable, requirement_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


def get_model_client() -> ModelClient | None:
    """The AI client, or None when ANTHROPIC_API_KEY is empty (override in tests)."""
    settings = get_settings()
    if not settings.ai_configured:
        return None
    return shared_client(settings.anthropic_api_key)


def get_key_tracker(request: Request) -> KeyStatusTracker:
    """The process-wide key status (created in `create_app`; override in tests)."""
    tracker: KeyStatusTracker = request.app.state.ai_key
    return tracker


def key_out(status: KeyStatus) -> schemas.AiKeyOut:
    return schemas.AiKeyOut(state=status.state, checked_at=status.checked_at)


def get_usage_log() -> UsageLog:
    return UsageLog(usage_log_path(get_settings()))


def _to_result(outcome: ExtractionOutcome) -> schemas.ExtractResult:
    usage = outcome.usage
    return schemas.ExtractResult(
        fields=outcome.fields,
        ai_filled_fields=outcome.ai_filled_fields,
        missing_required=outcome.missing_required,
        dropped=[schemas.DroppedOut(key=d.key, reason=d.reason) for d in outcome.dropped],
        usage=schemas.ExtractUsageOut(
            model=usage.model,
            fallback_used=usage.fallback_used,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            duration_ms=usage.duration_ms,
        ),
    )


def _number_words() -> NumberWords:
    try:
        return get_number_words()
    except ConfigError as exc:
        raise config_error(exc) from None


@router.post("/trades/{trade_id}/extract", response_model=schemas.ExtractResult)
def extract(
    trade_id: int,
    body: schemas.ExtractInput,
    db: Session = Depends(get_db),
    client: ModelClient | None = Depends(get_model_client),
    usage_log: UsageLog = Depends(get_usage_log),
    key_tracker: KeyStatusTracker = Depends(get_key_tracker),
) -> schemas.ExtractResult:
    """Prefill the journal from a description. Saves nothing except the usage log."""
    config, required_since = journal_context(db)
    number_words = _number_words()
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise ApiError(404, "not_found", "Trade not found", {"id": trade_id})
    check_describable(trade)
    scope = requirement_scope(trade, required_since)
    db.rollback()  # no transaction stays open during the (slow) AI call
    if client is None:
        logger.warning("AI extraction for trade %s: ANTHROPIC_API_KEY is not set", trade_id)
        raise ApiError(503, "ai_not_configured", "ANTHROPIC_API_KEY is not set")
    try:
        outcome = extract_trade_fields(
            body.text,
            trade_id=trade_id,
            config=config,
            number_words=number_words,
            client=client,
            settings=_extraction_settings(),
            usage_log=usage_log,
            scope=scope,
        )
    except ExtractionFailed as exc:
        raise _ai_error(exc, key_tracker) from None
    return _to_result(outcome)


def _ai_error(exc: ExtractionFailed, key_tracker: KeyStatusTracker) -> ApiError:
    """502 ai_error; an auth error also marks the key invalid (M3-17)."""
    if exc.kind == "auth":
        key_tracker.mark_invalid(exc.message)
    return ApiError(502, "ai_error", f"AI call failed: {exc.message}", {"kind": exc.kind})


def _extraction_settings() -> ExtractionSettings:
    settings = get_settings()
    return ExtractionSettings(
        primary_model=settings.anthropic_model_extraction,
        fallback_model=settings.anthropic_model_fallback,
        effort=settings.anthropic_effort,
    )


def _bias_result(outcome: BiasExtractionOutcome) -> schemas.BiasExtractResult:
    usage = outcome.usage
    return schemas.BiasExtractResult(
        entries=[
            schemas.BiasExtractEntryOut(symbol=e.symbol, fields=e.fields, evidence=e.evidence)
            for e in outcome.entries
        ],
        dropped=[
            schemas.BiasDroppedOut(symbol=d.symbol, key=d.key, reason=d.reason)
            for d in outcome.dropped
        ],
        usage=schemas.ExtractUsageOut(
            model=usage.model,
            fallback_used=usage.fallback_used,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            duration_ms=usage.duration_ms,
        ),
    )


@router.post("/bias/notes/extract", response_model=schemas.BiasExtractResult, tags=["bias"])
def extract_bias(
    body: schemas.BiasExtractInput,
    client: ModelClient | None = Depends(get_model_client),
    usage_log: UsageLog = Depends(get_usage_log),
    key_tracker: KeyStatusTracker = Depends(get_key_tracker),
) -> schemas.BiasExtractResult:
    """Prefill bias entries from a note text. Saves nothing except the usage log."""
    try:
        config = get_bias_config()
    except ConfigError as exc:
        raise config_error(exc) from None
    number_words = _number_words()
    if client is None:
        logger.warning("AI bias extraction: ANTHROPIC_API_KEY is not set")
        raise ApiError(503, "ai_not_configured", "ANTHROPIC_API_KEY is not set")
    try:
        outcome = extract_bias_fields(
            body.text,
            BiasKind(body.kind),
            config=config,
            number_words=number_words,
            client=client,
            settings=_extraction_settings(),
            usage_log=usage_log,
        )
    except ExtractionFailed as exc:
        raise _ai_error(exc, key_tracker) from None
    return _bias_result(outcome)


@router.get("/ai/usage", response_model=schemas.AiUsageOut)
def ai_usage(
    usage_log: UsageLog = Depends(get_usage_log),
    key_tracker: KeyStatusTracker = Depends(get_key_tracker),
) -> schemas.AiUsageOut:
    """Month-to-date (Europe/Brussels) AI usage from logs/ai_usage.jsonl."""
    settings = get_settings()
    month = summarise_month(usage_log.path, datetime.now(UTC))
    return schemas.AiUsageOut(
        month=month.month,
        cost_usd=month.cost_usd,
        calls=month.calls,
        failed_calls=month.failed_calls,
        unpriced_calls=month.unpriced_calls,
        input_tokens=month.input_tokens,
        output_tokens=month.output_tokens,
        configured=settings.ai_configured,
        extraction_model=settings.anthropic_model_extraction,
        key_state=key_tracker.status().state,
    )


@router.post("/ai/check", response_model=schemas.AiKeyOut)
def ai_check(key_tracker: KeyStatusTracker = Depends(get_key_tracker)) -> schemas.AiKeyOut:
    """Re-check the key now (blocking, at most ~10 s)."""
    return key_out(key_tracker.check())
