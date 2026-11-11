"""Loss per tick of the calculator, cross-currency aware (docs/api.md M5-09).

Same-currency specs use the synced ``tick_value_loss``. Cross-currency specs (profit currency
!= account currency, case-insensitive) use ``tick_size * contract_size * rate`` from the
account's latest ``fx_rates`` row, or the stored MT5 check value when it differs by > 0.5 %;
without a rate row the request is 409 ``conversion_rate_unavailable`` (never tick_value).
Reads the DB only; never touches MT5.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fx import (
    choose_loss_per_tick,
    is_stale,
    loss_per_tick_from_rate,
)
from app.errors import ApiError
from app.models import FxRate
from app.models.account import SymbolSpec
from app.schemas import calculator as schemas


def rate_row(db: Session, account_id: int, from_currency: str, to_currency: str) -> FxRate:
    """The account's rate row (currencies upper-cased as the sync stores them) or 409."""
    source, target = from_currency.upper(), to_currency.upper()
    row = db.scalar(
        select(FxRate).where(
            FxRate.account_id == account_id,
            FxRate.from_currency == source,
            FxRate.to_currency == target,
        )
    )
    if row is None:
        raise ApiError(
            409,
            "conversion_rate_unavailable",
            f"No {source}->{target} conversion rate; run a sync",
            {"from_currency": source, "to_currency": target},
        )
    return row


def conversion_for(
    db: Session, account_id: int, spec: SymbolSpec, account_currency: str, now: datetime
) -> schemas.ConversionInfo:
    """Conversion of a cross-currency spec; ``spec`` sizing fields are already validated.

    Raises `ApiError` 409 conversion_rate_unavailable without a rate row.
    """
    row = rate_row(db, account_id, spec.currency_profit, account_currency)
    rate_value = loss_per_tick_from_rate(spec.tick_size, spec.contract_size, row.rate)
    _, source = choose_loss_per_tick(rate_value, spec.mt5_loss_per_tick)
    return schemas.ConversionInfo(
        pair=row.pair,
        from_currency=row.from_currency,
        to_currency=row.to_currency,
        rate=row.rate,
        side="bid" if row.inverted else "ask",
        inverted=row.inverted,
        rate_at=row.rate_at,
        stale=is_stale(row.rate_at, now),
        source=source,
        rate_loss_per_tick=rate_value,
        mt5_loss_per_tick=spec.mt5_loss_per_tick,
        mt5_checked_at=spec.mt5_loss_per_tick_at,
    )


def chosen_loss_per_tick(conversion: schemas.ConversionInfo) -> Decimal:
    """The MT5 check value when it won (> 0.5 % apart), else the rate value."""
    if conversion.source == "mt5_check" and conversion.mt5_loss_per_tick is not None:
        return conversion.mt5_loss_per_tick
    return conversion.rate_loss_per_tick
