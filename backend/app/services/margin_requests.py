"""Calculator margin requests (docs/api.md M5-04d, PRD 6.8).

The API only queues a request: it re-runs the calculate sizing (same validation, same
errors), stores the server-computed volume and returns. The worker job
(`app.worker.margin_job`) asks MT5. No API process owns or initializes MT5.

De-duplication is done here, not by a DB index (DECISIONS 2026-11-09): an identical
(account, exact canonical symbol, direction, volume, entry) request still `pending` and not past
`expires_at`, or `processing` for less than `STALE_PROCESSING_S`, is returned instead of a
new row. It is best effort: two identical POSTs at the same moment may both insert, which
only costs one extra MT5 lookup.
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models.calculator import CalculatorMarginRequest
from app.mt5.real import (
    CONNECT_GRACE_S,
    DEFAULT_CALL_TIMEOUT_S,
    RETRY_DELAY_S,
    SHUTDOWN_TIMEOUT_S,
)
from app.mt5.source import DEFAULT_CONNECT_TIMEOUT_S
from app.schemas import calculator as schemas
from app.services.calculator import size

logger = logging.getLogger(__name__)

MARGIN_REQUEST_TTL = timedelta(seconds=60)

# A `processing` row older than this is stuck (result lost, worker died): the worker sweeps
# it to failed/`interrupted` and de-dup ignores it. Worst-case lookup with RealMt5Source
# defaults: initialize + its grace, account_info and calc_margin each with one retry, and
# shutdown (75 + 2 * 60.5 + 5 = 201 s), plus a minute of slack -> 261 s.
_READ_ATTEMPTS = 2  # first try + RealMt5Source's one retry on transient IPC errors
_READ_WORST_S = _READ_ATTEMPTS * DEFAULT_CALL_TIMEOUT_S + RETRY_DELAY_S
_LOOKUP_WORST_S = (
    DEFAULT_CONNECT_TIMEOUT_S + CONNECT_GRACE_S + 2 * _READ_WORST_S + SHUTDOWN_TIMEOUT_S
)
STALE_GRACE_S = 60
STALE_PROCESSING_S = math.ceil(_LOOKUP_WORST_S) + STALE_GRACE_S
STALE_PROCESSING = timedelta(seconds=STALE_PROCESSING_S)
MAX_ID = schemas.MAX_ID
# calculator_margin_requests.volume / entry are NUMERIC(20, 8).
_STORED_QUANTUM = Decimal("1e-8")
_STORED_INTEGER_DIGITS = 12
FINISHED_WITH_ERROR = ("failed", "expired")


def check_storable(field: str, value: Decimal) -> None:
    """Never let the DB round or overflow a price/volume: 422 naming the field.

    Only a 12+ integer-digit entry is reachable through calculate today; decimals beyond 8
    and volume overflow are excluded by the stored tick/step grid and volume_max.
    """
    fits = value.adjusted() < _STORED_INTEGER_DIGITS and value == value.quantize(_STORED_QUANTUM)
    if not fits:
        message = "must have at most 12 integer digits and 8 decimal places"
        raise ApiError(
            422, "validation_error", "Request validation failed", {"fields": {field: message}}
        )


def _open_duplicate(
    db: Session, account_id: int, symbol: str, direction: str, volume: Decimal, entry: Decimal
) -> CalculatorMarginRequest | None:
    """The newest identical open request, if any (best effort, see module doc)."""
    model = CalculatorMarginRequest
    return db.scalar(
        select(model)
        .where(
            model.account_id == account_id,
            model.symbol == symbol,
            model.direction == direction,
            model.volume == volume,
            model.entry == entry,
            or_(
                and_(
                    model.status == "processing",
                    model.started_at >= func.now() - STALE_PROCESSING,
                ),
                and_(model.status == "pending", model.expires_at > func.now()),
            ),
        )
        .order_by(model.id.desc())
        .limit(1)
    )


def to_item(row: CalculatorMarginRequest) -> schemas.MarginRequestItem:
    done = row.status == "done"
    return schemas.MarginRequestItem(
        id=row.id,
        account_id=row.account_id,
        symbol=row.symbol,
        direction=row.direction,  # type: ignore[arg-type]  # CHECK direction_valid
        volume=row.volume,
        entry=row.entry,
        status=row.status,  # type: ignore[arg-type]  # CHECK status_valid
        source="mt5" if done else None,
        amount=row.margin if done else None,
        currency=row.currency,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        expires_at=row.expires_at,
        error_code=row.error_code if row.status in FINISHED_WITH_ERROR else None,
    )


def create(db: Session, body: schemas.CalculateInput) -> schemas.MarginRequestItem:
    """Size like calculate (its errors unchanged, no row), then queue or reuse a request."""
    sized = size(db, body)
    context, volume, entry = sized.context, sized.result.volume, sized.request.entry
    direction = sized.request.direction
    check_storable("entry", entry)
    check_storable("volume", volume)
    # Best effort: a simultaneous identical POST may insert too (one extra lookup, harmless).
    existing = _open_duplicate(db, context.account_id, context.symbol, direction, volume, entry)
    if existing is not None:
        return to_item(existing)
    row = CalculatorMarginRequest(
        account_id=context.account_id,
        symbol=context.symbol,
        broker_symbol=context.broker_symbol,  # MT5 is asked with the broker name (M5-08)
        direction=direction,
        volume=volume,
        entry=entry,
        currency=context.currency,
        status="pending",
        # Same transaction as the created_at default now(): exactly created_at + TTL.
        expires_at=func.now() + MARGIN_REQUEST_TTL,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "Margin request %s queued: account %s %s %s %s @ %s",
        row.id,
        row.account_id,
        row.symbol,
        row.direction,
        row.volume,
        row.entry,
    )
    return to_item(row)


def get(db: Session, request_id: int) -> schemas.MarginRequestItem:
    row = db.get(CalculatorMarginRequest, request_id) if 0 < request_id <= MAX_ID else None
    if row is None:
        raise ApiError(404, "not_found", "Margin request not found", {"id": request_id})
    return to_item(row)
