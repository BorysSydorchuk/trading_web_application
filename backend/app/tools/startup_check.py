"""Non-destructive startup preflight. No MT5, AI, Whisper, dumps or migrations."""

# ruff: noqa: RUF001 - Ukrainian launcher messages
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, text

from app.config import REPO_ROOT, Settings, get_settings
from app.config_files import check_config_files
from app.services.backups import BackupStore, PostgresTools, _directory, target_key
from app.tools.migrate import parse_target


class StartupFailure(Exception):  # noqa: N818 - public preflight failure contract
    """Only fixed actionable messages; never driver/config exception text."""


def check_directories(settings: Settings) -> None:
    try:
        store = BackupStore(settings.backup_dir, compose_port=settings.postgres_port)
        for path in (
            settings.data_dir,
            settings.log_dir_path,
            store.scope(settings.database_url),
            REPO_ROOT / "backups",
        ):
            _directory(path)
            with tempfile.TemporaryFile(dir=path, suffix=".probe") as stream:
                stream.write(b"startup probe")
                stream.flush()
                os.fsync(stream.fileno())
    except Exception:
        raise StartupFailure(
            "Немає доступу на запис до DATA_DIR, LOG_DIR або BACKUP_DIR/backups. "
            "Перевірте права, вільне місце та відсутність посилань у шляху."
        ) from None


def check_database(settings: Settings) -> None:
    engine = None
    try:
        target_key(settings.database_url)
        target = parse_target(settings.database_url)
        engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
        with engine.connect() as connection:
            connection.execute(text("SET LOCAL statement_timeout = 5000"))
            if connection.scalar(text("SELECT current_database()")) != target.database:
                raise ValueError("wrong identity")
            connection.execute(text("SELECT 1"))
    except Exception:
        raise StartupFailure(
            "Не вдалося підтвердити підключення та ідентичність БД. Перевірте PostgreSQL, "
            "DATABASE_URL, права користувача й назву БД; міграції не виконано."
        ) from None
    finally:
        if engine is not None:
            engine.dispose()


def check_backup_tools(settings: Settings) -> None:
    try:
        target = parse_target(settings.database_url)
        dump, restore = shutil.which("pg_dump"), shutil.which("pg_restore")
        if dump:
            if not restore:
                raise ValueError("missing restore")
            commands = [[dump, "--version"], [restore, "--version"]]
        else:
            docker = shutil.which("docker")
            if not docker or not target.is_local or target.port != settings.postgres_port:
                raise ValueError("no compatible tool")
            PostgresTools._confirm_compose(settings.database_url, target)
            commands = [
                [docker, "compose", "exec", "-T", "db", tool, "--version"]
                for tool in ("pg_dump", "pg_restore")
            ]
        for command in commands:
            result = subprocess.run(  # noqa: S603 - fixed version commands, no shell/credentials
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                timeout=15,
                check=False,
            )
            version = re.search(rb"PostgreSQL\) (\d+)", result.stdout)
            if result.returncode or version is None or int(version[1]) < 16:
                raise ValueError("tool unavailable")
    except Exception:
        raise StartupFailure(
            "Недоступні pg_dump/pg_restore. Встановіть клієнт PostgreSQL 16 або запустіть "
            "локальний Docker db. Для Docker потрібна перевірка ідентичності кластера; "
            "віддалена БД потребує локальних PostgreSQL tools."
        ) from None


def check(settings: Settings) -> None:
    if sys.version_info[:2] != (3, 12):
        raise StartupFailure(
            "Потрібен Python 3.12.x для бекенду. Перевстановіть venv через uv sync."
        )
    # Config loader logs can include invalid input. The CLI emits fixed text only.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        errors = check_config_files()
    finally:
        logging.disable(previous)
    if errors:
        raise StartupFailure(
            "Некоректна конфігурація YAML. Перевірте файли config/ або CONFIG_DIR; запуск зупинено."
        )
    check_directories(settings)
    check_database(settings)
    check_backup_tools(settings)


def main() -> int:
    try:
        check(get_settings())
    except StartupFailure as error:
        print(str(error), flush=True)
        return 1
    except Exception:
        print(
            "Некоректні налаштування застосунку. Перевірте .env і config/; значення не виводимо.",
            flush=True,
        )
        return 1
    print("Перевірки БД, інструментів резервування, каталогів і конфігурації пройдено.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
