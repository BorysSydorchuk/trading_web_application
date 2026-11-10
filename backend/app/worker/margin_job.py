"""The `calculator_margin` worker job: live MT5 margin for queued calculator requests.

docs/api.md "Margin integration design" / M5-04d. Every 2 s, under the process-wide MT5
lock shared with sync (non-blocking: sync keeps priority, this run is then skipped):

1. ``processing`` rows older than `STALE_PROCESSING_S` (result lost, worker died) become
   ``failed``/``interrupted`` (safe: we hold the lock, so no lookup of ours is running), and
   pending requests past ``expires_at`` become ``expired`` (``request_expired``).
2. The oldest live pending request (``FOR UPDATE SKIP LOCKED``) is committed as
   ``processing`` before MT5 is called, so the UI can show it.
3. The account's terminal is connected/verified like sync (``connected``), then the read-only
   ``calc_margin`` runs; the terminal is always shut down.
4. The row ends ``done`` with the margin, or ``failed`` with the `Mt5ErrorCode` value
   (``internal_error`` for anything unexpected, traceback logged).

At most one request per run. All timestamps come from the DB ``now()``. Passwords are never
logged. At worker start `mark_interrupted_margin_requests` fails rows left ``processing``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import mt5_password_for
from app.models import Account
from app.models.calculator import CalculatorMarginRequest
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.source import Mt5Source, connected
from app.mt5.types import Direction
from app.services.margin_requests import STALE_PROCESSING
from app.services.sync import INTERNAL_ERROR, PasswordLookup

logger = logging.getLogger(__name__)

MARGIN_JOB_ID = "calculator_margin"
MARGIN_JOB_INTERVAL_S = 2
REQUEST_EXPIRED = "request_expired"
INTERRUPTED = "interrupted"
# calculator_margin_requests.margin is NUMERIC(28, 8).
_MARGIN_INTEGER_DIGITS = 20

_Request = CalculatorMarginRequest


@dataclass(frozen=True)
class ClaimedRequest:
    """What the MT5 phase needs, read while the row was claimed."""

    id: int
    direction: Direction
    symbol: str  # canonical (logs)
    broker_symbol: str  # what MT5 is asked with (M5-08)
    volume: Decimal
    entry: Decimal
    login: int
    server: str
    terminal_path: str


def _rowcount(result: object) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


def sweep_stale_processing(session: Session) -> int:
    """``processing`` rows started more than `STALE_PROCESSING` ago -> failed/interrupted.

    Call only while holding the MT5 lock (no lookup of this worker is running). Commits.
    """
    result = session.execute(
        update(_Request)
        .where(
            _Request.status == "processing",
            _Request.started_at < func.now() - STALE_PROCESSING,
        )
        .values(status="failed", error_code=INTERRUPTED, finished_at=func.now())
    )
    session.commit()
    count = _rowcount(result)
    if count:
        logger.warning("Marked %s stuck processing margin request(s) as interrupted", count)
    return count


def expire_overdue(session: Session) -> int:
    """Pending rows past ``expires_at`` -> expired. Rows locked elsewhere are skipped. Commits."""
    overdue = (
        select(_Request.id)
        .where(_Request.status == "pending", _Request.expires_at <= func.now())
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    result = session.execute(
        update(_Request)
        .where(_Request.id.in_(overdue))
        .values(status="expired", error_code=REQUEST_EXPIRED, finished_at=func.now())
    )
    session.commit()
    count = _rowcount(result)
    if count:
        logger.info("Expired %s margin request(s) not started within their time limit", count)
    return count


def claim_next(session: Session) -> ClaimedRequest | None:
    """Oldest live pending request -> processing (committed), or None."""
    row = session.scalar(
        select(_Request)
        .where(_Request.status == "pending", _Request.expires_at > func.now())
        .order_by(_Request.created_at, _Request.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        session.commit()
        return None
    account = session.get(Account, row.account_id)
    if account is None:  # pragma: no cover - FK with ON DELETE CASCADE
        session.rollback()
        return None
    claimed = ClaimedRequest(
        id=row.id,
        direction=row.direction,  # type: ignore[arg-type]  # CHECK direction_valid
        symbol=row.symbol,
        broker_symbol=row.broker_symbol,
        volume=row.volume,
        entry=row.entry,
        login=account.login,
        server=account.server,
        terminal_path=account.terminal_path or "",
    )
    row.status = "processing"
    row.started_at = func.now()  # SQL expression: the DB clock
    session.commit()
    return claimed


def _checked_margin(margin: Decimal) -> Decimal:
    """Sources already reject negative/non-finite values; only overflow is left. Rounding
    to 8 decimals by NUMERIC(28, 8) is accepted (far below any displayed precision)."""
    if margin.adjusted() >= _MARGIN_INTEGER_DIGITS:
        raise Mt5Error(Mt5ErrorCode.MT5_ERROR, f"margin from MT5 too large to store: {margin}")
    return margin


def lookup_margin(
    source: Mt5Source, claimed: ClaimedRequest, password_for: PasswordLookup
) -> tuple[Decimal | None, str | None]:
    """``(margin, None)`` or ``(None, error_code)``; never raises."""
    try:
        if not claimed.terminal_path.strip():  # as sync/resolve_terminal, before connecting
            raise Mt5Error(
                Mt5ErrorCode.TERMINAL_NOT_FOUND, "terminal path is not set for the account"
            )
        password = password_for(claimed.login)
        with connected(source, claimed.terminal_path, claimed.login, password, claimed.server):
            margin = source.calc_margin(
                claimed.direction, claimed.broker_symbol, claimed.volume, claimed.entry
            )
        return _checked_margin(margin), None
    except Mt5Error as exc:
        logger.error("Margin request %s failed: %s: %s", claimed.id, exc.code.value, exc.message)
        return None, exc.code.value
    except Exception:
        logger.exception("Margin request %s failed with an unexpected error", claimed.id)
        return None, INTERNAL_ERROR


def finish(session: Session, request_id: int, margin: Decimal | None, code: str | None) -> None:
    """processing -> done (margin) or failed (error code), ``finished_at`` = DB now. Commits."""
    if code is None and margin is not None:
        values: dict[str, object] = {"status": "done", "margin": margin}
    else:
        values = {"status": "failed", "error_code": code or INTERNAL_ERROR}
    result = session.execute(
        update(_Request)
        .where(_Request.id == request_id, _Request.status == "processing")
        .values(**values, finished_at=func.now())
    )
    session.commit()
    if _rowcount(result) == 0:
        logger.warning(
            "Margin request %s is no longer processing; its %s result was dropped",
            request_id,
            values["status"],
        )


def run_margin_cycle(
    session_factory: sessionmaker[Session],
    source: Mt5Source,
    lock: threading.Lock,
    *,
    password_for: PasswordLookup = mt5_password_for,
) -> int | None:
    """Handle at most one request. Returns its id, or None (nothing to do / lock held)."""
    if not lock.acquire(blocking=False):
        return None  # sync is using MT5; try again on the next run
    try:
        with session_factory() as session:
            sweep_stale_processing(session)
            expire_overdue(session)
            claimed = claim_next(session)
        if claimed is None:
            return None
        margin, code = lookup_margin(source, claimed, password_for)
        try:
            with session_factory() as session:
                finish(session, claimed.id, margin, code)
        except Exception:
            logger.exception(
                "Margin request %s: could not store the result; it stays processing until "
                "the stale sweep marks it interrupted",
                claimed.id,
            )
            return None
        if code is None:
            logger.info("Margin request %s done: %s", claimed.id, margin)
        return claimed.id
    finally:
        lock.release()


def mark_interrupted_margin_requests(session_factory: sessionmaker[Session]) -> int:
    """At worker start: rows still ``processing`` belong to a stopped worker -> failed."""
    try:
        with session_factory() as session:
            result = session.execute(
                update(_Request)
                .where(_Request.status == "processing")
                .values(status="failed", error_code=INTERRUPTED, finished_at=func.now())
            )
            session.commit()
    except Exception:
        logger.exception("Could not clean up interrupted margin requests")
        return 0
    count = _rowcount(result)
    if count:
        logger.warning("Marked %s interrupted margin request(s) as failed", count)
    return count
