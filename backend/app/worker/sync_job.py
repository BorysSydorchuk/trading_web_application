"""The `mt5_sync` worker job: every minute, sync each due active account in turn (PRD 6.2).

Cadence per account comes from config/rules.yaml `sync` (60 s in trading hours, 15 min
otherwise) measured from the account's last attempt. Accounts are isolated: one failure is
recorded in its sync_log row and logged, the others still run.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT, Settings
from app.config_files import ConfigError, get_rules
from app.config_files.rules import RulesConfig
from app.models import Account
from app.models.enums import AccountStatus
from app.mt5.fixture import FixtureMt5Source
from app.mt5.real import RealMt5Source
from app.mt5.source import Mt5Source
from app.services.sync import close_orphaned_runs, is_due, sync_account

logger = logging.getLogger(__name__)

SYNC_JOB_ID = "mt5_sync"
SYNC_JOB_INTERVAL_S = 60
FIXTURE_PREFIX = "fixture:"


def make_source(settings: Settings) -> Mt5Source:
    """`MT5_SOURCE`: "real" (default) or "fixture:<path>" (relative to the repo root)."""
    spec = settings.mt5_source.strip()
    if spec.lower() in ("", "real"):
        return RealMt5Source()
    if spec.lower().startswith(FIXTURE_PREFIX):
        path = Path(spec[len(FIXTURE_PREFIX) :].strip())
        if not path.is_absolute():
            path = REPO_ROOT / path
        logger.warning("MT5_SOURCE uses fixture data from %s (no real terminal)", path)
        return FixtureMt5Source.from_file(path)
    raise ValueError(f"MT5_SOURCE must be 'real' or 'fixture:<path>', got {spec!r}")


def run_sync_cycle(
    session_factory: sessionmaker[Session],
    source: Mt5Source,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    rules_getter: Callable[[], RulesConfig] = get_rules,
    lock: threading.Lock | None = None,
) -> list[int]:
    """Sync every due active account sequentially. Returns the ids of synced accounts.

    ``lock`` (shared with the margin job, `app.worker.mt5_shared`) is acquired blocking and
    held for the whole cycle: sync has priority and waits for a running margin lookup.
    """
    try:
        rules = rules_getter()
    except ConfigError as exc:
        logger.error("MT5 sync skipped: %s", exc)
        return []
    with lock if lock is not None else nullcontext():
        return _sync_due_accounts(session_factory, source, rules, now)


def _sync_due_accounts(
    session_factory: sessionmaker[Session],
    source: Mt5Source,
    rules: RulesConfig,
    now: Callable[[], datetime],
) -> list[int]:
    with session_factory() as session:
        account_ids = list(
            session.scalars(
                select(Account.id)
                .where(Account.status == AccountStatus.ACTIVE.value)
                .order_by(Account.id)
            )
        )
    synced: list[int] = []
    for account_id in account_ids:
        try:
            with session_factory() as session:
                account = session.get(Account, account_id)
                if account is None or account.status != AccountStatus.ACTIVE.value:
                    continue  # deleted/archived since the list was read
                started = now()
                if not is_due(session, account_id, rules, started):
                    continue
                sync_account(session, account, source, rules, started)
                synced.append(account_id)
        except Exception:
            # sync_account records MT5/data errors itself; this catches e.g. a DB outage.
            logger.exception("MT5 sync of account %s failed; continuing with the next", account_id)
    return synced


def mark_interrupted_runs(session_factory: sessionmaker[Session]) -> None:
    """At worker start: sync_log rows still "running" belong to a stopped worker."""
    try:
        with session_factory() as session:
            count = close_orphaned_runs(session, datetime.now(UTC))
        if count:
            logger.warning("Marked %s interrupted sync(s) from a previous run as failed", count)
    except Exception:
        logger.exception("Could not clean up interrupted syncs")
