"""`.env` editing and pure planning for `scripts/native_pg.py` (stdlib only).

Edits keep every other line byte-for-byte (line endings, a UTF-8 BOM on line 1, comments,
quoting). Values are never printed. Split out of native_pg.py to keep both files small.
"""

# ruff: noqa: RUF001
# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from urllib.parse import quote

HOST = "127.0.0.1"
DEFAULT_NATIVE_PORT = 5433
APP_ROLE = "journal"
APP_DB = "trading_journal"
TEST_DB = "trading_journal_test"
PASSWORD_BYTES = 32
BOM = "﻿"
TMP_SUFFIX = ".native-pg.tmp"  # `.env.native-pg.tmp`: covered by `.env.*` in .gitignore

K_PORT = "NATIVE_PG_PORT"
K_SUPER = "NATIVE_PG_SUPERUSER_PASSWORD"
K_SUPER_NEW = "NATIVE_PG_SUPERUSER_PASSWORD_NEW"  # rotation in progress (see rotate_superuser)
K_NATIVE_URL = "NATIVE_DATABASE_URL"
K_NATIVE_TEST = "NATIVE_TEST_DATABASE_URL"
K_URL = "DATABASE_URL"
K_TEST = "TEST_DATABASE_URL"
K_DOCKER_URL = "DOCKER_DATABASE_URL"
K_DOCKER_TEST = "DOCKER_TEST_DATABASE_URL"
K_MODE = "DB_MODE"  # native | docker (scripts/dev.py resolve_db_mode); set by switch/switch-back
NATIVE_KEYS = (K_PORT, K_SUPER, K_NATIVE_URL, K_NATIVE_TEST)

NATIVE_SERVICE = "postgresql-x64-16"
WINGET_ID = "PostgreSQL.PostgreSQL.16"
# EDB installer options (installbuilder): unattended, no UI, our port and service name.
EDB_OPTIONS = (
    "--mode unattended --unattendedmodeui none --superpassword $pw "
    f"--serverport {DEFAULT_NATIVE_PORT} --servicename {NATIVE_SERVICE} "
    "--disable-components pgAdmin,stackbuilder"
)


class NativePgError(Exception):
    """Readable Ukrainian failure; never contains a password or a URL."""


def say(text: str) -> None:
    print(f"[native-pg] {text}", flush=True)


# --------------------------------------------------------------------------- parsing


def _line_key(line: str) -> str | None:
    stripped = line.lstrip(BOM).strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :]
    key = stripped.partition("=")[0].strip()
    return key or None


def _raw_value(line: str) -> str:
    return line.rstrip("\r\n").partition("=")[2].strip()


def raw_env(text: str) -> dict[str, str]:
    """KEY -> raw value text (quotes kept) of the last assignment, as dotenv reads it."""
    return {
        key: _raw_value(line) for line in text.splitlines() if (key := _line_key(line)) is not None
    }


def unquote_value(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return raw[1:-1]
    return raw


def env_values(text: str) -> dict[str, str]:
    return {key: unquote_value(raw) for key, raw in raw_env(text).items()}


def port_value(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "") or str(default)
    if not raw.isdecimal() or not 0 < int(raw) < 65536:
        raise NativePgError(f"{key} у .env має бути номером порту (1-65535).")
    return int(raw)


# --------------------------------------------------------------------------- editing


def set_env(text: str, updates: Mapping[str, str], remove: Collection[str] = ()) -> str:
    """`text` with each KEY=value set: first assignment replaced in place (its line ending and
    a leading BOM kept), later duplicates and `remove` keys dropped, missing keys appended."""
    ending = "\r\n" if "\r\n" in text else "\n"
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        key = _line_key(line)
        bom = BOM if line.startswith(BOM) else ""
        if key is None or (key not in updates and key not in remove):
            out.append(line)
            continue
        if key in remove or key in seen:
            if bom:
                out.append(bom)
            continue
        seen.add(key)
        body = line.rstrip("\r\n")
        out.append(f"{bom}{key}={updates[key]}{line[len(body) :] or ending}")
    missing = [key for key in updates if key not in seen]
    if missing and out and not out[-1].endswith(("\n", "\r")) and out[-1] != BOM:
        out[-1] += ending
    out.extend(f"{key}={updates[key]}{ending}" for key in missing)
    return "".join(out)


def read_env_text(path: Path) -> str:
    if not path.is_file():
        raise NativePgError(f"Не знайдено {path.name}. Запустіть спершу start.bat (створить .env).")
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise NativePgError(f"Не вдалося прочитати {path.name}: {type(exc).__name__}.") from None


def write_env_text(path: Path, text: str) -> None:
    """Atomic replace; bytes exactly as composed. The temp file never survives a failure."""
    tmp = path.with_name(path.name + TMP_SUFFIX)
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    except OSError as exc:
        raise NativePgError(
            f"Не вдалося записати {path.name}: {exc.strerror or type(exc).__name__}."
        ) from None
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


BACKUP_INFIX = ".bak-"  # `.env.bak-<UTC stamp>`: covered by `.env.*` in .gitignore
KEEP_ENV_BACKUPS = 10


def backup_env_file(path: Path, stamp: str) -> Path:
    """Byte copy of ``path`` to ``<name>.bak-<stamp>`` before a switch; keeps the newest
    KEEP_ENV_BACKUPS. Raises NativePgError (nothing changed) if the copy fails."""
    backup = path.with_name(f"{path.name}{BACKUP_INFIX}{stamp}")
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as exc:
        raise NativePgError(
            f"Не вдалося зберегти копію {path.name}: {exc.strerror or type(exc).__name__}. "
            "Нічого не змінено."
        ) from None
    old = sorted(path.parent.glob(f"{path.name}{BACKUP_INFIX}*"))[:-KEEP_ENV_BACKUPS]
    for extra in old:
        with contextlib.suppress(OSError):
            extra.unlink()
    return backup


def update_env_file(path: Path, updates: Mapping[str, str], remove: Collection[str] = ()) -> None:
    write_env_text(path, set_env(read_env_text(path), updates, remove))


# --------------------------------------------------------------------------- planning


def make_password(token: Callable[[int], str] = secrets.token_urlsafe) -> str:
    """URL-safe random password that never starts with `-` (installer would read an option)."""
    while True:
        value = token(PASSWORD_BYTES)
        if not value.startswith("-"):
            return value


def native_url(password: str, port: int, database: str, user: str = APP_ROLE) -> str:
    return (
        f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{HOST}:{port}/{quote(database, safe='')}"
    )


def secrets_updates(
    current: Mapping[str, str], *, force: bool, password: Callable[[], str] = make_password
) -> dict[str, str]:
    present = [key for key in NATIVE_KEYS if key in current]
    if present and not force:
        raise NativePgError(
            "У .env уже є " + ", ".join(present) + ". Нічого не змінено; щоб згенерувати нові "
            "паролі, додайте --force (лише ДО встановлення PostgreSQL або разом з configure)."
        )
    app_password = password()
    port = DEFAULT_NATIVE_PORT
    return {
        K_PORT: str(port),
        K_SUPER: password(),
        K_NATIVE_URL: native_url(app_password, port, APP_DB),
        K_NATIVE_TEST: native_url(app_password, port, TEST_DB),
    }


def switch_updates(raw: Mapping[str, str]) -> dict[str, str]:
    """DATABASE_URL/TEST_DATABASE_URL -> native; the Docker values kept once as DOCKER_*."""
    for key in (K_NATIVE_URL, K_NATIVE_TEST):
        if not raw.get(key):
            raise NativePgError(f"У .env немає {key}; спершу виконайте команду secrets.")
    for key in (K_URL, K_TEST):
        if not raw.get(key):
            raise NativePgError(f"У .env немає {key}; перемикати нічого.")
    if raw[K_URL] == raw[K_NATIVE_URL] and raw[K_TEST] == raw[K_NATIVE_TEST]:
        if _mode(raw) == "native":
            raise NativePgError("Застосунок уже працює з нативним PostgreSQL; нічого не змінено.")
        return {K_MODE: "native"}  # URLs already native: only the explicit mode is missing
    updates = {K_URL: raw[K_NATIVE_URL], K_TEST: raw[K_NATIVE_TEST], K_MODE: "native"}
    if K_DOCKER_URL not in raw:
        updates[K_DOCKER_URL] = raw[K_URL]
    if K_DOCKER_TEST not in raw:
        updates[K_DOCKER_TEST] = raw[K_TEST]
    return updates


def switch_back_updates(raw: Mapping[str, str]) -> dict[str, str]:
    if not raw.get(K_DOCKER_URL) or not raw.get(K_DOCKER_TEST):
        raise NativePgError(
            f"У .env немає {K_DOCKER_URL}/{K_DOCKER_TEST} (switch ще не виконувався); "
            "нічого не змінено."
        )
    if raw.get(K_URL) == raw[K_DOCKER_URL] and raw.get(K_TEST) == raw[K_DOCKER_TEST]:
        if _mode(raw) == "docker":
            raise NativePgError("Застосунок уже працює з Docker PostgreSQL; нічого не змінено.")
        return {K_MODE: "docker"}
    return {K_URL: raw[K_DOCKER_URL], K_TEST: raw[K_DOCKER_TEST], K_MODE: "docker"}


def _mode(raw: Mapping[str, str]) -> str:
    return unquote_value(raw.get(K_MODE, "")).strip().lower()


def fingerprint(counts: Mapping[str, int], alembic: tuple[str, ...]) -> str:
    """sha256 of the per-table row counts and the alembic revision (copy marker check)."""
    payload = json.dumps({"alembic": list(alembic), "counts": dict(counts)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- superuser password


ROTATION_RERUN = "Повторіть configure: він перевірить, який пароль чинний, і впорядкує .env."


def rotate_superuser(
    env_file: Path, alter: Callable[[str], None], password: Callable[[], str] = make_password
) -> None:
    """New postgres password without a lock-out window:
    1. write it to `.env` as NATIVE_PG_SUPERUSER_PASSWORD_NEW (old key untouched),
    2. ALTER ROLE (`alter` raises NativePgError on failure),
    3. promote: replace the old key, remove _NEW.
    A failure after step 1 leaves _NEW in `.env`; `recover_rotation` settles it next run.
    """
    new_password = password()
    update_env_file(env_file, {K_SUPER_NEW: new_password})
    try:
        alter(new_password)
    except NativePgError as exc:
        raise NativePgError(f"Пароль postgres не змінено: {exc}. {ROTATION_RERUN}") from None
    try:
        update_env_file(env_file, {K_SUPER: new_password}, remove=(K_SUPER_NEW,))
    except NativePgError as exc:
        raise NativePgError(
            f"Пароль postgres змінено, але .env не оновлено ({exc}); новий пароль збережено як "
            f"{K_SUPER_NEW}. {ROTATION_RERUN}"
        ) from None
    say(
        "Пароль суперкористувача postgres змінено і записано в .env (значення не показую). "
        "Старий пароль міг лишитися в журналі інсталятора в %TEMP% (install-postgresql.log, "
        "журнали winget) — він більше не дійсний."
    )


def recover_rotation(
    env_file: Path, env: Mapping[str, str], can_connect: Callable[[str], bool]
) -> None:
    """Settle an interrupted rotation: keep whichever password the server accepts."""
    pending = env.get(K_SUPER_NEW)
    if not pending:
        return
    if can_connect(pending):
        update_env_file(env_file, {K_SUPER: pending}, remove=(K_SUPER_NEW,))
        say("Завершено попередню зміну пароля postgres (новий пароль чинний).")
        return
    if env.get(K_SUPER) and can_connect(env[K_SUPER]):
        update_env_file(env_file, {}, remove=(K_SUPER_NEW,))
        say("Попередня зміна пароля postgres не відбулася; чинний старий пароль.")
        return
    raise NativePgError(
        "Ні старий, ні новий пароль postgres з .env не підходить (або служба не запущена). "
        "Перевірте службу «postgresql-x64-16» у services.msc і повторіть configure."
    )


def install_snippet() -> str:
    """PowerShell for an elevated window in the repo root; the password stays in `$pw`."""
    return "\n".join(
        [
            "$pw = ((Get-Content -Encoding utf8 .env | Where-Object { $_ -match "
            f"'^{K_SUPER}=' }}) -replace '^{K_SUPER}=', '').Trim()",
            'if (-not $pw) { Write-Host "Немає пароля в .env: виконайте secrets"; return }',
            f"winget install --id {WINGET_ID} -e --accept-package-agreements "
            f'--accept-source-agreements --override "{EDB_OPTIONS}"',
            "Remove-Variable pw",
        ]
    )
