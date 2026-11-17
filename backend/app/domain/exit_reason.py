"""Exit reason prefill from MT5 closing deals (M8-09, DECISIONS 2026-11-17).

Primary source is the MT5 DEAL_REASON of the trade's final closing deal: SL -> ``sl``,
TP -> ``tp``, stop-out -> ``stop_out``. A manual close (client / mobile / web / expert) is
left for the owner: it may be a fractal update or the point B target. Only when MT5 reported
no deal reason at all is the final deal's price compared with the initial SL / TP, within
one tick. Any other reason (rollover, split, ``unknown_<n>``, ...) and no match stay empty.

A value the owner entered, changed or cleared is never overwritten; neither is a value
that existed before M8-09 (no source recorded).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.models.enums import ExitReasonSource

# exit_reason option values (config/journal_fields.yaml).
EXIT_SL = "sl"
EXIT_TP = "tp"
EXIT_STOP_OUT = "stop_out"

# Lowercase DEAL_REASON keys (app.domain.trade_builder) -> exit_reason option.
_BY_DEAL_REASON = {"sl": EXIT_SL, "tp": EXIT_TP, "so": EXIT_STOP_OUT}
AUTO_SOURCES = frozenset({ExitReasonSource.MT5_REASON.value, ExitReasonSource.PRICE_MATCH.value})


class ClosingDeal(Protocol):
    """An exit deal: the domain `ExitDeal` or the stored `TradeExitDeal` row."""

    @property
    def ticket(self) -> int: ...
    @property
    def time(self) -> datetime: ...
    @property
    def price(self) -> Decimal: ...
    @property
    def reason(self) -> str | None: ...


@dataclass(frozen=True)
class ExitReasonSuggestion:
    value: str
    source: ExitReasonSource


def final_deal[D: ClosingDeal](deals: Sequence[D]) -> D | None:
    """Last closing deal by (time, ticket); None without deals."""
    return max(deals, key=lambda d: (d.time, d.ticket), default=None)


def _stop(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value != 0 else None


def _near(price: Decimal, stop: Decimal | None, tick: Decimal) -> bool:
    return stop is not None and abs(price - stop) <= tick


def _price_match(
    price: Decimal, initial_sl: Decimal | None, tp: Decimal | None, tick_size: Decimal | None
) -> str | None:
    if tick_size is None or tick_size <= 0:
        return None
    at_sl = _near(price, _stop(initial_sl), tick_size)
    at_tp = _near(price, _stop(tp), tick_size)
    if at_sl == at_tp:  # neither, or both (ambiguous)
        return None
    return EXIT_SL if at_sl else EXIT_TP


def suggest_exit_reason(
    deals: Sequence[ClosingDeal],
    *,
    initial_sl: Decimal | None,
    tp: Decimal | None,
    tick_size: Decimal | None,
) -> ExitReasonSuggestion | None:
    """Prefill for a closed trade from its exit deals; None = leave it for the owner."""
    last = final_deal(deals)
    if last is None:
        return None
    reason = last.reason
    if reason in _BY_DEAL_REASON:
        return ExitReasonSuggestion(_BY_DEAL_REASON[reason], ExitReasonSource.MT5_REASON)
    if reason is not None:  # manual close or another reported reason: the owner decides
        return None
    matched = _price_match(last.price, initial_sl, tp, tick_size)
    if matched is None:
        return None
    return ExitReasonSuggestion(matched, ExitReasonSource.PRICE_MATCH)


def resolve_prefill(
    current_value: str | None,
    current_source: str | None,
    suggestion: ExitReasonSuggestion | None,
) -> tuple[str | None, str | None] | None:
    """New (exit_reason, exit_reason_source) the sync may write; None = leave unchanged.

    A prefilled value follows a new suggestion but is never cleared (a later sync without
    the symbol spec must not erase a price match); an empty value without source is
    filled; owner values and pre-M8-09 values stay.
    """
    if suggestion is None:
        return None
    if current_source in AUTO_SOURCES:
        return suggestion.value, suggestion.source.value
    if current_source is None and current_value is None:
        return suggestion.value, suggestion.source.value
    return None


def source_after_owner_save(
    old_value: str | None, new_value: str | None, old_source: str | None
) -> str | None:
    """Journal save: a changed (or cleared) value is the owner's; unchanged keeps its source."""
    if new_value != old_value:
        return ExitReasonSource.OWNER.value
    return old_source
