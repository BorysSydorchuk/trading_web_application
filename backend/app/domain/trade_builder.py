"""Build trades from MT5 deals, one per position (PRD 6.2, 6.4; DECISIONS 2026-11-01).

Input deals must already carry UTC times (see ``broker_time``) and should contain *all*
trade deals of each position (fetch by position, not only the sync window); positions whose
deals are incomplete or inconsistent are returned in ``BuildResult.skipped`` with a reason.

Conventions:
- Only ``buy``/``sell`` deals are trade deals; balance, credit, commission-only, etc. are
  ignored here (they still count in ``metrics.balance_at_open``).
- ``fee`` is folded into ``commission`` (the schema has no fee column).
- ``out_by`` (close-by in hedging) is treated exactly like ``out``.
- ``inout`` (netting reversal) is not supported: FundedNext accounts are hedging, and on a
  netting reversal MT5 keeps the position id, so old and new trade would share one key. Any
  position containing an ``inout`` deal is returned in ``skipped``.
- Entry/exit prices are volume-weighted over entry/exit deals (8 dp). With netting scale-ins
  between partial exits this is an approximation of MT5's running position price.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.models.enums import Direction, InitialSlSource, TradeStatus

PRICE_Q = Decimal("0.00000001")
MONEY_Q = Decimal("0.01")
ZERO = Decimal(0)
NETTING_REVERSAL = "netting reversal (inout) not supported"


class DealType(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"
    BALANCE = "balance"
    CREDIT = "credit"
    CHARGE = "charge"
    CORRECTION = "correction"
    BONUS = "bonus"
    COMMISSION = "commission"
    COMMISSION_DAILY = "commission_daily"
    COMMISSION_MONTHLY = "commission_monthly"
    COMMISSION_AGENT_DAILY = "commission_agent_daily"
    COMMISSION_AGENT_MONTHLY = "commission_agent_monthly"
    INTEREST = "interest"
    BUY_CANCELED = "buy_canceled"
    SELL_CANCELED = "sell_canceled"
    DIVIDEND = "dividend"
    DIVIDEND_FRANKED = "dividend_franked"
    TAX = "tax"
    UNKNOWN = "unknown"


class DealEntry(enum.StrEnum):
    IN = "in"
    OUT = "out"
    INOUT = "inout"
    OUT_BY = "out_by"


# Index = MT5 numeric code (ENUM_DEAL_TYPE, ENUM_DEAL_ENTRY, ENUM_DEAL_REASON).
_MT5_DEAL_TYPES = tuple(t for t in DealType if t is not DealType.UNKNOWN)
_MT5_DEAL_ENTRIES = (DealEntry.IN, DealEntry.OUT, DealEntry.INOUT, DealEntry.OUT_BY)
_MT5_DEAL_REASONS = (
    "client",
    "mobile",
    "web",
    "expert",
    "sl",
    "tp",
    "so",
    "rollover",
    "vmargin",
    "split",
    "corporate_action",
)


def deal_type_from_mt5(code: int) -> DealType:
    return _MT5_DEAL_TYPES[code] if 0 <= code < len(_MT5_DEAL_TYPES) else DealType.UNKNOWN


def deal_entry_from_mt5(code: int) -> DealEntry:
    if not 0 <= code < len(_MT5_DEAL_ENTRIES):
        raise ValueError(f"unknown MT5 deal entry code: {code}")
    return _MT5_DEAL_ENTRIES[code]


def deal_reason_from_mt5(code: int) -> str:
    """Lowercase DEAL_REASON key; unknown codes become ``unknown_<code>`` (never fail)."""
    return _MT5_DEAL_REASONS[code] if 0 <= code < len(_MT5_DEAL_REASONS) else f"unknown_{code}"


@dataclass(frozen=True)
class Deal:
    """The MT5 TradeDeal fields we use. ``time`` is aware UTC. sl/tp 0 means "not set"."""

    ticket: int
    order: int
    position_id: int
    time: datetime
    type: DealType
    entry: DealEntry
    volume: Decimal
    price: Decimal
    profit: Decimal
    symbol: str
    commission: Decimal = ZERO
    swap: Decimal = ZERO
    fee: Decimal = ZERO
    reason: str | None = None
    sl: Decimal | None = None
    tp: Decimal | None = None
    magic: int = 0


@dataclass(frozen=True)
class OrderStops:
    """SL/TP of an opening order (history_orders_get), keyed by order ticket."""

    sl: Decimal | None = None
    tp: Decimal | None = None


@dataclass(frozen=True)
class PositionSnapshot:
    """Currently open position (positions_get), keyed by position identifier."""

    sl: Decimal | None = None
    tp: Decimal | None = None
    volume: Decimal | None = None


@dataclass(frozen=True)
class ExitDeal:
    ticket: int
    time: datetime
    price: Decimal
    volume: Decimal
    profit: Decimal
    commission: Decimal  # includes fee
    swap: Decimal
    reason: str | None


@dataclass(frozen=True)
class BuiltTrade:
    position_id: int
    symbol: str
    direction: Direction
    open_time: datetime
    close_time: datetime | None  # None while net volume != 0
    duration_seconds: int | None
    entry_price: Decimal
    exit_price: Decimal | None
    volume: Decimal  # total entered
    open_volume: Decimal  # still open (0 when closed)
    exit_volume: Decimal  # total closed so far
    commission: Decimal  # commission + fee of all deals, incl. entry
    swap: Decimal
    gross_pnl: Decimal  # realised profit so far
    net_pnl: Decimal  # gross + commission + swap
    exit_deals: tuple[ExitDeal, ...]
    initial_sl: Decimal | None
    initial_sl_source: InitialSlSource | None
    last_sl: Decimal | None
    tp: Decimal | None

    @property
    def is_closed(self) -> bool:
        return self.close_time is not None


@dataclass(frozen=True)
class SkippedPosition:
    position_id: int
    reason: str


@dataclass(frozen=True)
class BuildResult:
    trades: list[BuiltTrade]
    skipped: list[SkippedPosition]


def _stop(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value != 0 else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


@dataclass
class _Acc:
    key: int
    symbol: str
    direction: Direction
    open_time: datetime
    opening_deal: Deal
    entries: list[tuple[Decimal, Decimal]] = field(default_factory=list)  # (volume, price)
    exits: list[ExitDeal] = field(default_factory=list)
    net: Decimal = ZERO
    commission: Decimal = ZERO
    swap: Decimal = ZERO
    gross: Decimal = ZERO
    close_time: datetime | None = None
    last_deal_sl: Decimal | None = None
    last_deal_tp: Decimal | None = None
    error: str | None = None

    def add_entry(self, volume: Decimal, price: Decimal) -> None:
        self.entries.append((volume, price))
        self.net += volume

    def add_exit(
        self, deal: Deal, volume: Decimal, commission: Decimal, swap: Decimal, profit: Decimal
    ) -> None:
        if volume > self.net:
            self.error = f"deal {deal.ticket} closes {volume} but only {self.net} is open"
            return
        self.exits.append(
            ExitDeal(
                deal.ticket, deal.time, deal.price, volume, profit, commission, swap, deal.reason
            )
        )
        self.net -= volume
        self.commission += commission
        self.swap += swap
        self.gross += profit
        if self.net == 0:
            self.close_time = deal.time

    def note_stops(self, deal: Deal) -> None:
        if _stop(deal.sl) is not None:
            self.last_deal_sl = deal.sl
        if _stop(deal.tp) is not None:
            self.last_deal_tp = deal.tp


def _vwap(parts: Iterable[tuple[Decimal, Decimal]]) -> Decimal | None:
    total_volume = ZERO
    total_value = ZERO
    for volume, price in parts:
        total_volume += volume
        total_value += volume * price
    if total_volume == 0:
        return None
    return (total_value / total_volume).quantize(PRICE_Q, rounding=ROUND_HALF_UP)


def _direction(deal_type: DealType) -> Direction:
    return Direction.BUY if deal_type is DealType.BUY else Direction.SELL


def build_trades(
    deals: Iterable[Deal],
    opening_orders: Mapping[int, OrderStops] | None = None,
    positions: Mapping[int, PositionSnapshot] | None = None,
    first_seen_sl: Mapping[int, Decimal] | None = None,
) -> BuildResult:
    """Group trade deals into trades.

    ``opening_orders`` is keyed by order ticket, ``positions`` (open positions) and
    ``first_seen_sl`` (first SL the worker saw on the open position) by position id.
    """
    orders = opening_orders or {}
    open_positions = positions or {}
    seen_sl = first_seen_sl or {}

    accs: dict[int, _Acc] = {}
    orphan: dict[int, str] = {}

    trade_deals = sorted(
        (d for d in deals if d.type in (DealType.BUY, DealType.SELL)),
        key=lambda d: (d.time, d.ticket),
    )
    for deal in trade_deals:
        if deal.entry is DealEntry.INOUT:
            orphan[deal.position_id] = NETTING_REVERSAL
    for deal in trade_deals:
        key = deal.position_id
        if key in orphan:
            continue
        acc = accs.get(key)
        if acc is not None and acc.error is not None:
            continue
        commission = deal.commission + deal.fee

        if deal.entry is DealEntry.IN:
            if acc is None:
                acc = _Acc(key, deal.symbol, _direction(deal.type), deal.time, deal)
                accs[key] = acc
            elif acc.close_time is not None:
                acc.error = f"entry deal {deal.ticket} after the position was closed"
                continue
            elif _direction(deal.type) is not acc.direction:
                acc.error = f"entry deal {deal.ticket} has the opposite direction"
                continue
            acc.add_entry(deal.volume, deal.price)
            acc.commission += commission
            acc.swap += deal.swap
            acc.gross += deal.profit
            acc.note_stops(deal)
            continue

        if acc is None:
            orphan[key] = f"exit deal {deal.ticket} without an entry deal in the input"
            continue
        if acc.close_time is not None:
            acc.error = f"exit deal {deal.ticket} after the position was closed"
            continue

        # OUT or OUT_BY (INOUT positions were skipped above).
        acc.add_exit(deal, deal.volume, commission, deal.swap, deal.profit)
        acc.note_stops(deal)

    trades: list[BuiltTrade] = []
    skipped = [SkippedPosition(pid, reason) for pid, reason in orphan.items()]
    for acc in accs.values():
        if acc.error is not None:
            skipped.append(SkippedPosition(acc.key, acc.error))
            continue
        trades.append(
            _finish(
                acc,
                orders.get(acc.opening_deal.order),
                open_positions.get(acc.key),
                seen_sl.get(acc.key),
            )
        )
    trades.sort(key=lambda t: (t.open_time, t.position_id))
    skipped.sort(key=lambda s: s.position_id)
    return BuildResult(trades, skipped)


def _finish(
    acc: _Acc,
    order: OrderStops | None,
    position: PositionSnapshot | None,
    first_seen_sl: Decimal | None,
) -> BuiltTrade:
    entry_price = _vwap(acc.entries)
    if entry_price is None:  # pragma: no cover - an _Acc always starts with an entry
        raise ValueError(f"position {acc.key} has no entry volume")
    exit_price = _vwap((e.volume, e.price) for e in acc.exits)
    exit_volume = sum((e.volume for e in acc.exits), ZERO)

    initial_sl, sl_source = initial_stop_loss(acc.opening_deal, order, first_seen_sl)
    order_tp = order.tp if order is not None else None
    position_tp = position.tp if position is not None else None
    tp = _stop(acc.opening_deal.tp) or _stop(order_tp) or _stop(position_tp) or acc.last_deal_tp
    position_sl = position.sl if position is not None and acc.close_time is None else None
    last_sl = _stop(position_sl) or acc.last_deal_sl or initial_sl

    duration = (
        int((acc.close_time - acc.open_time).total_seconds())
        if acc.close_time is not None
        else None
    )
    commission = _money(acc.commission)
    swap = _money(acc.swap)
    gross = _money(acc.gross)
    return BuiltTrade(
        position_id=acc.key,
        symbol=acc.symbol,
        direction=acc.direction,
        open_time=acc.open_time,
        close_time=acc.close_time,
        duration_seconds=duration,
        entry_price=entry_price,
        exit_price=exit_price,
        volume=sum((v for v, _ in acc.entries), ZERO),
        open_volume=acc.net,
        exit_volume=exit_volume,
        commission=commission,
        swap=swap,
        gross_pnl=gross,
        net_pnl=gross + commission + swap,
        exit_deals=tuple(acc.exits),
        initial_sl=initial_sl,
        initial_sl_source=sl_source,
        last_sl=last_sl,
        tp=tp,
    )


def initial_stop_loss(
    opening_deal: Deal, order: OrderStops | None, first_seen_sl: Decimal | None
) -> tuple[Decimal | None, InitialSlSource | None]:
    """Opening deal sl -> opening order sl -> first SL seen on the position -> None."""
    if (sl := _stop(opening_deal.sl)) is not None:
        return sl, InitialSlSource.DEAL
    if order is not None and (sl := _stop(order.sl)) is not None:
        return sl, InitialSlSource.ORDER
    if (sl := _stop(first_seen_sl)) is not None:
        return sl, InitialSlSource.POSITION
    return None, None


def next_status(
    current: TradeStatus | str | None, *, is_closed: bool, has_initial_sl: bool
) -> TradeStatus:
    """Status after a sync. Never downgrades draft/complete.

    open position -> open; closed without SL -> needs_sl; closed with SL -> needs_description.
    """
    if current is not None:
        current = TradeStatus(current)
        if current in (TradeStatus.DRAFT, TradeStatus.COMPLETE):
            return current
    if not is_closed:
        return TradeStatus.OPEN
    return TradeStatus.NEEDS_DESCRIPTION if has_initial_sl else TradeStatus.NEEDS_SL
