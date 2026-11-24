"""cTrader closed and open positions -> trades, through the shared MT5 trade writer.

`app.ctrader.convert` turns the read into domain deals and position snapshots; from there
`app.services.trade_writer.write_trades` does exactly what it does for MT5 (build, upsert by
account + position_id, metrics, exit deals, exit reason, rules, bias alignment).

Risk (phase c): the batch carries the account's stored cTrader specs by broker name and the
FX loss per tick per lot of the cross-currency ones (`app.services.ctrader_specs.risk_inputs`,
written earlier in the same cycle), exactly as the MT5 sync passes them. So a closed trade
gets its risk from the realized P&L, and an open or breakeven trade from its initial SL and
the spec, like an MT5 trade; a cross-currency spec without a rate row gives no fallback risk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files.rules import RulesConfig
from app.config_files.symbols import SymbolsConfig
from app.ctrader.convert import StoredStops, convert
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.history import TradingRead
from app.domain.trade_builder import SkippedPosition
from app.models import Account, Trade
from app.services.ctrader_specs import risk_inputs
from app.services.trade_writer import TradeBatch, write_trades

logger = logging.getLogger(__name__)

_MAX_LISTED = 10


@dataclass(frozen=True)
class CtraderTradeResult:
    deals_read: int
    created: int
    updated: int
    open_positions: int
    skipped: tuple[SkippedPosition, ...]
    unconfirmed: tuple[int, ...]


def _ids(pids: list[int]) -> str:
    shown = ", ".join(str(pid) for pid in pids[:_MAX_LISTED])
    return shown + (f" (+{len(pids) - _MAX_LISTED})" if len(pids) > _MAX_LISTED else "")


def _stored_stops(session: Session, account_id: int) -> dict[int, StoredStops]:
    """last_sl / tp of the account's DB-open trades: a close must never wipe them."""
    rows = session.execute(
        select(Trade.position_id, Trade.last_sl, Trade.tp).where(
            Trade.account_id == account_id, Trade.close_time.is_(None)
        )
    )
    return {row.position_id: StoredStops(row.last_sl, row.tp) for row in rows}


def write_ctrader_trades(
    session: Session,
    account: Account,
    read: TradingRead,
    balance: Decimal,
    rules: RulesConfig,
    symbols: SymbolsConfig,
) -> CtraderTradeResult:
    """Persist one read (no commit). Raises ``history_incomplete`` before anything is written
    when a position that must have its entry deal in the read range lacks it: the read is
    then not trusted (no trade closed, no open trade created, the cursor does not move)."""
    converted = convert(read, _stored_stops(session, account.id))
    if converted.missing_entries:
        raise CtraderError(
            CtraderErrorCode.HISTORY_INCOMPLETE,
            f"deal history incomplete: no entry deal for position(s) "
            f"{_ids(converted.missing_entries)}",
        )
    if converted.before_range:
        logger.debug(
            "cTrader account %s: %s position(s) opened before the read range ignored: %s",
            account.id,
            len(converted.before_range),
            _ids(converted.before_range),
        )
    specs, fx_loss = risk_inputs(session, account)
    batch = TradeBatch(
        deals=converted.deals,
        position_ids=converted.position_ids,
        snapshots=converted.snapshots,
        balance=balance,
        currency=account.currency,
        specs=specs,
        fx_loss=fx_loss,
    )
    counts = write_trades(session, account, batch, rules, symbols)
    for skipped in converted.skipped:
        logger.warning(
            "cTrader account %s: position %s skipped: %s",
            account.id,
            skipped.position_id,
            skipped.reason,
        )
    if converted.unconfirmed:
        logger.warning(
            "cTrader account %s: %s open trade(s) not reported by cTrader and no close in the "
            "history yet (positions %s); kept open, retried next sync",
            account.id,
            len(converted.unconfirmed),
            _ids(converted.unconfirmed),
        )
    return CtraderTradeResult(
        deals_read=len(read.deals),
        created=counts.created,
        updated=counts.updated,
        open_positions=len(read.positions),
        skipped=(*converted.skipped, *counts.skipped),
        unconfirmed=tuple(converted.unconfirmed),
    )
