"""One-shot verified backup. No scheduler; manual archives are never auto-pruned."""

# ruff: noqa: RUF001 - Ukrainian console messages

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.services.backups import BackupStore, Kind


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--kind", choices=("manual", "daily"), default="manual")
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        kind: Kind = args.kind
        store = BackupStore(args.root or settings.backup_dir, compose_port=settings.postgres_port)
        item = store.create(settings.database_url, kind=kind)
        print("Резервну копію перевірено: " + str(item.archive))
        if kind == "daily":
            store.prune(settings.database_url)
        return 0
    except Exception:
        # Never echo tool stderr, URL, credentials or arbitrary exception text.
        print(
            "Помилка резервного копіювання або зберігання. Перевірте БД, інструменти, "
            "права доступу, вільне місце та блокування каталогу.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
