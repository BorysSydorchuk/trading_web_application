"""Trade metrics (PRD 6.4; DECISIONS 2026-11-01). Decimal only; None when inputs are missing.

Rounding: money 2 dp, ratios/percent/R 4 dp, ROUND_HALF_UP. Percent values are in percent
units (0.5605 means 0.5605 %). Ratios are computed from the already-rounded money values so
stored numbers are consistent with each other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from app.domain.sessions import DEFAULT_TZ, to_local

MONEY_Q = Decimal("0.01")
RATIO_Q = Decimal("0.0001")
HUNDRED = Decimal(100)
# Below this |exit - entry| / |entry - SL| the realised conversion is too noisy (profit is
# rounded to 2 dp), so the tick_value fallback is preferred when a spec is available.
MIN_REALISED_MOVE_RATIO = Decimal("0.1")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def ratio(value: Decimal) -> Decimal:
    return value.quantize(RATIO_Q, rounding=ROUND_HALF_UP)


class BalanceDeal(Protocol):
    """Any deal (trade, balance, credit, commission...) that changed the balance."""

    @property
    def time(self) -> datetime: ...
    @property
    def profit(self) -> Decimal: ...
    @property
    def commission(self) -> Decimal: ...
    @property
    def swap(self) -> Decimal: ...
    @property
    def fee(self) -> Decimal: ...


def balance_at_open(
    current_balance: Decimal | None, open_time: datetime, deals: Iterable[BalanceDeal]
) -> Decimal | None:
    """Current balance - Σ(profit + commission + swap + fee) of all deals at/after open_time.

    ``deals`` must cover every balance-changing deal from ``open_time`` until the moment
    ``current_balance`` was read, including deposits/withdrawals (type balance).
    """
    if current_balance is None:
        return None
    delta = sum(
        (d.profit + d.commission + d.swap + d.fee for d in deals if d.time >= open_time),
        Decimal(0),
    )
    return money(current_balance - delta)


def risk_amount(
    *,
    entry_price: Decimal | None,
    initial_sl: Decimal | None,
    volume: Decimal | None,
    exit_price: Decimal | None = None,
    exit_volume: Decimal | None = None,
    gross_pnl: Decimal | None = None,
    tick_size: Decimal | None = None,
    tick_value: Decimal | None = None,
) -> Decimal | None:
    """Money at risk from the initial SL, in account currency.

    Realised conversion (exact, no FX rates): the trade's own P&L per price unit per lot,
    ``|gross| / (|exit - entry| * exit_volume)``, times ``|entry - SL| * volume``. For a fully
    closed trade this is ``|gross| * |entry - SL| / |exit - entry|``.
    Fallback ``|entry - SL| / tick_size * tick_value * volume`` from symbol specs when nothing
    was realised at a different price (breakeven, still open), and also when
    ``|exit - entry| < MIN_REALISED_MOVE_RATIO * |entry - SL|`` and a spec is available
    (if no spec, the realised formula is still used in that case).
    """
    if entry_price is None or initial_sl is None or volume is None or volume <= 0:
        return None
    distance = abs(entry_price - initial_sl)
    if distance == 0:
        return money(Decimal(0))
    has_spec = tick_size is not None and tick_value is not None and tick_size > 0 and tick_value > 0
    if (
        exit_price is not None
        and exit_volume is not None
        and exit_volume > 0
        and gross_pnl is not None
        and gross_pnl != 0
        and exit_price != entry_price
    ):
        move = abs(exit_price - entry_price)
        if not (has_spec and move < MIN_REALISED_MOVE_RATIO * distance):
            per_unit = abs(gross_pnl) / (move * exit_volume)
            return money(per_unit * distance * volume)
    if not has_spec or tick_size is None or tick_value is None:
        return None
    return money(distance / tick_size * tick_value * volume)


def _pct(amount: Decimal | None, balance: Decimal | None) -> Decimal | None:
    if amount is None or balance is None or balance <= 0:
        return None
    return ratio(amount / balance * HUNDRED)


def risk_pct(risk: Decimal | None, balance_open: Decimal | None) -> Decimal | None:
    return _pct(risk, balance_open)


def pnl_pct(net_pnl: Decimal | None, balance_open: Decimal | None) -> Decimal | None:
    return _pct(net_pnl, balance_open)


def r_multiple(net_pnl: Decimal | None, risk: Decimal | None) -> Decimal | None:
    """Net P&L (commission and swap included) / risk amount."""
    if net_pnl is None or risk is None or risk <= 0:
        return None
    return ratio(net_pnl / risk)


def planned_rr(
    entry_price: Decimal | None, initial_sl: Decimal | None, tp: Decimal | None
) -> Decimal | None:
    """|TP - entry| / |entry - SL|; None without TP or SL."""
    if entry_price is None or initial_sl is None or tp is None or tp == 0:
        return None
    distance = abs(entry_price - initial_sl)
    if distance == 0:
        return None
    return ratio(abs(tp - entry_price) / distance)


@dataclass(frozen=True)
class ReentryCandidate:
    key: int  # caller's id (trade id or position id)
    account_id: int
    symbol: str
    direction: str
    session: str | None
    open_time: datetime
    close_time: datetime | None
    net_pnl: Decimal | None


def reentry_flags(trades: Iterable[ReentryCandidate], tz: str = DEFAULT_TZ) -> Mapping[int, bool]:
    """Re-entry = same account, symbol, direction, local day and session, opened after an
    earlier trade of that idea closed (close_time <= open_time) with net P&L < 0.
    Trades without a session are never re-entries.
    """
    items = list(trades)
    flags: dict[int, bool] = {}
    for trade in items:
        flags[trade.key] = trade.session is not None and any(
            _same_idea(trade, other, tz)
            and other.close_time is not None
            and other.close_time <= trade.open_time
            and other.net_pnl is not None
            and other.net_pnl < 0
            for other in items
            if other.key != trade.key
        )
    return flags


def _same_idea(a: ReentryCandidate, b: ReentryCandidate, tz: str) -> bool:
    return (
        a.account_id == b.account_id
        and a.symbol == b.symbol
        and a.direction == b.direction
        and a.session == b.session
        and to_local(a.open_time, tz).date() == to_local(b.open_time, tz).date()
    )
