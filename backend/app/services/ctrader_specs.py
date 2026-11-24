"""cTrader specs, conversion rates and the trade risk inputs (docs/api.md phase c, c1-c3).

Write side of `app.ctrader.market`, through the MT5 code paths: specs go into ``symbol_specs``
by (account, broker name) with the canonical name of ``symbols.yaml`` (`sync.upsert_specs`),
rates into ``fx_rates`` (`fx_sync.upsert_rates`, same 8 dp half-up rate). ``mt5_loss_per_tick``
stays NULL for cTrader (no ``order_calc_profit``), so the rate value is always the one used.

`store_market` runs in a savepoint and never raises: a failure is a WARNING, the rows stay as
they were and the balance of the same cycle is kept. `risk_inputs` gives the trade writer the
stored specs and the FX loss per tick per lot of the cross-currency ones, as MT5 passes them.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files.symbols import SymbolsConfig
from app.ctrader.market import MarketRead
from app.domain.fx import is_cross_currency
from app.domain.symbols import canonical_symbol
from app.models import Account, SymbolSpec
from app.mt5.types import RawSymbolSpec
from app.services.fx_sync import upsert_rates
from app.services.fx_values import cross_loss_per_tick, rate_row
from app.services.sync import upsert_specs

logger = logging.getLogger(__name__)


def write_ctrader_specs(
    session: Session,
    account: Account,
    specs: Mapping[str, RawSymbolSpec],
    symbols: SymbolsConfig,
    now: datetime,
) -> int:
    """Upsert the specs (keyed by broker name; no commit). Returns the number written."""
    canonical = {name: canonical_symbol(symbols, name) for name in specs}
    return upsert_specs(session, account.id, specs.values(), now, canonical)


def store_market(
    session: Session,
    account: Account,
    market: MarketRead | None,
    symbols: SymbolsConfig,
    now: datetime,
) -> None:
    """Specs and rates of one read in a savepoint (no commit); never raises."""
    if market is None or (not market.specs and not market.quotes):
        return
    try:
        with session.begin_nested():
            write_ctrader_specs(session, account, market.specs, symbols, now)
            upsert_rates(session, account.id, market.quotes, now)
            session.flush()
    except Exception as exc:
        logger.warning(
            "cTrader account %s: specs and FX rates not stored: %s",
            account.id,
            type(exc).__name__,
            exc_info=True,
        )


def _raw(row: SymbolSpec) -> RawSymbolSpec:
    return RawSymbolSpec(
        name=row.symbol,
        digits=row.digits,
        contract_size=row.contract_size,
        tick_size=row.tick_size,
        tick_value=row.tick_value,
        volume_min=row.volume_min,
        volume_step=row.volume_step,
        volume_max=row.volume_max,
        currency_profit=row.currency_profit,
        currency_margin=row.currency_margin,
        point=row.point,
        tick_value_loss=row.tick_value_loss,
    )


def risk_inputs(
    session: Session, account: Account
) -> tuple[dict[str, RawSymbolSpec], dict[str, Decimal | None]]:
    """Stored specs by broker name and the FX loss per tick per lot of the cross-currency
    ones (`cross_loss_per_tick`; None without a rate row -> no fallback risk)."""
    session.flush()  # no autoflush: rows written this cycle must be visible
    rows = session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account.id)).all()
    specs = {row.symbol: _raw(row) for row in rows}
    currency = account.currency or ""
    fx_loss: dict[str, Decimal | None] = {}
    for row in rows:
        if not is_cross_currency(row.currency_profit, currency):
            continue
        rate = rate_row(session, account.id, row.currency_profit, currency)
        fx_loss[row.symbol] = cross_loss_per_tick(
            account.id, row.symbol, row.tick_size, row.contract_size, rate, row.mt5_loss_per_tick
        )
    return specs, fx_loss
