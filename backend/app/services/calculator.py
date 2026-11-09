"""Position-size calculator service (docs/api.md M5-04c, PRD 6.8).

Answers from synced symbol specs and the account balance only. Never touches MT5 and never
creates margin requests: the margin metadata is read from the latest done request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.position_size import (
    ErrorCode,
    PositionSizeError,
    PositionSizeRequest,
    PositionSizeResult,
    calculate_position_size,
)
from app.domain.position_size import SymbolSpec as CoreSpec
from app.errors import ApiError
from app.models import Account
from app.models.account import SymbolSpec
from app.models.calculator import CalculatorMarginRequest
from app.schemas import calculator as schemas
from app.schemas.calculator import plain_decimal

logger = logging.getLogger(__name__)

DEFAULT_RISK_PERCENT = Decimal("1")
# Precision for the two reported quotients (sl_points, scaled margin), including the
# margin product. Inputs are bounded by the core's 64-digit limit and NUMERIC storage,
# so exact results always fit.
QUOTIENT_PRECISION = 160
SIZING_SPEC_KEYS = (
    "point",
    "tick_size",
    "tick_value_loss",
    "volume_min",
    "volume_step",
    "volume_max",
)
# PositionSizeError code -> HTTP status (docs/api.md M5-04c); unknown codes are 422.
_ERROR_STATUS: dict[ErrorCode, int] = {"specs_invalid": 409}
NO_CACHED_MARGIN = schemas.MarginInfo(
    source="unavailable",
    amount=None,
    currency=None,
    calculated_at=None,
    sample_price=None,
    sample_volume=None,
    reason="no_cached_margin",
)


@dataclass(frozen=True)
class EffectiveBalance:
    amount: Decimal
    source: Literal["reference", "synced"]
    synced_at: datetime | None


@dataclass(frozen=True)
class SizingContext:
    """What the response needs from the account, the stored spec and the balance."""

    account_id: int
    currency: str
    symbol: str
    specs_at: datetime
    point: Decimal
    balance: EffectiveBalance


def _is_positive(value: Decimal) -> bool:
    # NUMERIC can hold NaN: check finiteness first, a NaN comparison would raise.
    return value.is_finite() and value > 0


def get_account_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise ApiError(404, "not_found", "Account not found", {"account_id": account_id})
    return account


def list_symbol_specs(db: Session, account_id: int) -> schemas.SymbolSpecList:
    get_account_or_404(db, account_id)
    rows = db.scalars(
        select(SymbolSpec).where(SymbolSpec.account_id == account_id).order_by(SymbolSpec.symbol)
    )
    return schemas.SymbolSpecList(
        items=[schemas.SymbolSpecItem.model_validate(row, from_attributes=True) for row in rows]
    )


def _validate_combinations(body: schemas.CalculateInput) -> None:
    fields: dict[str, str] = {}
    if (body.sl_price is None) == (body.sl_points is None):
        message = "specify exactly one of sl_price and sl_points"
        fields = {"sl_price": message, "sl_points": message}
    if body.risk_percent is not None and body.risk_amount is not None:
        message = "specify at most one of risk_percent and risk_amount"
        fields |= {"risk_percent": message, "risk_amount": message}
    if fields:
        raise ApiError(422, "validation_error", "Request validation failed", {"fields": fields})


def _spec_or_404(db: Session, account_id: int, symbol: str) -> SymbolSpec:
    # Exact match only (VARCHAR equality): never a prefix or case-insensitive match.
    spec = db.scalar(
        select(SymbolSpec).where(SymbolSpec.account_id == account_id, SymbolSpec.symbol == symbol)
    )
    if spec is None:
        raise ApiError(404, "not_found", "Symbol spec not found", {"symbol": symbol})
    return spec


def effective_balance(account: Account) -> EffectiveBalance:
    """Reference balance, else last synced balance; never starting_balance."""
    if account.reference_balance is not None:
        balance = EffectiveBalance(account.reference_balance, "reference", None)
    elif account.balance is not None:
        balance = EffectiveBalance(account.balance, "synced", account.balance_synced_at)
    else:
        raise ApiError(409, "balance_unavailable", "No reference balance and no synced balance")
    if not _is_positive(balance.amount):
        raise ApiError(409, "balance_unavailable", "The effective balance is not positive")
    return balance


def core_spec(spec: SymbolSpec) -> CoreSpec:
    """Sizing fields of a stored spec; null or non-positive values are specs_incomplete."""
    values = {key: getattr(spec, key) for key in SIZING_SPEC_KEYS}
    missing = [key for key, value in values.items() if value is None or not _is_positive(value)]
    if missing:
        raise ApiError(
            409,
            "specs_incomplete",
            "Symbol spec is incomplete; run a sync",
            {"missing": missing, "symbol": spec.symbol},
        )
    return CoreSpec(**values)


def _core_request(body: schemas.CalculateInput, balance: Decimal) -> PositionSizeRequest:
    risk_percent = body.risk_percent
    if risk_percent is None and body.risk_amount is None:
        risk_percent = DEFAULT_RISK_PERCENT
    return PositionSizeRequest(
        direction=body.direction,
        entry=body.entry,
        balance=balance,
        sl_price=body.sl_price,
        sl_points=body.sl_points,
        risk_percent=risk_percent,
        risk_amount=body.risk_amount,
    )


def error_details(exc: PositionSizeError, spec: CoreSpec) -> dict[str, Any] | None:
    """`details` of a core rejection; validation_error always carries a `fields` object."""
    if exc.code == "validation_error":
        return {"fields": {name: str(exc) for name in exc.fields}}
    if exc.code == "below_min_volume" and exc.min_volume_risk is not None:
        return {
            "volume_min": plain_decimal(spec.volume_min),
            "min_volume_risk": plain_decimal(exc.min_volume_risk),
        }
    if exc.code == "off_tick_grid":
        return {"fields": list(exc.fields)}  # entry / sl_price (effective SL)
    return None


def _domain_error(exc: PositionSizeError, spec: CoreSpec, body: schemas.CalculateInput) -> ApiError:
    logger.info(
        "Calculator rejected account %s %s: %s (%s)", body.account_id, body.symbol, exc.code, exc
    )
    return ApiError(_ERROR_STATUS.get(exc.code, 422), exc.code, str(exc), error_details(exc, spec))


def _scaled(value: Decimal, numerator: Decimal, denominator: Decimal) -> Decimal:
    """value * numerator / denominator, both steps in one high-precision local context."""
    with localcontext() as context:
        context.prec = QUOTIENT_PRECISION
        return value * numerator / denominator


def _latest_sample(
    db: Session, context: SizingContext, direction: str
) -> CalculatorMarginRequest | None:
    # Done rows always have finished_at (CHECK result_matches_status); ties go to the newer id.
    return db.scalar(
        select(CalculatorMarginRequest)
        .where(
            CalculatorMarginRequest.account_id == context.account_id,
            CalculatorMarginRequest.symbol == context.symbol,
            CalculatorMarginRequest.direction == direction,
            CalculatorMarginRequest.status == "done",
            CalculatorMarginRequest.margin.is_not(None),
        )
        .order_by(CalculatorMarginRequest.finished_at.desc(), CalculatorMarginRequest.id.desc())
        .limit(1)
    )


def margin_info(
    db: Session, context: SizingContext, direction: str, volume: Decimal
) -> schemas.MarginInfo:
    """Offline estimate from the latest done request (same account, exact symbol, direction)."""
    sample = _latest_sample(db, context, direction)
    if sample is None or sample.margin is None:
        return NO_CACHED_MARGIN
    return schemas.MarginInfo(
        source="cached_estimate",
        amount=_scaled(sample.margin, volume, sample.volume),
        currency=sample.currency,
        calculated_at=sample.finished_at,
        sample_price=sample.entry,
        sample_volume=sample.volume,
        reason=None,
    )


def _sl_points(request: PositionSizeRequest, point: Decimal, distance: Decimal) -> Decimal:
    """The entered SL points, else the price distance in broker points."""
    if request.sl_points is not None:
        return request.sl_points
    return _scaled(distance, Decimal(1), point)


def _result(
    context: SizingContext,
    request: PositionSizeRequest,
    sized: PositionSizeResult,
    margin: schemas.MarginInfo,
) -> schemas.CalculateResult:
    balance = context.balance
    return schemas.CalculateResult(
        account_id=context.account_id,
        symbol=context.symbol,
        direction=request.direction,
        entry=request.entry,
        sl_price=sized.sl_price,
        sl_distance=sized.sl_distance,
        sl_points=_sl_points(request, context.point, sized.sl_distance),
        balance=balance.amount,
        balance_source=balance.source,
        balance_synced_at=balance.synced_at,
        currency=context.currency,
        risk_percent=request.risk_percent,
        risk_amount=request.risk_amount,
        risk_budget=sized.risk_budget,
        volume=sized.volume,
        actual_risk=sized.actual_risk,
        actual_risk_percent=sized.actual_risk_percent,
        tp_1_5=sized.tp_1_5,
        tp_2=sized.tp_2,
        tp_3=sized.tp_3,
        specs_at=context.specs_at,
        margin=margin,
    )


def calculate(db: Session, body: schemas.CalculateInput) -> schemas.CalculateResult:
    """Validate selection, balance and specs, size with the pure core, attach margin info."""
    _validate_combinations(body)
    account = get_account_or_404(db, body.account_id)
    spec = _spec_or_404(db, account.id, body.symbol)
    balance = effective_balance(account)
    sizing_spec = core_spec(spec)
    request = _core_request(body, balance.amount)
    try:
        sized = calculate_position_size(request, sizing_spec)
    except PositionSizeError as exc:
        raise _domain_error(exc, sizing_spec, body) from None
    context = SizingContext(
        account_id=account.id,
        currency=account.currency,
        symbol=spec.symbol,
        specs_at=spec.synced_at,
        point=sizing_spec.point,
        balance=balance,
    )
    margin = margin_info(db, context, request.direction, sized.volume)
    return _result(context, request, sized, margin)
