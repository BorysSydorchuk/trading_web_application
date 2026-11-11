"""Per-tick values for the trade risk fallback, cross-currency aware (docs/api.md M5-09).

One rule for the MT5 sync and for a user-entered initial SL (PATCH /api/trades/{id}):

- same-currency spec (or a blank currency, see `is_cross_currency`): the spec's own
  ``tick_value``, unchanged;
- cross-currency spec: never ``tick_value``; the loss per tick per lot is
  ``tick_size * contract_size * rate`` from the account's fx_rates row (currencies
  upper-cased), or the MT5 check value when it differs by > 0.5 % (`choose_loss_per_tick`);
  no rate row, or unusable fields -> None, so the fallback risk is None.

`metrics.risk_amount` takes the pair as ``tick_value`` / ``loss_per_tick``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.fx import choose_loss_per_tick, is_cross_currency, loss_per_tick_from_rate
from app.models import FxRate
from app.models.account import SymbolSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskTickValues:
    """``metrics.risk_amount`` inputs: at most one of the two is set."""

    tick_value: Decimal | None
    loss_per_tick: Decimal | None


NO_VALUES = RiskTickValues(None, None)


def cross_loss_per_tick(
    account_id: int,
    symbol: str,
    tick_size: Decimal,
    contract_size: Decimal,
    row: FxRate | None,
    check: Decimal | None,
) -> Decimal | None:
    """Loss per tick per lot of a cross-currency spec from its rate row; None without a row
    or when the values cannot be used (WARNING, never raises)."""
    if row is None:
        return None
    try:
        rate_value = loss_per_tick_from_rate(tick_size, contract_size, row.rate)
        value, source = choose_loss_per_tick(rate_value, check)
    except (ValueError, ArithmeticError) as exc:
        logger.warning(
            "Account %s: %s loss per tick from the %s rate failed: %s; no risk fallback",
            account_id, symbol, row.pair, exc,
        )  # fmt: skip
        return None
    if source == "mt5_check":
        logger.warning(
            "Account %s: %s MT5 loss per tick %s differs from the %s rate value %s by more "
            "than 0.5 %%; using the MT5 value",
            account_id, symbol, check, row.pair, rate_value,
        )  # fmt: skip
    return value


def tick_values(
    currency_profit: str,
    tick_value: Decimal,
    account_currency: str | None,
    cross_loss: Decimal | None,
) -> RiskTickValues:
    """The spec's tick_value (same currency or unknown account currency), else only the FX
    loss per tick ``cross_loss`` (None -> no fallback risk)."""
    if account_currency is not None and is_cross_currency(currency_profit, account_currency):
        return RiskTickValues(None, cross_loss)
    return RiskTickValues(tick_value, None)


def rate_row(
    session: Session, account_id: int, from_currency: str, to_currency: str
) -> FxRate | None:
    """The account's latest (unique) rate row; currencies upper-cased as the sync stores them."""
    return session.scalar(
        select(FxRate).where(
            FxRate.account_id == account_id,
            FxRate.from_currency == from_currency.strip().upper(),
            FxRate.to_currency == to_currency.strip().upper(),
        )
    )


def stored_spec_tick_values(
    session: Session, account_id: int, account_currency: str, spec: SymbolSpec | None
) -> RiskTickValues:
    """Risk fallback values of a stored spec (user-entered SL); reads the DB only."""
    if spec is None:
        return NO_VALUES
    cross_loss: Decimal | None = None
    if is_cross_currency(spec.currency_profit, account_currency):
        row = rate_row(session, account_id, spec.currency_profit, account_currency)
        cross_loss = cross_loss_per_tick(
            account_id, spec.symbol, spec.tick_size, spec.contract_size, row,
            spec.mt5_loss_per_tick,
        )  # fmt: skip
    return tick_values(spec.currency_profit, spec.tick_value, account_currency, cross_loss)
