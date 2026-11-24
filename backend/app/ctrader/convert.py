"""cTrader records -> domain inputs of `app.domain.trade_builder` (pure, no I/O).

- A deal with ``closePositionDetail`` is an exit (``out``), any other executed deal an entry.
- Lots = cTrader volume / the symbol's ``lotSize`` (both in cTrader units). A position whose
  symbol has no known lot size, or whose volume is not an exact multiple, is skipped with a
  visible reason: a guessed lot count would be wrong everywhere it is shown.
- Money of a closed volume comes from its close detail: ``grossProfit``, ``swap``,
  ``commission`` (realized for the closed volume) and ``pnlConversionFee`` (as ``fee``). An
  entry deal carries no money: cTrader books the commission to the balance with the close, so
  taking the entry deal's commission as well would count it twice (DECISIONS 2026-11-24).
- Prices are quantized to the symbol's ``digits``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Context, Decimal, Inexact
from typing import Final

from app.ctrader.history import CtDeal, CtPosition, CtSymbol, TradingRead
from app.domain.trade_builder import (
    Deal,
    DealEntry,
    DealType,
    PositionSnapshot,
    SkippedPosition,
)
from app.mt5.convert import quantize_price

_EXACT: Final = Context(prec=40, traps=[Inexact])
ZERO: Final = Decimal(0)


@dataclass(frozen=True)
class Converted:
    deals: list[Deal]
    position_ids: set[int]  # positions to build: each has its entry deal(s) in ``deals``
    snapshots: dict[int, PositionSnapshot]  # open positions cTrader reports
    skipped: list[SkippedPosition]
    # Positions whose entry deal must be in the read range but is not: an incomplete read.
    missing_entries: list[int]
    # DB-open, not reported by cTrader, and not fully closed by the deals read.
    unconfirmed: list[int]
    # Exit deals of positions opened before the read range and not open in the DB.
    before_range: list[int]


def lots(volume: int, symbol: CtSymbol) -> Decimal | None:
    """Exact lots, or None when the lot size is unknown or does not divide the volume."""
    if symbol.lot_size is None or symbol.lot_size <= 0:
        return None
    try:
        return _EXACT.divide(Decimal(volume), Decimal(symbol.lot_size))
    except Inexact:
        return None


def _symbol_problem(symbol_id: int, symbols: Mapping[int, CtSymbol]) -> str | None:
    symbol = symbols.get(symbol_id)
    if symbol is None:
        return f"cTrader symbol {symbol_id} unknown"
    if symbol.lot_size is None or symbol.lot_size <= 0:
        return f"lot size of {symbol.name} unknown"
    return None


def _to_deal(deal: CtDeal, symbol: CtSymbol, volume: Decimal) -> Deal:
    close = deal.close
    return Deal(
        ticket=deal.deal_id,
        order=deal.order_id,
        position_id=deal.position_id,
        time=deal.time,
        type=DealType.BUY if deal.side == "buy" else DealType.SELL,
        entry=DealEntry.IN if close is None else DealEntry.OUT,
        volume=volume,
        price=quantize_price(deal.price, symbol.digits),
        profit=close.gross_profit if close is not None else ZERO,
        symbol=symbol.name,
        commission=close.commission if close is not None else ZERO,
        swap=close.swap if close is not None else ZERO,
        fee=close.fee if close is not None else ZERO,
    )


def _deal_volume(deal: CtDeal) -> int:
    if deal.close is not None and deal.close.closed_volume is not None:
        return deal.close.closed_volume
    return deal.volume


def _convert_position(deals: Iterable[CtDeal], symbols: Mapping[int, CtSymbol]) -> list[Deal] | str:
    """Domain deals of one position, or the reason it cannot be built."""
    out: list[Deal] = []
    for deal in deals:
        problem = _symbol_problem(deal.symbol_id, symbols)
        if problem is not None:
            return problem
        symbol = symbols[deal.symbol_id]
        volume = lots(_deal_volume(deal), symbol)
        if volume is None:
            return f"deal {deal.deal_id}: volume is not a whole number of {symbol.name} lots"
        out.append(_to_deal(deal, symbol, volume))
    return out


def _fully_closed(deals: Iterable[CtDeal]) -> bool:
    entered = closed = 0
    for deal in deals:
        if deal.close is None:
            entered += deal.volume
        else:
            closed += _deal_volume(deal)
    return entered > 0 and closed >= entered


def _snapshot(position: CtPosition, symbol: CtSymbol) -> PositionSnapshot:
    return PositionSnapshot(
        sl=quantize_price(position.sl, symbol.digits) if position.sl is not None else None,
        tp=quantize_price(position.tp, symbol.digits) if position.tp is not None else None,
        volume=lots(position.volume, symbol),
    )


def _missing_entries(read: TradingRead, with_entry: set[int]) -> list[int]:
    """DB-open trades and open positions opened inside the read range need their entry."""
    opened = dict(read.request.open_trades)
    opened.update((pos.position_id, pos.open_time) for pos in read.positions)
    return sorted(
        pid
        for pid, at in opened.items()
        if read.read_from <= at <= read.read_to and pid not in with_entry
    )


def convert(read: TradingRead) -> Converted:
    by_position: dict[int, list[CtDeal]] = defaultdict(list)
    for deal in read.deals:
        by_position[deal.position_id].append(deal)
    with_entry = {pid for pid, own in by_position.items() if any(d.close is None for d in own)}
    db_open = set(read.request.open_trades)
    live = {pos.position_id: pos for pos in read.positions}

    deals: list[Deal] = []
    skipped: list[SkippedPosition] = []
    built: set[int] = set()
    before_range: list[int] = []
    for pid in sorted(by_position):
        if pid not in with_entry:
            if pid in db_open:
                skipped.append(SkippedPosition(pid, "entry deal before the history read range"))
            else:
                before_range.append(pid)
            continue
        result = _convert_position(by_position[pid], read.symbols)
        if isinstance(result, str):
            skipped.append(SkippedPosition(pid, result))
            continue
        deals.extend(result)
        built.add(pid)

    snapshots = {
        pid: _snapshot(pos, read.symbols[pos.symbol_id])
        for pid, pos in live.items()
        if pid in built
    }
    unconfirmed = sorted(
        pid for pid in db_open - set(live) if not _fully_closed(by_position.get(pid, ()))
    )
    deals.sort(key=lambda d: (d.time, d.ticket))
    return Converted(
        deals=deals,
        position_ids=built,
        snapshots=snapshots,
        skipped=skipped,
        missing_entries=_missing_entries(read, with_entry),
        unconfirmed=unconfirmed,
        before_range=before_range,
    )
