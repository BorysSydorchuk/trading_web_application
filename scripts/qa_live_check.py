"""Start the app for Borys's M3 live check against the QA database (docs/reports/M3-live-check.md).

Stdlib only, Python 3.12+. Steps:
  1. refuses to run unless DATABASE_URL points at the QA database `trading_journal_qa_m3`,
  2. copies `config/` to `<base>/config` (fresh each run; default base `%TEMP%\\tj-qa`) and
     makes the `lesson` journal field required there: only that one line changes, the rest of
     the file stays byte-identical (UTF-8 in and out, no BOM, line endings kept),
  3. checks that the copied config loads with the app's own loader (incl. the mojibake check),
  4. starts the app like `start.bat` (`scripts/dev.py`) with the QA environment: fixture MT5
     source, `<base>/data` as DATA_DIR (kept between runs), the copied config, Whisper beam 1.

Stop it with Ctrl+C or `stop.bat` (same run file as dev.py). Your real journal is not touched.

Usage:
  python scripts/qa_live_check.py [--no-browser] [--whisper-condition-on-previous-text]
                                  [--database-url URL] [--base-dir DIR]
"""

# Only fixed commands (python, uv) are executed; no user input reaches a shell.
# ruff: noqa: S603, RUF001
# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
CONFIG_SRC = ROOT / "config"
DEV_SCRIPT = ROOT / "scripts" / "dev.py"
JOURNAL_FIELDS = "journal_fields.yaml"
# Written into every copy; only a folder with it (or a pre-marker copy, see `_is_our_copy`) is
# ever deleted, so a wrong --base-dir cannot wipe a real folder.
COPY_MARKER = ".tj-qa-copy"
REQUIRED_KEY = "lesson"

QA_DB_NAME = "trading_journal_qa_m3"
QA_DATABASE_URL = f"postgresql+psycopg://journal:journal@127.0.0.1:5432/{QA_DB_NAME}"
DEFAULT_BASE = Path(tempfile.gettempdir()) / "tj-qa"
QA_ENV: dict[str, str] = {
    "MT5_SOURCE": "fixture:backend/tests/fixtures/mt5/basic_week.json",
    "MT5_PASSWORD_51234567": "qa",
    "WHISPER_BEAM_SIZE": "1",
    "WHISPER_CPU_THREADS": "auto",
}
CONFIG_CHECK_TIMEOUT_S = 300
CONFIG_CHECK = (
    "import sys\n"
    "from app.config_files import check_config_files\n"
    "sys.exit(1 if check_config_files() else 0)\n"
)

_KEY_LINE = re.compile(r"^\s*-\s+key:\s*(?P<key>[\w-]+)\s*(?:#.*)?$")
_REQUIRED_LINE = re.compile(
    r"^(?P<head>\s*required:\s*)(?P<value>true|false)(?P<tail>\s*(?:#.*)?)$"
)

MSG: dict[str, str] = {
    "help_description": (
        "Запуск застосунку для live-перевірки M3 з QA-базою trading_journal_qa_m3 "
        "і копією config/, де поле «Урок» обовʼязкове."
    ),
    "help_no_browser": "не відкривати браузер",
    "help_condition": "увімкнути WHISPER_CONDITION_ON_PREVIOUS_TEXT=true (для порівняння)",
    "help_database_url": "URL QA-бази (дозволена лише база " + QA_DB_NAME + ")",
    "help_base_dir": "тимчасова папка для копії config/ і data/ (типово %TEMP%\\tj-qa)",
    # Never put the URL itself into a message: it may contain the password.
    "db_not_qa": (
        "Відмовляюся запускати: DATABASE_URL вказує на базу «{name}», а не на QA-базу "
        + QA_DB_NAME
        + ". Ваш справжній журнал не можна чіпати."
    ),
    "db_not_postgres": "Відмовляюся запускати: DATABASE_URL має бути PostgreSQL-адресою.",
    "config_missing": "Не знайдено папку налаштувань {path}.",
    "copy_failed": "Не вдалося скопіювати config/ у {path}: {error}",
    "base_in_repo": (
        "Відмовляюся запускати: тимчасова папка {path} лежить у репозиторії або містить його; "
        "копія замінила б справжні config/ чи data/. Вкажіть папку поза репозиторієм "
        "(типово %TEMP%\\tj-qa)."
    ),
    "dest_not_copy": (
        "Відмовляюся видаляти {path}: це не копія налаштувань, створена цим скриптом. "
        "Видаліть папку вручну або вкажіть іншу --base-dir."
    ),
    "not_utf8": "Файл {path} не в кодуванні UTF-8 ({error}). Відновіть його з git.",
    "key_missing": "У {file} немає поля `key: {key}` з рядком `required:`.",
    "uv_missing": "Не знайдено uv у PATH. Див. README (Prerequisites).",
    "check_failed": (
        "Скопійовані налаштування не завантажуються (подробиці вище). Перевірте config/{file}; "
        "якщо текст спотворений, відновіть файл з git."
    ),
    "check_cannot_run": "Не вдалося перевірити налаштування: {error}",
    "check_timeout": "Перевірка налаштувань триває понад {seconds} с, зупинено.",
    "db_ok": "База даних: QA-база " + QA_DB_NAME + " (ваш справжній журнал не використовується).",
    "config_copied": "Налаштування скопійовано в {path} (стару копію видалено).",
    "lesson_required": "У копії {file} поле «{key}» тепер обовʼязкове (змінено лише один рядок).",
    "lesson_already": "У копії {file} поле «{key}» вже обовʼязкове, нічого не змінено.",
    "checking": "Перевіряю скопійовані налаштування (кодування UTF-8, спотворений текст)...",
    "check_output": "Нижче вивід перевірки налаштувань (uv run, завантажувач застосунку):",
    "config_ok": "Налаштування в порядку.",
    "env": "Середовище: {env}",
    "starting": "Запускаю застосунок через scripts/dev.py. Зупинка: Ctrl+C або stop.bat.",
    "dev_cannot_start": "Не вдалося запустити scripts/dev.py: {error}",
    "error": "ПОМИЛКА: {error}",
}


class QaError(Exception):
    """A readable (Ukrainian) reason why the QA start was refused."""


def say(msg: str) -> None:
    print(f"[qa] {msg}", flush=True)


# --------------------------------------------------------------------------- pure helpers


def check_qa_database(url: str) -> None:
    """Raise QaError unless `url` is a PostgreSQL URL of the QA database."""
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres"):
        raise QaError(MSG["db_not_postgres"])
    name = parts.path.lstrip("/")
    if name != QA_DB_NAME:
        raise QaError(MSG["db_not_qa"].format(name=name or "?"))


def make_field_required(text: str, key: str = REQUIRED_KEY) -> tuple[str, bool]:
    """Set `required: true` on field `key`; (new text, changed). Other lines stay identical."""
    lines = text.splitlines(keepends=True)
    in_field = False
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        key_match = _KEY_LINE.match(body)
        if key_match:
            in_field = key_match.group("key") == key
            continue
        required = _REQUIRED_LINE.match(body) if in_field else None
        if required is None:
            continue
        if required.group("value") == "true":
            return text, False
        ending = line[len(body) :]
        lines[index] = f"{required.group('head')}true{required.group('tail')}{ending}"
        return "".join(lines), True
    raise QaError(MSG["key_missing"].format(file=JOURNAL_FIELDS, key=key))


def check_base_dir(base: Path, root: Path = ROOT) -> None:
    """Refuse a base dir inside the repo (or one that contains it): real config/data live there."""
    base, root = base.resolve(), root.resolve()
    if base.is_relative_to(root) or root.is_relative_to(base):
        raise QaError(MSG["base_in_repo"].format(path=base))


def _is_our_copy(dest: Path, src: Path) -> bool:
    """A copy made by this script: has the marker, or (older runs) only files named as in src."""
    if (dest / COPY_MARKER).is_file():
        return True
    entries = list(dest.iterdir())
    return all(e.is_file() and (src / e.name).is_file() for e in entries)


def prepare_config(src: Path, dest: Path) -> bool:
    """Fresh copy of `src` in `dest` with `lesson` required; True if the line was changed."""
    if not src.is_dir():
        raise QaError(MSG["config_missing"].format(path=src))
    try:
        if dest.exists():
            if not dest.is_dir() or not _is_our_copy(dest, src):
                raise QaError(MSG["dest_not_copy"].format(path=dest))
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        (dest / COPY_MARKER).write_text("scripts/qa_live_check.py\n", encoding="utf-8")
    except OSError as exc:
        raise QaError(MSG["copy_failed"].format(path=dest, error=exc)) from exc
    path = dest / JOURNAL_FIELDS
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise QaError(MSG["key_missing"].format(file=JOURNAL_FIELDS, key=REQUIRED_KEY)) from None
    except UnicodeDecodeError as exc:
        raise QaError(MSG["not_utf8"].format(path=path, error=exc)) from None
    new_text, changed = make_field_required(text)
    if changed:
        path.write_bytes(new_text.encode("utf-8"))
    return changed


def qa_env(
    base: Path,
    config: Path,
    database_url: str,
    condition_on_previous_text: bool,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The child environment: the current one plus the QA settings (these win over .env)."""
    check_qa_database(database_url)
    env = dict(os.environ if environ is None else environ)
    env.update(QA_ENV)
    env["DATABASE_URL"] = database_url
    env["DATA_DIR"] = str(base / "data")
    env["CONFIG_DIR"] = str(config)
    env["PYTHONIOENCODING"] = "utf-8"
    if condition_on_previous_text:
        env["WHISPER_CONDITION_ON_PREVIOUS_TEXT"] = "true"
    return env


def shown_env(env: Mapping[str, str]) -> str:
    """The QA variables for the console, without the DB URL (it may contain a password)."""
    keys = [*QA_ENV, "DATA_DIR", "CONFIG_DIR", "WHISPER_CONDITION_ON_PREVIOUS_TEXT"]
    return ", ".join(f"{k}={env[k]}" for k in keys if k in env)


# --------------------------------------------------------------------------- processes


def validate_config(env: Mapping[str, str]) -> None:
    """Load every config file with the app's loader; QaError (details printed) on failure."""
    uv = shutil.which("uv")
    if not uv:
        raise QaError(MSG["uv_missing"])
    say(MSG["check_output"])
    try:
        result = subprocess.run(
            [uv, "run", "--project", str(BACKEND), "python", "-c", CONFIG_CHECK],
            cwd=BACKEND,
            env=dict(env),
            timeout=CONFIG_CHECK_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise QaError(MSG["check_timeout"].format(seconds=CONFIG_CHECK_TIMEOUT_S)) from None
    except OSError as exc:
        raise QaError(MSG["check_cannot_run"].format(error=exc)) from exc
    if result.returncode != 0:
        raise QaError(MSG["check_failed"].format(file=JOURNAL_FIELDS))


def run_dev(env: Mapping[str, str], dev_args: Sequence[str]) -> int:
    try:
        proc = subprocess.Popen([sys.executable, str(DEV_SCRIPT), *dev_args], cwd=ROOT, env=env)
    except OSError as exc:
        raise QaError(MSG["dev_cannot_start"].format(error=exc)) from exc
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue  # dev.py gets the same Ctrl+C and stops its children; wait for it


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=MSG["help_description"])
    parser.add_argument("--no-browser", action="store_true", help=MSG["help_no_browser"])
    parser.add_argument(
        "--whisper-condition-on-previous-text", action="store_true", help=MSG["help_condition"]
    )
    parser.add_argument("--database-url", default=QA_DATABASE_URL, help=MSG["help_database_url"])
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE, help=MSG["help_base_dir"])
    return parser.parse_args(argv)


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    _utf8_console()
    base: Path = args.base_dir.expanduser().resolve()
    config = base / "config"
    try:
        env = qa_env(base, config, args.database_url, args.whisper_condition_on_previous_text)
        check_base_dir(base)
        say(MSG["db_ok"])
        changed = prepare_config(CONFIG_SRC, config)
        say(MSG["config_copied"].format(path=config))
        done = "lesson_required" if changed else "lesson_already"
        say(MSG[done].format(file=JOURNAL_FIELDS, key=REQUIRED_KEY))
        say(MSG["checking"])
        validate_config(env)
        say(MSG["config_ok"])
        say(MSG["env"].format(env=shown_env(env)))
        say(MSG["starting"])
        return run_dev(env, ["--no-browser"] if args.no_browser else [])
    except QaError as exc:
        say(MSG["error"].format(error=exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
