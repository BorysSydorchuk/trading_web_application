"""Cross-currency loss value helpers (docs/api.md "M5-09 Cross-currency loss value").

Pure Decimal functions; no MT5 or DB access. For a spec whose profit currency differs from
the account currency, the loss per tick per lot in account currency is
``tick_size * contract_size * rate`` with rate = profit currency -> account currency from the
conversion pair's latest tick: direct pair ask, inverse pair 1 / bid (the higher price, so the
larger, conservative loss). An optional MT5 ``order_calc_profit`` check wins when it differs
from the rate value by more than ``CHECK_TOLERANCE``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Literal

STALE_AFTER = timedelta(hours=1)
CHECK_TOLERANCE = Decimal("0.005")
CHECK_MOVE_RATIO = Decimal("0.01")

QuoteSide = Literal["ask", "bid"]
LossSource = Literal["rate", "mt5_check"]


@dataclass(frozen=True)
class ConversionPair:
    """Broker symbol converting profit -> account currency; ``inverted`` = ``<A><P>``.

    ``candidates``: every prefix-matched broker symbol that qualified (sorted, ``pair`` first);
    empty for an exact name match. More than one = ambiguous (the sync logs a WARNING).
    """

    pair: str
    inverted: bool
    side: QuoteSide
    candidates: tuple[str, ...] = field(default=(), compare=False)


def is_cross_currency(profit_currency: str, account_currency: str) -> bool:
    """Case-insensitive; a blank currency on either side is never cross-currency."""
    profit, account = profit_currency.strip().upper(), account_currency.strip().upper()
    return bool(profit) and bool(account) and profit != account


def _require_positive(value: Decimal, name: str) -> None:
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive finite number, got {value}")


def loss_per_tick_from_rate(tick_size: Decimal, contract_size: Decimal, rate: Decimal) -> Decimal:
    """Account-currency loss per tick per lot: ``tick_size * contract_size * rate``."""
    _require_positive(tick_size, "tick_size")
    _require_positive(contract_size, "contract_size")
    _require_positive(rate, "rate")
    return tick_size * contract_size * rate


def _is_suffixed(name: str, wanted: str) -> bool:
    """``name`` is ``wanted`` plus a broker suffix that starts with a non-letter (EURUSD.r,
    EURUSD#, EURUSD2), so EURUSDT is not EURUSD."""
    upper = name.upper()
    if not upper.startswith(wanted) or len(upper) == len(wanted):
        return False
    return not upper[len(wanted)].isalpha()


def _find_symbol(name: str, sorted_names: list[str]) -> tuple[str, tuple[str, ...]] | None:
    """(symbol, prefix candidates): exact name (case-insensitive) first with no candidates,
    else the first sorted name that is ``name`` plus a non-letter suffix."""
    wanted = name.upper()
    exact = next((n for n in sorted_names if n.upper() == wanted), None)
    if exact is not None:
        return exact, ()
    candidates = tuple(n for n in sorted_names if _is_suffixed(n, wanted))
    return (candidates[0], candidates) if candidates else None


def pick_conversion_pair(
    profit_currency: str, account_currency: str, broker_symbols: Iterable[str]
) -> ConversionPair | None:
    """Direct ``<P><A>`` (rate = ask), else inverse ``<A><P>`` (rate = 1 / bid), else None."""
    names = sorted(broker_symbols)
    direct = _find_symbol(profit_currency + account_currency, names)
    if direct is not None:
        return ConversionPair(pair=direct[0], inverted=False, side="ask", candidates=direct[1])
    inverse = _find_symbol(account_currency + profit_currency, names)
    if inverse is not None:
        return ConversionPair(pair=inverse[0], inverted=True, side="bid", candidates=inverse[1])
    return None


def conversion_rate(pair: ConversionPair, *, bid: Decimal, ask: Decimal) -> Decimal:
    """Profit -> account currency rate: ask of a direct pair, 1 / bid of an inverse pair."""
    if pair.inverted:
        _require_positive(bid, "bid")
        return Decimal(1) / bid
    _require_positive(ask, "ask")
    return ask


def check_tick_count(price: Decimal, tick_size: Decimal) -> int:
    """Ticks in a 1 % price move, floored (the order_calc_profit check distance)."""
    _require_positive(price, "price")
    _require_positive(tick_size, "tick_size")
    return int((price * CHECK_MOVE_RATIO / tick_size).to_integral_value(rounding=ROUND_FLOOR))


def check_loss_per_tick(result: Decimal, ticks: int) -> Decimal:
    """Loss per tick per lot from an order_calc_profit result over ``ticks`` ticks at 1 lot."""
    if ticks <= 0:
        raise ValueError(f"tick count must be positive, got {ticks}")
    return result.copy_abs() / ticks


def choose_loss_per_tick(
    rate_value: Decimal, mt5_value: Decimal | None
) -> tuple[Decimal, LossSource]:
    """The MT5 check wins only when it differs from the rate value by > 0.5 % of it."""
    if mt5_value is None:
        return rate_value, "rate"
    if abs(mt5_value - rate_value) > CHECK_TOLERANCE * rate_value:
        return mt5_value, "mt5_check"
    return rate_value, "rate"


def is_stale(rate_at: datetime, now: datetime) -> bool:
    """Strictly older than ``STALE_AFTER`` (exactly one hour is not stale)."""
    return now - rate_at > STALE_AFTER
