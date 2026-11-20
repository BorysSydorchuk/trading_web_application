"""One-off: recompute the numbers of every saved digest after a formula change.

    (repo root, PowerShell or cmd)
    python -m uv run --project backend python -m app.tools.recompute_digests          # dry run
    python -m uv run --project backend python -m app.tools.recompute_digests --apply

M8-10b fixes (PM 2026-11-20): the period % base now counts accounts whose only trades are
excluded from statistics. Review texts and saved AI summary texts are kept; a saved summary
whose numbers changed gets «Підсумок застарів» (``ai_summary_stale_at``). No digest is
created. ``--apply`` on a non-test database first writes a verified pre-migration backup
(`backups/pre-migration-recompute-digests-<UTC>.dump`, same tool as `app.tools.migrate`) and
writes nothing when the backup fails. The dry run rolls back.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session_factory
from app.logging_setup import setup_logging
from app.services.digests import recompute_all
from app.tools import migrate

logger = logging.getLogger(__name__)
LOG_FILE = "maintenance.log"
BACKUP_LABEL = "recompute-digests"
LOG_PATH = f"logs/{LOG_FILE}"
FAILED = "Помилка резервування чи перерахунку дайджестів; нічого не змінено. Деталі:"

Backup = Callable[[Settings, TextIO], Path | None]


def take_backup(settings: Settings, out: TextIO, deps: migrate.Deps | None = None) -> Path | None:
    """Verified pg_dump of a real database; None for a test database. Raises BackupError."""
    target = migrate.parse_target(settings.database_url)
    if target.is_test:
        return None
    deps = deps or migrate.Deps()
    deps.confirm_target(settings.database_url, settings.postgres_port)
    return migrate.make_backup(target, BACKUP_LABEL, deps, out, compose_port=settings.postgres_port)


def run(
    session: Session,
    *,
    apply: bool,
    now: datetime,
    out: TextIO,
    backup: Callable[[], Path | None] = lambda: None,
) -> list[tuple[int, bool]]:
    """Recompute all digests; commit only with ``apply`` (after the backup), else roll back."""
    path = backup() if apply else None
    if path is not None:
        print(f"Резервна копія: {path}", file=out)
    result = recompute_all(session, now)
    changed = [digest_id for digest_id, diff in result if diff]
    if apply:
        session.commit()
        logger.info("Digests recomputed: %d, numbers changed: %s", len(result), changed)
    else:
        session.rollback()
    mode = "застосовано" if apply else "пробний запуск, нічого не змінено"
    print(
        f"Дайджестів: {len(result)}, змінилися числа: {len(changed)} {changed} ({mode})", file=out
    )
    return result


def main(argv: Sequence[str] | None = None, *, backup: Backup = take_backup) -> int:
    parser = argparse.ArgumentParser(prog="recompute_digests", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the recomputed numbers")
    args = parser.parse_args(argv)
    out = sys.stdout
    if isinstance(out, io.TextIOWrapper):
        out.reconfigure(encoding="utf-8")
    settings = get_settings()
    setup_logging(LOG_FILE, settings)
    with get_session_factory()() as session:
        try:
            run(
                session,
                apply=args.apply,
                now=datetime.now(UTC),
                out=out,
                backup=lambda: backup(settings, out),
            )
        except migrate.MigrateError as exc:  # BackupError included; texts carry no secrets
            return _fail(f"Резервну копію не створено, нічого не змінено: {exc}")
        except Exception:
            logger.exception("recompute_digests failed")
            return _fail(f"{FAILED} {LOG_PATH}")
    return 0


def _fail(text: str) -> int:
    logger.error("%s", text)
    print(text, file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
