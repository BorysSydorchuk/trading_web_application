"""Unit tests for `scripts/native_pg.py` (pure parts; no install, no DB, no sc.exe)."""

# Messages under test are Ukrainian (Cyrillic look-alike letters are intended).
# ruff: noqa: S105 - fake passwords; Ukrainian messages

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "native_pg.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tj_native_pg", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


npg = _load()

DOCKER_URL = "postgresql+psycopg://journal:docker-pw@127.0.0.1:5432/trading_journal"
DOCKER_TEST = "postgresql+psycopg://journal:docker-pw@127.0.0.1:5432/trading_journal_test"
ENV_TEXT = (
    "﻿# Trading Journal settings\r\n"
    f"DATABASE_URL={DOCKER_URL}\r\n"
    "\r\n"
    "ANTHROPIC_API_KEY='keep me = exactly'\r\n"
    f"TEST_DATABASE_URL={DOCKER_TEST}\r\n"
    "  # indented comment\r\n"
    "LAST=1"
)


def fixed_passwords(*values: str) -> Any:
    it = iter(values)
    return lambda: next(it)


# --------------------------------------------------------------------------- .env editing


def test_set_env_replaces_in_place_and_keeps_other_lines() -> None:
    out = npg.set_env(ENV_TEXT, {"DATABASE_URL": "new", "NEW_KEY": "v"})
    lines = out.split("\r\n")
    assert lines[0] == "﻿# Trading Journal settings"
    assert lines[1] == "DATABASE_URL=new"
    assert lines[3] == "ANTHROPIC_API_KEY='keep me = exactly'"
    assert lines[5] == "  # indented comment"
    assert lines[6] == "LAST=1"  # missing final newline added before the append
    assert lines[7] == "NEW_KEY=v"
    assert out.endswith("\r\n")
    untouched = ENV_TEXT.replace(f"DATABASE_URL={DOCKER_URL}\r\n", "")
    assert all(line in out for line in untouched.splitlines(keepends=True)[:-1])


def test_set_env_drops_duplicate_keys_and_keeps_lf() -> None:
    text = "A=1\nB=2\nA=3\n"
    assert npg.set_env(text, {"A": "x"}) == "A=x\nB=2\n"
    assert npg.set_env("", {"A": "x"}) == "A=x\n"


def test_set_env_no_updates_is_identity() -> None:
    assert npg.set_env(ENV_TEXT, {}) == ENV_TEXT


def test_raw_env_and_values() -> None:
    raw = npg.raw_env(ENV_TEXT)
    assert raw["ANTHROPIC_API_KEY"] == "'keep me = exactly'"
    assert npg.env_values(ENV_TEXT)["ANTHROPIC_API_KEY"] == "keep me = exactly"
    assert raw["DATABASE_URL"] == DOCKER_URL


def test_write_env_text_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    npg.write_env_text(path, ENV_TEXT)
    assert path.read_bytes() == ENV_TEXT.encode("utf-8")
    assert npg.read_env_text(path) == ENV_TEXT
    assert not list(tmp_path.glob("*.tmp"))


# --------------------------------------------------------------------------- secrets / URLs


def test_native_url_encodes_special_characters() -> None:
    password = "p@ss/w:rd#?%"
    url = npg.native_url(password, 5433, "trading_journal")
    assert "p@ss" not in url
    conn = npg.conn_from_url(url)
    assert (conn.host, conn.port, conn.user, conn.database) == (
        "127.0.0.1",
        5433,
        "journal",
        "trading_journal",
    )
    assert conn.password == password


def test_make_password_never_starts_with_dash() -> None:
    tokens = iter(["-bad", "-worse", "good_token"])
    assert npg.make_password(lambda _n: next(tokens)) == "good_token"
    assert len(npg.make_password()) >= 40


def test_secrets_updates() -> None:
    updates = npg.secrets_updates({}, force=False, password=fixed_passwords("app", "super"))
    assert updates == {
        "NATIVE_PG_PORT": "5433",
        "NATIVE_PG_SUPERUSER_PASSWORD": "super",
        "NATIVE_DATABASE_URL": "postgresql+psycopg://journal:app@127.0.0.1:5433/trading_journal",
        "NATIVE_TEST_DATABASE_URL": (
            "postgresql+psycopg://journal:app@127.0.0.1:5433/trading_journal_test"
        ),
    }


def test_secrets_refuses_existing_without_force() -> None:
    with pytest.raises(npg.NativePgError, match="--force"):
        npg.secrets_updates({"NATIVE_PG_SUPERUSER_PASSWORD": "x"}, force=False)
    forced = npg.secrets_updates({"NATIVE_PG_SUPERUSER_PASSWORD": "x"}, force=True)
    assert forced["NATIVE_PG_SUPERUSER_PASSWORD"] != "x"


def test_cmd_secrets_writes_env_and_prints_no_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    path.write_bytes(ENV_TEXT.encode("utf-8"))
    assert npg.main(["secrets"], env_file=path) == 0
    text = path.read_bytes().decode("utf-8")
    values = npg.env_values(text)
    assert text.startswith(ENV_TEXT)
    out = capsys.readouterr().out
    assert values["NATIVE_PG_SUPERUSER_PASSWORD"] not in out
    assert values["NATIVE_DATABASE_URL"] not in out
    assert "docker-pw" not in out
    # second run refuses and leaves the file as it is
    assert npg.main(["secrets"], env_file=path) == 1
    assert path.read_bytes().decode("utf-8") == text
    assert "ПОМИЛКА" in capsys.readouterr().out


def test_install_snippet_reads_password_from_env() -> None:
    snippet = npg.install_snippet()
    assert "NATIVE_PG_SUPERUSER_PASSWORD" in snippet
    assert "--superpassword $pw" in snippet
    assert "--serverport 5433" in snippet
    assert "--servicename postgresql-x64-16" in snippet
    assert "winget install --id PostgreSQL.PostgreSQL.16 -e" in snippet
    assert "Remove-Variable pw" in snippet
    assert "--disable-components pgAdmin,stackbuilder" in snippet
    assert "--enable-components" not in snippet


# --------------------------------------------------------------------------- rotation


def test_rotate_writes_env_only_after_alter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    original = _with_native()
    path.write_bytes(original.encode("utf-8"))
    seen: list[tuple[str, str]] = []

    def alter(new: str) -> None:
        # at ALTER time the .env still holds the old password
        seen.append((new, npg.env_values(npg.read_env_text(path))["NATIVE_PG_SUPERUSER_PASSWORD"]))

    npg.rotate_superuser(path, "super", alter, password=lambda: "rotated")
    assert seen == [("rotated", "super")]
    text = npg.read_env_text(path)
    assert npg.env_values(text)["NATIVE_PG_SUPERUSER_PASSWORD"] == "rotated"
    assert text == npg.set_env(original, {"NATIVE_PG_SUPERUSER_PASSWORD": "rotated"})
    out = capsys.readouterr().out
    assert "rotated" not in out
    assert "%TEMP%" in out


def test_rotate_alter_fails_env_unchanged(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(_with_native().encode("utf-8"))
    before = path.read_bytes()

    def alter(_new: str) -> None:
        raise npg.NativePgError("alter failed")

    with pytest.raises(npg.NativePgError, match="alter failed"):
        npg.rotate_superuser(path, "super", alter, password=lambda: "rotated")
    assert path.read_bytes() == before


def test_rotate_env_write_fails_restores_old_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_bytes(_with_native().encode("utf-8"))
    calls: list[str] = []

    def broken_write(_path: Path, _text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(npg, "write_env_text", broken_write)
    with pytest.raises(npg.NativePgError, match="повернено"):
        npg.rotate_superuser(path, "super", calls.append, password=lambda: "rotated")
    assert calls == ["rotated", "super"]
    assert npg.env_values(npg.read_env_text(path))["NATIVE_PG_SUPERUSER_PASSWORD"] == "super"


def test_configure_parser_rotates_by_default() -> None:
    parser = npg.build_parser()
    assert parser.parse_args(["configure"]).no_rotate is False
    assert parser.parse_args(["configure", "--no-rotate", "--restart"]).no_rotate is True


# --------------------------------------------------------------------------- collation


class FakeCursor:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, statement: Any) -> None:
        text = statement.as_string(None)
        self.db.statements.append(text)
        if self.db.fail_icu and "ICU_LOCALE" in text:
            import psycopg

            raise psycopg.errors.FeatureNotSupported("ICU is not supported in this build")


class FakeDb:
    def __init__(self, fail_icu: bool) -> None:
        self.fail_icu = fail_icu
        self.statements: list[str] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def test_create_database_uses_icu_en_us() -> None:
    db = FakeDb(fail_icu=False)
    npg.create_database(db, "trading_journal")
    assert db.statements == [
        'CREATE DATABASE "trading_journal" OWNER "journal" TEMPLATE template0 '
        "ENCODING 'UTF8' LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LOCALE 'C'"
    ]


def test_create_database_falls_back_without_icu(capsys: pytest.CaptureFixture[str]) -> None:
    db = FakeDb(fail_icu=True)
    npg.create_database(db, "trading_journal_test")
    assert len(db.statements) == 2
    assert db.statements[1] == (
        'CREATE DATABASE "trading_journal_test" OWNER "journal" TEMPLATE template0 '
        "ENCODING 'UTF8'"
    )
    assert "УВАГА" in capsys.readouterr().out


def test_restore_argv_has_no_password() -> None:
    conn = npg.Conn("127.0.0.1", 5433, "journal", "trading_journal", "s3cret")
    argv = npg.restore_argv("pg_restore", conn, Path("x.dump"))
    assert "s3cret" not in " ".join(argv)
    assert {"--no-owner", "--role=journal", "--exit-on-error", "--single-transaction"} <= set(argv)
    assert "s3cret" not in repr(conn)


# --------------------------------------------------------------------------- switch


def _with_native(text: str = ENV_TEXT) -> str:
    updates = npg.secrets_updates({}, force=False, password=fixed_passwords("app", "super"))
    return str(npg.set_env(text, updates))


def test_switch_and_back_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "copy.json"
    marker.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(npg, "COPY_MARKER", marker)
    path = tmp_path / ".env"
    original = _with_native()
    path.write_bytes(original.encode("utf-8"))

    assert npg.main(["switch"], env_file=path) == 0
    switched = npg.env_values(npg.read_env_text(path))
    assert switched["DATABASE_URL"] == switched["NATIVE_DATABASE_URL"]
    assert switched["TEST_DATABASE_URL"] == switched["NATIVE_TEST_DATABASE_URL"]
    assert switched["DOCKER_DATABASE_URL"] == DOCKER_URL
    assert switched["DOCKER_TEST_DATABASE_URL"] == DOCKER_TEST
    assert npg.main(["switch"], env_file=path) == 1  # already native

    assert npg.main(["switch-back"], env_file=path) == 0
    back = npg.read_env_text(path)
    assert npg.env_values(back)["DATABASE_URL"] == DOCKER_URL
    assert npg.env_values(back)["TEST_DATABASE_URL"] == DOCKER_TEST
    # every original line is still there, byte for byte, in the same order
    assert back.startswith(original)
    assert npg.main(["switch-back"], env_file=path) == 1  # already docker

    # second switch keeps the first DOCKER_* values
    assert npg.main(["switch"], env_file=path) == 0
    again = npg.env_values(npg.read_env_text(path))
    assert again["DOCKER_DATABASE_URL"] == DOCKER_URL
    assert (
        list(npg.read_env_text(path).splitlines()).count(f"DOCKER_DATABASE_URL={DOCKER_URL}") == 1
    )


def test_switch_refuses_without_verified_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(npg, "COPY_MARKER", tmp_path / "missing.json")
    path = tmp_path / ".env"
    path.write_bytes(_with_native().encode("utf-8"))
    assert npg.main(["switch"], env_file=path) == 1
    assert npg.env_values(npg.read_env_text(path))["DATABASE_URL"] == DOCKER_URL
    assert npg.main(["switch", "--force"], env_file=path) == 0


def test_switch_requires_native_keys() -> None:
    with pytest.raises(npg.NativePgError, match="NATIVE_DATABASE_URL"):
        npg.switch_updates(npg.raw_env(ENV_TEXT))
    with pytest.raises(npg.NativePgError, match="DOCKER_DATABASE_URL"):
        npg.switch_back_updates(npg.raw_env(ENV_TEXT))


# --------------------------------------------------------------------------- comparison


def snap(**over: Any) -> Any:
    base: dict[str, Any] = {
        "counts": {"trades": 10, "accounts": 2, "alembic_version": 1},
        "checksums": {"trades": "aa", "accounts": "bb", "alembic_version": "cc"},
        "alembic": ("rev1",),
    }
    base.update(over)
    return npg.Snapshot(**base)


def test_compare_identical_ok() -> None:
    result = npg.compare(snap(), snap())
    assert result.ok
    assert all(row.ok for row in result.rows)
    assert any(row.table == "alembic_version" for row in result.rows)


@pytest.mark.parametrize(
    "target",
    [
        {"counts": {"trades": 9, "accounts": 2, "alembic_version": 1}},
        {"checksums": {"trades": "XX", "accounts": "bb", "alembic_version": "cc"}},
        {"counts": {"trades": 10, "alembic_version": 1}},
        {"checksums": {"trades": "aa", "accounts": "bb"}},
        {"alembic": ("rev2",)},
        {"alembic": ()},
    ],
)
def test_compare_detects_differences(target: dict[str, Any]) -> None:
    result = npg.compare(snap(), snap(**target))
    assert not result.ok
    bad = [row for row in result.rows if not row.ok]
    assert len(bad) == 1
    assert "РІЗНИЦЯ" in "\n".join(npg.format_comparison(result))


def test_compare_empty_is_not_ok() -> None:
    empty = npg.Snapshot({}, {}, ())
    assert not npg.Comparison().ok
    result = npg.compare(empty, empty)
    assert not result.ok  # nothing copied is never a "verified" copy


def test_checksum_tables_adds_alembic() -> None:
    assert npg.checksum_tables(["trades", "accounts"]) == ["accounts", "alembic_version", "trades"]


# --------------------------------------------------------------------------- guards / status


def fake_dev(busy: list[int], records: list[object], orphans: list[object]) -> Any:
    return SimpleNamespace(
        APP_PORTS=(8000, 5173),
        RUN_FILE=Path("run.json"),
        busy_ports=lambda _ports: busy,
        read_run_file=lambda _p: records,
        alive_records=lambda r: r,
        find_orphan_workers=lambda: orphans,
    )


def test_ensure_app_stopped() -> None:
    npg.ensure_app_stopped(fake_dev([], [], []))
    with pytest.raises(npg.NativePgError, match="8000"):
        npg.ensure_app_stopped(fake_dev([8000], [], []))
    with pytest.raises(npg.NativePgError, match=r"stop\.bat"):
        npg.ensure_app_stopped(fake_dev([], [], [object()]))


@pytest.mark.parametrize(
    ("url", "label"),
    [
        (DOCKER_URL, "docker (порт 5432)"),
        ("postgresql+psycopg://journal:x@localhost:5433/trading_journal", "native (порт 5433)"),
        ("postgresql+psycopg://journal:x@db.example.com:5432/tj", "інший сервер"),
        ("", "не задано"),
        ("not a url", "некоректний URL"),
    ],
)
def test_describe_active(url: str, label: str) -> None:
    text = npg.describe_active(url, 5433, 5432)
    assert text.startswith(label)
    assert "x@" not in text


def test_native_settings_missing_keys() -> None:
    with pytest.raises(npg.NativePgError, match="secrets"):
        npg.native_settings({})


def test_copy_refuses_native_source(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    text = _with_native()
    raw = npg.raw_env(text)
    path.write_bytes(npg.set_env(text, {"DATABASE_URL": raw["NATIVE_DATABASE_URL"]}).encode())
    with pytest.raises(npg.NativePgError, match="нативний сервер"):
        npg.cmd_copy(path, replace=False)
