"""POST /api/trades/{id}/extract and GET /api/ai/usage (docs/api.md M2 "AI extraction",
"AI usage")."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Depends
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.api.config_files import config_error
from app.api.trades import journal_context
from app.config import get_settings
from app.config_files import ConfigError, get_number_words
from app.db import get_db
from app.domain.extraction import NumberWords
from app.errors import ApiError
from app.models import Trade
from app.schemas import ai as schemas
from app.services.ai.client import AnthropicModelClient, ModelClient
from app.services.ai.extraction import (
    ExtractionFailed,
    ExtractionOutcome,
    ExtractionSettings,
    extract_trade_fields,
)
from app.services.ai.usage_log import UsageLog, summarise_month, usage_log_path
from app.services.trade_journal import check_describable, requirement_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


@lru_cache(maxsize=1)
def _client_for(api_key: SecretStr) -> AnthropicModelClient:
    return AnthropicModelClient(api_key)


def get_model_client() -> ModelClient | None:
    """The AI client, or None when ANTHROPIC_API_KEY is empty (override in tests)."""
    settings = get_settings()
    if not settings.ai_configured:
        return None
    return _client_for(settings.anthropic_api_key)


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
    settings = get_settings()
    try:
        outcome = extract_trade_fields(
            body.text,
            trade_id=trade_id,
            config=config,
            number_words=number_words,
            client=client,
            settings=ExtractionSettings(
                primary_model=settings.anthropic_model_extraction,
                fallback_model=settings.anthropic_model_fallback,
                effort=settings.anthropic_effort,
            ),
            usage_log=usage_log,
            scope=scope,
        )
    except ExtractionFailed as exc:
        raise ApiError(
            502, "ai_error", f"AI call failed: {exc.message}", {"kind": exc.kind}
        ) from None
    return _to_result(outcome)


@router.get("/ai/usage", response_model=schemas.AiUsageOut)
def ai_usage(usage_log: UsageLog = Depends(get_usage_log)) -> schemas.AiUsageOut:
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
    )
