"""Raw MT5 records -> domain inputs of `app.domain.trade_builder`, with server time -> UTC.

This is the only place where MT5 server wall-clock epochs become UTC datetimes (PRD 6.3).
The ``Conversion`` comes from `app.domain.broker_time.choose_conversion`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.domain.broker_time import (
    Conversion,
    server_msc_to_wall,
    server_to_utc,
    utc_to_server,
)
from app.domain.trade_builder import (
    Deal,
    OrderStops,
    PositionSnapshot,
    deal_entry_from_mt5,
    deal_reason_from_mt5,
    deal_type_from_mt5,
)
from app.mt5.types import RawDeal, RawOrder, RawPosition, RawSymbolSpec

# History query bounds are widened by this much so a DST switch inside the window
# (offset changes by 1 h) can never drop a deal at the edge. Upserts are idempotent.
RANGE_PAD = timedelta(hours=1)


def deal_time_utc(raw: RawDeal, conversion: Conversion) -> datetime:
    """Aware UTC time of a deal; uses ``time_msc`` (ms precision) when MT5 provides it."""
    wall = server_msc_to_wall(raw.time_msc) if raw.time_msc else None
    return server_to_utc(wall if wall is not None else raw.time, conversion)


def quantize_price(value: Decimal, digits: int | None) -> Decimal:
    """Round a price to the symbol's digits (removes float noise); unchanged if unknown."""
    if digits is None or digits < 0:
        return value
    return value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def _opt_price(value: Decimal | None, digits: int | None) -> Decimal | None:
    return None if value is None else quantize_price(value, digits)


def digits_by_symbol(specs: Iterable[RawSymbolSpec]) -> dict[str, int]:
    return {s.name: s.digits for s in specs}


def to_deal(raw: RawDeal, conversion: Conversion, digits: Mapping[str, int] | None = None) -> Deal:
    """Raw deal -> domain `Deal` (UTC time, enum codes mapped, prices at symbol digits).

    Raises ValueError (with the deal ticket) for an unknown deal entry code.
    """
    sym_digits = (digits or {}).get(raw.symbol)
    try:
        entry = deal_entry_from_mt5(raw.entry)
    except ValueError as exc:
        raise ValueError(f"deal {raw.ticket}: {exc}") from None
    return Deal(
        ticket=raw.ticket,
        order=raw.order,
        position_id=raw.position_id,
        time=deal_time_utc(raw, conversion),
        type=deal_type_from_mt5(raw.type),
        entry=entry,
        volume=raw.volume,
        price=quantize_price(raw.price, sym_digits),
        profit=raw.profit,
        symbol=raw.symbol,
        commission=raw.commission,
        swap=raw.swap,
        fee=raw.fee,
        reason=deal_reason_from_mt5(raw.reason),
        sl=_opt_price(raw.sl, sym_digits),
        tp=_opt_price(raw.tp, sym_digits),
        magic=raw.magic,
    )


def to_deals(
    raws: Iterable[RawDeal], conversion: Conversion, digits: Mapping[str, int] | None = None
) -> list[Deal]:
    """Convert and de-duplicate by ticket (a deal may come from both window and position)."""
    by_ticket = {r.ticket: r for r in raws}
    deals = [to_deal(r, conversion, digits) for r in by_ticket.values()]
    deals.sort(key=lambda d: (d.time, d.ticket))
    return deals


def order_stops(raw: RawOrder, digits: Mapping[str, int] | None = None) -> OrderStops:
    """SL/TP of an order; 0 (unset in MT5) is kept as-is, the domain treats it as None."""
    sym_digits = (digits or {}).get(raw.symbol)
    return OrderStops(sl=quantize_price(raw.sl, sym_digits), tp=quantize_price(raw.tp, sym_digits))


def position_snapshots(
    raws: Iterable[RawPosition], digits: Mapping[str, int] | None = None
) -> dict[int, PositionSnapshot]:
    """Open positions keyed by position id (``identifier``), as `build_trades` expects."""
    out: dict[int, PositionSnapshot] = {}
    for raw in raws:
        sym_digits = (digits or {}).get(raw.symbol)
        out[raw.identifier] = PositionSnapshot(
            sl=quantize_price(raw.sl, sym_digits),
            tp=quantize_price(raw.tp, sym_digits),
            volume=raw.volume,
        )
    return out


def server_epoch(wall: datetime) -> int:
    """Naive server wall datetime -> MT5 epoch seconds (wall read as UTC)."""
    if wall.tzinfo is not None:
        raise ValueError("server wall time must be naive")
    return int(wall.replace(tzinfo=UTC).timestamp())


def server_epoch_range(
    from_utc: datetime, to_utc: datetime, conversion: Conversion, pad: timedelta = RANGE_PAD
) -> tuple[int, int]:
    """UTC window -> (from, to) server epochs for `Mt5Source.deals`, padded by ``pad``."""
    if to_utc < from_utc:
        raise ValueError("to_utc is before from_utc")
    start = utc_to_server(from_utc, conversion) - pad
    end = utc_to_server(to_utc, conversion) + pad
    return server_epoch(start), server_epoch(end)
