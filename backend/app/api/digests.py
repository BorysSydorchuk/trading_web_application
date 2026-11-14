"""/api/digests: weekly and monthly digests (docs/api.md "Digests API")."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.ai import (
    ai_call_error,
    extraction_settings,
    get_key_tracker,
    get_model_client,
    get_usage_log,
)
from app.clock import utc_now
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.schemas import digests as schemas
from app.services import digests as service
from app.services.ai.client import ModelClient
from app.services.ai.digest_summary import summarise_digest
from app.services.ai.extraction import ExtractionFailed
from app.services.ai.key_status import KeyStatusTracker
from app.services.ai.usage_log import UsageLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/digests", tags=["digests"])


@router.post("", response_model=schemas.DigestOut)
def create_digest(
    body: schemas.DigestCreate,
    response: Response,
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> schemas.DigestOut:
    """Create (201) or regenerate (200) the digest of the period containing ``date``."""
    digest, created = service.generate(db, body.kind, body.date, now)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return digest


@router.get("", response_model=schemas.DigestList)
def list_digests(
    kind: schemas.DigestKindIn | None = None,
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> schemas.DigestList:
    return service.list_digests(db, kind, now)


# Static paths before "/{digest_id}" so they are not read as an id.
@router.get("/suggestion", response_model=schemas.DigestSuggestion)
def get_suggestion(
    db: Session = Depends(get_db), now: datetime = Depends(utc_now)
) -> schemas.DigestSuggestion:
    return service.suggestion(db, now)


@router.get("/by-period", response_model=schemas.DigestOut)
def get_by_period(
    kind: schemas.DigestKindIn, date: date, db: Session = Depends(get_db)
) -> schemas.DigestOut:
    return service.get_by_period(db, kind, date)


@router.get("/{digest_id}", response_model=schemas.DigestOut)
def get_digest(digest_id: int, db: Session = Depends(get_db)) -> schemas.DigestOut:
    return service.get(db, digest_id)


@router.patch("/{digest_id}", response_model=schemas.DigestOut)
def patch_digest(
    digest_id: int,
    body: schemas.DigestPatch,
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> schemas.DigestOut:
    return service.update_review(db, digest_id, body, now)


@router.post("/{digest_id}/ai-summary", response_model=schemas.DigestOut)
def create_ai_summary(
    digest_id: int,
    db: Session = Depends(get_db),
    client: ModelClient | None = Depends(get_model_client),
    usage_log: UsageLog = Depends(get_usage_log),
    key_tracker: KeyStatusTracker = Depends(get_key_tracker),
) -> schemas.DigestOut:
    """One AI call on ANTHROPIC_MODEL_SUMMARY; stores and returns the digest with ai_summary.

    Order: 404 → 503 ai_not_configured → AI call (502 ai_error leaves ai_summary unchanged).
    """
    summary_input = service.ai_summary_input(db, digest_id)
    db.rollback()  # no transaction stays open during the (slow) AI call
    if client is None:
        logger.warning("AI digest summary %s: ANTHROPIC_API_KEY is not set", digest_id)
        raise ApiError(503, "ai_not_configured", "ANTHROPIC_API_KEY is not set")
    settings = replace(extraction_settings(), primary_model=get_settings().anthropic_model_summary)
    try:
        outcome = summarise_digest(
            summary_input, client=client, settings=settings, usage_log=usage_log
        )
    except ExtractionFailed as exc:
        raise ai_call_error(exc, key_tracker) from None
    return service.store_ai_summary(db, digest_id, outcome.text)
