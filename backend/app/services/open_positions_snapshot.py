"""Live open-position values for «Головна» (M8-10b; docs/api.md "M8-10b", DECISIONS 2026-11-20).

The worker writes ``DATA_DIR/open_positions.json`` after every successful account sync from
the positions the sync already read (MT5 ``positions_get``, read-only):

    {"<account_id>": {"<position_id>": {"price_current": "2650.5", "profit": "-12.30",
                                        "time": "2026-11-20T09:00:00Z"}}}

``profit`` = MT5 position profit + swap (account currency), ``time`` = the sync time (UTC).
``"_synced_at": {"<account_id>": "<sync start, UTC>"}`` says which sync wrote each account's
entry (an empty entry = MT5 reported no positions then); readers of positions skip it.
The file is replaced atomically (temp file + ``os.replace``). The API reads it; values older
than ``STALE_AFTER`` are stale (only their time is shown). A missing or broken file never
fails a reader (logged once per process); a failed write never fails a sync (logged by the
caller).
"""

from __future__ import annotations

import json
import logging
import os
import time as monotonic_time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.mt5.types import RawPosition

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = "open_positions.json"
SYNCED_KEY = "_synced_at"
STALE_AFTER = timedelta(minutes=5)
# Windows: os.replace fails while a reader has the target open; readers are brief.
_REPLACE_ATTEMPTS = 5
_REPLACE_PAUSE_S = 0.05

_warned: set[str] = set()


@dataclass(frozen=True)
class LiveValue:
    price_current: Decimal
    pnl: Decimal  # profit + swap, account currency
    time: datetime  # aware UTC


def snapshot_path(data_dir: Path) -> Path:
    return data_dir / SNAPSHOT_FILE


def _utc_iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _position_entry(position: RawPosition, at: datetime) -> dict[str, str]:
    return {
        "price_current": format(position.price_current, "f"),
        "profit": format(position.profit + position.swap, "f"),
        "time": _utc_iso(at),
    }


def _read_raw(path: Path) -> dict[str, Any]:
    """The current file as a dict; anything unreadable is treated as empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Open positions snapshot %s unreadable, rewritten: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _replace(tmp: Path, path: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            monotonic_time.sleep(_REPLACE_PAUSE_S)


def write_account(
    path: Path, account_id: int, positions: Sequence[RawPosition], at: datetime
) -> None:
    """Replace ``account_id``'s positions in the snapshot (others kept). Raises OSError."""
    data = _read_raw(path)
    data[str(account_id)] = {str(p.identifier): _position_entry(p, at) for p in positions}
    synced = data.get(SYNCED_KEY)
    data[SYNCED_KEY] = {
        **(synced if isinstance(synced, dict) else {}),
        str(account_id): _utc_iso(at),
    }
    write_json_atomic(path, data)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Replace ``path`` with ``data`` as JSON (temp file + ``os.replace``). Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _warn_once(key: str, message: str, *args: object) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def _parse_value(raw: Any) -> LiveValue | None:
    if not isinstance(raw, dict):
        return None
    try:
        at = datetime.fromisoformat(str(raw["time"]))
        value = LiveValue(Decimal(str(raw["price_current"])), Decimal(str(raw["profit"])), at)
    except (KeyError, ValueError, InvalidOperation):
        return None
    if at.tzinfo is None or not value.price_current.is_finite() or not value.pnl.is_finite():
        return None
    return value


def _parse(data: dict[str, Any]) -> dict[tuple[int, int], LiveValue]:
    out: dict[tuple[int, int], LiveValue] = {}
    for account_key, positions in data.items():
        if not isinstance(positions, dict):
            continue
        for position_key, raw in positions.items():
            value = _parse_value(raw)
            try:
                key = (int(account_key), int(position_key))
            except ValueError:
                continue
            if value is not None:
                out[key] = value
    return out


def is_fresh(value: LiveValue, now: datetime) -> bool:
    """Live values older than ``STALE_AFTER`` are not shown (only their time is)."""
    return now - value.time <= STALE_AFTER


def read_snapshot(path: Path) -> dict[tuple[int, int], LiveValue]:
    """Values by (account_id, position_id), stale ones included (see ``is_fresh``). Never
    raises: a missing or broken file is an empty result (warning logged once per process)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _warn_once("missing", "Open positions snapshot %s not found: no live prices", path)
        return {}
    except (OSError, ValueError) as exc:
        _warn_once("broken", "Open positions snapshot %s unreadable: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        _warn_once("broken", "Open positions snapshot %s unreadable: not a mapping", path)
        return {}
    return _parse(data)


def synced_at(path: Path) -> dict[int, datetime]:
    """Per account: start time of the sync that wrote its entry. Never raises (missing or
    unreadable file, or a file from before this key: no accounts)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # read_snapshot already warns about a missing/broken file
    raw = data.get(SYNCED_KEY) if isinstance(data, dict) else None
    out: dict[int, datetime] = {}
    for key, value in (raw if isinstance(raw, dict) else {}).items():
        try:
            at = datetime.fromisoformat(str(value))
            account_id = int(key)
        except ValueError:
            continue
        if at.tzinfo is not None:
            out[account_id] = at
    return out
