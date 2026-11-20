"""Starting balance suggested from the MT5 deal history (docs/api.md "Starting balance
suggestion (2026-11-20)", DECISIONS 2026-11-20).

The worker reads an account's full deal history once (read-only, when the file below has no
entry for it) and stores its first deposit = the earliest non-trade deal (MT5 type not buy
0 / sell 1; brokers book deposits as type 2 and also 4) with a positive profit:

    {"<account_id>": {"amount": "10000.00", "time": "2026-11-10T12:53:00Z",
                      "ticket": 194830322, "checked_at": "2026-11-20T09:00:00Z"}}

``amount`` = profit + commission + swap + fee (account currency, 2 decimals); ``time`` UTC.
No deposit found: ``{"amount": null, "checked_at": ...}`` (not re-read every minute). The
API shows the suggestion while it differs from the stored starting balance; the owner
confirms it with the existing PATCH. A missing or broken file never fails a reader (logged
once per process); a failed write never fails a sync (logged by the caller).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.domain.broker_time import Conversion
from app.mt5.convert import deal_time_utc
from app.mt5.source import Mt5Source
from app.mt5.types import RawDeal
from app.services.open_positions_snapshot import write_json_atomic

logger = logging.getLogger(__name__)

SUGGESTIONS_FILE = "starting_balance_suggestions.json"
TRADE_DEAL_TYPES = (0, 1)  # MT5 DEAL_TYPE_BUY, DEAL_TYPE_SELL
CENT = Decimal("0.01")

_warned: set[str] = set()


@dataclass(frozen=True)
class FirstDeposit:
    amount: Decimal  # account currency, 2 decimals
    time: datetime  # aware UTC
    ticket: int


@dataclass(frozen=True)
class Suggestion:
    """One file entry. ``amount``/``time`` None: the history was read, no deposit found."""

    amount: Decimal | None
    time: datetime | None


def suggestions_path(data_dir: Path) -> Path:
    return data_dir / SUGGESTIONS_FILE


def _utc_iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _net(deal: RawDeal) -> Decimal:
    return (deal.profit + deal.commission + deal.swap + deal.fee).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def first_deposit(deals: Iterable[RawDeal], conversion: Conversion) -> FirstDeposit | None:
    """The earliest non-trade deal whose net amount (profit + costs, 2 dp) is positive
    (ties: lowest ticket), or None. Net, so a stored amount is always a valid starting balance
    and the account counts as checked (no full-history re-read every minute)."""
    candidates = [
        (deal_time_utc(d, conversion), d.ticket, net)
        for d in deals
        if d.type not in TRADE_DEAL_TYPES and (net := _net(d)) > 0
    ]
    if not candidates:
        return None
    at, ticket, amount = min(candidates, key=lambda c: (c[0], c[1]))
    return FirstDeposit(amount=amount, time=at, ticket=ticket)


def read_history_deposit(
    source: Mt5Source, account_id: int, to_server_epoch: int, conversion: Conversion
) -> tuple[bool, FirstDeposit | None]:
    """Read the full deal history (read-only, while connected) and pick its first deposit.
    Never raises: returns (False, None) with a warning when the history is not read."""
    try:
        return True, first_deposit(source.deals(0, to_server_epoch), conversion)
    except Exception as exc:
        logger.warning(
            "Account %s: deal history for the starting balance suggestion not read: %s: %s",
            account_id,
            type(exc).__name__,
            exc,
        )
        return False, None


def _read_raw(path: Path) -> dict[str, Any]:
    """The current file as a dict; anything unreadable is treated as empty (rewritten)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Starting balance suggestions %s unreadable, rewritten: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def write_account(
    path: Path, account_id: int, deposit: FirstDeposit | None, checked_at: datetime
) -> None:
    """Replace ``account_id``'s entry (others kept), atomically. Raises OSError."""
    data = _read_raw(path)
    entry: dict[str, Any] = {"amount": None, "checked_at": _utc_iso(checked_at)}
    if deposit is not None:
        entry |= {
            "amount": format(deposit.amount, "f"),
            "time": _utc_iso(deposit.time),
            "ticket": deposit.ticket,
        }
    data[str(account_id)] = entry
    write_json_atomic(path, data)


def _warn_once(key: str, message: str, *args: object) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def _parse_entry(raw: Any) -> Suggestion | None:
    if not isinstance(raw, dict) or "amount" not in raw:
        return None
    if raw["amount"] is None:
        return Suggestion(None, None)
    try:
        amount = Decimal(str(raw["amount"]))
        at = datetime.fromisoformat(str(raw["time"]))
    except (KeyError, ValueError, InvalidOperation):
        return None
    if at.tzinfo is None or not amount.is_finite() or amount <= 0:
        return None
    return Suggestion(amount, at)


def read_suggestions(path: Path) -> dict[int, Suggestion]:
    """Entries by account id. Never raises: a missing or broken file is empty (logged once
    per process); a malformed entry is skipped."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if "missing" not in _warned:
            _warned.add("missing")
            logger.info("Starting balance suggestions %s not found yet", path)
        return {}
    except (OSError, ValueError) as exc:
        _warn_once("broken", "Starting balance suggestions %s unreadable: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        _warn_once("broken", "Starting balance suggestions %s unreadable: not a mapping", path)
        return {}
    out: dict[int, Suggestion] = {}
    for key, raw in data.items():
        entry = _parse_entry(raw)
        try:
            account_id = int(key)
        except ValueError:
            continue
        if entry is not None:
            out[account_id] = entry
    return out


def suggestion_for(
    suggestions: dict[int, Suggestion], account_id: int, starting_balance: Decimal
) -> Suggestion | None:
    """The entry to show: only with an amount that differs from the stored balance."""
    entry = suggestions.get(account_id)
    if entry is None or entry.amount is None or entry.amount == starting_balance:
        return None
    return entry
