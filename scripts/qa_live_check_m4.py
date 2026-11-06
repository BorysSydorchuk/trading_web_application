"""Start M4 owner checks using an existing local QA DB, fixture MT5 and disabled AI.

No database creation, reset or deletion. Config bytes are copied unchanged; audio and
logs remain in the separate QA directory. Shared dev.py owns processes and migrations.
Stop the normal app before starting this script. See docs/reports/M4-live-check.md.
"""

# Ukrainian console messages intentionally contain Cyrillic look-alikes.
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import qa_live_check as common

ROOT = common.ROOT
CONFIG_SRC = ROOT / "config"
QA_DB_NAME = "trading_journal_qa_m4"
QA_DATABASE_URL = f"postgresql+psycopg://journal:journal@127.0.0.1:5432/{QA_DB_NAME}"
DEFAULT_BASE = Path(tempfile.gettempdir()) / "tj-qa-m4"
COPY_MARKER = ".tj-qa-m4-copy"
MARKER_TEXT = "scripts/qa_live_check_m4.py\n"
QaError = common.QaError
validate_config = common.validate_config
run_dev = common.run_dev
shown_env = common.shown_env


def check_qa_database(url: str) -> None:
    """Accept only an exact local PostgreSQL target without routing overrides."""
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme == "postgresql+psycopg"
            and parts.hostname in {"localhost", "127.0.0.1", "::1"}
            and parts.path == f"/{QA_DB_NAME}"
            and not parts.query
            and not parts.fragment
        )
        # Accessing port validates malformed values too, without exposing the URL.
        port = parts.port
        valid = valid and (port is None or 1 <= port <= 65535)
    except ValueError:
        valid = False
    if not valid:
        raise QaError(
            f"Дозволена лише локальна PostgreSQL QA-база {QA_DB_NAME} без параметрів URL."
        )


def qa_env(
    base: Path,
    config: Path,
    database_url: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Override inherited application settings in the child, including any AI key."""
    check_qa_database(database_url)
    env = dict(os.environ if environ is None else environ)
    # Settings are case-insensitive: discard case variants before writing canonical names.
    overrides = {
        **common.QA_ENV,
        "DATABASE_URL": database_url,
        "DATA_DIR": str(base / "data"),
        "LOG_DIR": str(base / "logs"),
        "CONFIG_DIR": str(config),
        "ANTHROPIC_API_KEY": "",
        "PYTHONIOENCODING": "utf-8",
    }
    names = {key.casefold() for key in overrides}
    env = {key: value for key, value in env.items() if key.casefold() not in names}
    env.update(overrides)
    return env


def check_base_dir(base: Path) -> None:
    common.check_base_dir(base)
    # Refuse junctions/symlinks into unrelated config, audio or log directories.
    for name in ("config", "data", "logs"):
        child = base / name
        if child.resolve().parent != base.resolve() or child.is_symlink():
            raise QaError("QA-папки config/data/logs не можуть бути посиланнями на інші папки.")


def prepare_config(src: Path, dest: Path) -> None:
    """Only replace a marked M4 copy; preserve every source byte and all QA audio."""
    check_base_dir(dest.parent)
    if not src.is_dir():
        raise QaError("Не знайдено config/ застосунку.")
    if dest.exists():
        marker = dest / COPY_MARKER
        if (
            not dest.is_dir()
            or not marker.is_file()
            or marker.is_symlink()
            or marker.read_text(encoding="utf-8") != MARKER_TEXT
        ):
            raise QaError("Відмовляюся замінювати config/: це не позначена QA-копія M4.")
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    (dest / COPY_MARKER).write_text(MARKER_TEXT, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4: локальна QA-база, fixture MT5, AI вимкнено.")
    parser.add_argument("--no-browser", action="store_true", help="не відкривати браузер")
    parser.add_argument(
        "--database-url",
        default=QA_DATABASE_URL,
        help="URL наявної локальної QA-бази M4",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE,
        help="окрема QA-папка поза репозиторієм",
    )
    args = parser.parse_args(argv)
    common._utf8_console()
    try:
        base = args.base_dir.expanduser().resolve()
        config = base / "config"
        env = qa_env(base, config, args.database_url)
        check_base_dir(base)
        common.say(f"QA-база {QA_DB_NAME}; AI вимкнено. MT5 працює лише з fixtures.")
        prepare_config(CONFIG_SRC, config)
        common.say("Копію config/ збережено без змін. Аудіо попередніх QA-перевірок залишено.")
        validate_config(env)
        common.say("Зупиніть звичайний застосунок перед запуском QA: ті самі порти й stop.bat.")
        return run_dev(env, ["--no-browser"] if args.no_browser else [])
    except (QaError, OSError, UnicodeError):
        # Never echo exception text: OS/URL errors may contain connection secrets.
        common.say(
            "Помилка: запуск QA відхилено. Перевірте локальну QA-базу, шлях і позначку config/."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
