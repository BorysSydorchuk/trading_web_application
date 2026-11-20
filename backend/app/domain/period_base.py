"""The one percent base of a period P&L (PM 2026-11-20; docs/api.md "M8-10b fixes").

Pure, Decimal. Used by «Головна» (KPIs, limits), the Home charts and the digest metrics, so
every "% of the period" in the app divides by the same number:

- one account selected -> its ``reference_balance``;
- all accounts -> the sum of the ``reference_balance`` of the accounts with at least one
  closed trade in the period, M8-01 excluded trades INCLUDED (an account whose only trade
  of the period is excluded still counts); no such account -> None, unless
  ``fallback_to_all`` (Home today KPI: every selected account);
- any counted size that is missing, not finite or <= 0 -> None (no percent, never a 500).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

ZERO = Decimal(0)


def _usable(size: Decimal | None) -> bool:
    return size is not None and size.is_finite() and size > 0


def period_base(
    sizes: Mapping[int, Decimal],
    traded: Iterable[int],
    *,
    account_id: int | None = None,
    fallback_to_all: bool = False,
) -> Decimal | None:
    """Percent base of a period.

    ``sizes``: account id -> reference_balance of the accounts in scope (the selected
    account, or every non-archived / active account). ``traded``: ids of the accounts with a
    closed trade in the period, excluded trades included. ``account_id``: the one selected
    account (its size, whatever it traded).
    """
    if account_id is not None:
        size = sizes.get(account_id)
        return size if size is not None and _usable(size) else None
    counted = set(traded)
    if not counted and fallback_to_all:
        counted = set(sizes)
    if not counted:
        return None
    base = ZERO
    for account in sorted(counted):
        size = sizes.get(account)
        if size is None or not _usable(size):
            return None
        base += size
    return base
