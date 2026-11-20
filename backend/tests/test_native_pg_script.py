"""Unit tests for `scripts/native_pg.py` and its helpers `native_pg_env.py` /
`native_pg_compare.py` (no install, no real DB, no sc.exe; DB access is faked)."""

# ruff: noqa: S105, RUF001 - fake passwords; Ukrainian messages

from __future__ import annotations

import fnmatch
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _load() -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))  # native_pg imports its sibling helper modules
    spec = importlib.util.spec_from_file_location("tj_native_pg", SCRIPTS / "native_pg.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


npg = _load()
envm: Any = sys.modules["native_pg_env"]
cmpm: Any = sys.modules["native_pg_compare"]

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


def _with_native(text: str = ENV_TEXT) -> str:
    updates = envm.secrets_updates({}, force=False, password=fixed_passwords("app", "super"))
    return str(envm.set_env(text, updates))


def fake_dev(busy: list[int] | None = None, orphans: list[object] | None = None) -> Any:
    return SimpleNamespace(
        APP_PORTS=(8000, 5173),
        RUN_FILE=Path("run.json"),
        busy_ports=lambda _ports: busy or [],
        read_run_file=lambda _p: [],
        alive_records=lambda r: r,
        find_orphan_workers=lambda: orphans or [],
    )


@pytest.fixture
def stopped_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """App not running; copy marker in tmp. Returns the marker path."""
    monkeypatch.setattr(npg, "load_dev", lambda: fake_dev())
    marker = tmp_path / "copy.json"
    monkeypatch.setattr(npg, "COPY_MARKER", marker)
    return marker


# --------------------------------------------------------------------------- .env editing


def test_set_env_replaces_in_place_and_keeps_other_lines() -> None:
    out = envm.set_env(ENV_TEXT, {"DATABASE_URL": "new", "NEW_KEY": "v"})
    lines = out.split("\r\n")
    assert lines[0] == "﻿# Trading Journal settings"
    assert lines[1] == "DATABASE_URL=new"
    assert lines[3] == "ANTHROPIC_API_KEY='keep me = exactly'"
    assert lines[5] == "  # indented comment"
    assert lines[6] == "LAST=1"  # missing final newline added before the append
    assert lines[7] == "NEW_KEY=v"
    assert out.endswith("\r\n")


def test_bom_on_key_line_one_is_matched_and_kept() -> None:
    text = "﻿DATABASE_URL=old\nOTHER=1\n"
    assert envm.raw_env(text)["DATABASE_URL"] == "old"
    assert envm.set_env(text, {"DATABASE_URL": "new"}) == "﻿DATABASE_URL=new\nOTHER=1\n"
    assert envm.set_env(text, {}, remove=("DATABASE_URL",)) == "﻿OTHER=1\n"
    assert "﻿DATABASE_URL" not in envm.set_env(text, {"DATABASE_URL": "x"}, remove=())[1:]


def test_set_env_drops_duplicates_and_removes_keys() -> None:
    assert envm.set_env("A=1\nB=2\nA=3\n", {"A": "x"}) == "A=x\nB=2\n"
    assert envm.set_env("A=1\nB=2\n", {}, remove=("A",)) == "B=2\n"
    assert envm.set_env("", {"A": "x"}) == "A=x\n"
    assert envm.set_env(ENV_TEXT, {}) == ENV_TEXT


def test_raw_env_and_values() -> None:
    raw = envm.raw_env(ENV_TEXT)
    assert raw["ANTHROPIC_API_KEY"] == "'keep me = exactly'"
    assert envm.env_values(ENV_TEXT)["ANTHROPIC_API_KEY"] == "keep me = exactly"


def test_write_env_text_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    envm.write_env_text(path, ENV_TEXT)
    assert path.read_bytes() == ENV_TEXT.encode("utf-8")
    assert envm.read_env_text(path) == ENV_TEXT
    assert not list(tmp_path.glob("*.tmp"))


def test_write_env_failure_removes_temp_and_is_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"A=1\n")

    def broken_replace(_src: object, _dst: object) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(envm.os, "replace", broken_replace)
    with pytest.raises(envm.NativePgError, match=r"Не вдалося записати \.env"):
        envm.write_env_text(path, "A=2\n")
    assert path.read_bytes() == b"A=1\n"
    assert not (tmp_path / ".env.native-pg.tmp").exists()


def test_temp_file_name_is_gitignored() -> None:
    tmp_name = ".env" + envm.TMP_SUFFIX
    assert tmp_name == ".env.native-pg.tmp"
    patterns = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert any(fnmatch.fnmatch(tmp_name, p.strip()) for p in patterns if p.strip())


@pytest.mark.parametrize("value", ["abc", "0", "70000", "-1"])
def test_port_value_rejects_bad_ports(value: str) -> None:
    with pytest.raises(envm.NativePgError, match="NATIVE_PG_PORT"):
        envm.port_value({"NATIVE_PG_PORT": value}, "NATIVE_PG_PORT", 5433)
    assert envm.port_value({}, "NATIVE_PG_PORT", 5433) == 5433


def test_status_bad_port_is_a_clear_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"NATIVE_PG_PORT=abc\n")
    assert npg.main(["status"], env_file=path) == 1
    assert "NATIVE_PG_PORT" in capsys.readouterr().out


# --------------------------------------------------------------------------- secrets / URLs


def test_native_url_encodes_special_characters() -> None:
    password = "p@ss/w:rd#?%"
    url = envm.native_url(password, 5433, "trading_journal")
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
    assert envm.make_password(lambda _n: next(tokens)) == "good_token"
    assert len(envm.make_password()) >= 40


def test_secrets_updates_and_refusal() -> None:
    updates = envm.secrets_updates({}, force=False, password=fixed_passwords("app", "super"))
    assert updates["NATIVE_PG_SUPERUSER_PASSWORD"] == "super"
    assert updates["NATIVE_DATABASE_URL"].endswith(":app@127.0.0.1:5433/trading_journal")
    with pytest.raises(envm.NativePgError, match="--force"):
        envm.secrets_updates({"NATIVE_PG_SUPERUSER_PASSWORD": "x"}, force=False)


def test_cmd_secrets_writes_env_and_prints_no_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    path.write_bytes(ENV_TEXT.encode("utf-8"))
    assert npg.main(["secrets"], env_file=path) == 0
    text = path.read_bytes().decode("utf-8")
    values = envm.env_values(text)
    assert text.startswith(ENV_TEXT)
    out = capsys.readouterr().out
    assert values["NATIVE_PG_SUPERUSER_PASSWORD"] not in out
    assert "docker-pw" not in out
    assert npg.main(["secrets"], env_file=path) == 1
    assert path.read_bytes().decode("utf-8") == text


def test_install_snippet() -> None:
    snippet = envm.install_snippet()
    assert "--superpassword $pw" in snippet
    assert "--serverport 5433" in snippet
    assert "--servicename postgresql-x64-16" in snippet
    assert "--disable-components pgAdmin,stackbuilder" in snippet
    assert "Remove-Variable pw" in snippet


def test_restore_argv_has_no_password() -> None:
    conn = npg.Conn("127.0.0.1", 5433, "journal", "trading_journal", "s3cret")
    argv = npg.restore_argv("pg_restore", conn, Path("x.dump"))
    assert "s3cret" not in " ".join(argv)
    assert {"--no-owner", "--role=journal", "--exit-on-error", "--single-transaction"} <= set(argv)
    assert "s3cret" not in repr(conn)


def test_restore_error_summary_drops_row_data() -> None:
    stderr = (
        "pg_restore: error: could not execute query: ERROR:  duplicate key value violates "
        'unique constraint "trades_pkey"\n'
        "pg_restore: detail: Key (id)=(42) already exists.\n"
        'CONTEXT:  COPY trades, line 1: "42\tEURUSD\tsecret note"\n'
        "pg_restore: detail: Command was: COPY public.trades (id, note) FROM stdin;\n"
    )
    summary = cmpm.restore_error_summary(stderr)
    assert summary.startswith("pg_restore: error: could not execute query: ERROR:")
    assert "42" not in summary
    assert "secret note" not in summary
    assert "trades_pkey" not in summary  # quoted literals masked
    assert cmpm.restore_error_summary("") == "—"


# --------------------------------------------------------------------------- switch


def _switch_env(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_bytes(_with_native().encode("utf-8"))
    return path


def test_switch_and_back_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    monkeypatch.setattr(npg, "source_fingerprint", lambda _url: "fp1")
    path = _switch_env(tmp_path)
    original = envm.read_env_text(path)
    npg.write_marker(Path("x.dump"), "fp1")

    assert npg.main(["switch"], env_file=path) == 0
    assert not stopped_app.exists()  # marker consumed
    switched = envm.env_values(envm.read_env_text(path))
    assert switched["DATABASE_URL"] == switched["NATIVE_DATABASE_URL"]
    assert switched["DOCKER_DATABASE_URL"] == DOCKER_URL
    assert switched["DOCKER_TEST_DATABASE_URL"] == DOCKER_TEST
    assert npg.main(["switch", "--force"], env_file=path) == 1  # already native

    assert npg.main(["switch-back"], env_file=path) == 0
    back = envm.read_env_text(path)
    assert envm.env_values(back)["DATABASE_URL"] == DOCKER_URL
    assert back.startswith(original)
    assert npg.main(["switch-back"], env_file=path) == 1  # already docker

    assert npg.main(["switch"], env_file=path) == 1  # marker was consumed: copy again
    npg.write_marker(Path("x.dump"), "fp1")
    assert npg.main(["switch"], env_file=path) == 0
    lines = envm.read_env_text(path).splitlines()
    assert lines.count(f"DOCKER_DATABASE_URL={DOCKER_URL}") == 1


def test_switch_refuses_when_source_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    monkeypatch.setattr(npg, "source_fingerprint", lambda _url: "fp-new")
    path = _switch_env(tmp_path)
    npg.write_marker(Path("x.dump"), "fp-old")
    before = path.read_bytes()
    assert npg.main(["switch"], env_file=path) == 1
    assert path.read_bytes() == before
    assert stopped_app.exists()


def test_switch_without_marker_needs_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    monkeypatch.setattr(npg, "source_fingerprint", lambda _url: pytest.fail("not with --force"))
    path = _switch_env(tmp_path)
    assert npg.main(["switch"], env_file=path) == 1
    assert npg.main(["switch", "--force"], env_file=path) == 0


@pytest.mark.parametrize("command", ["switch", "switch-back"])
def test_switch_commands_refuse_while_app_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.setattr(npg, "load_dev", lambda: fake_dev(busy=[8000]))
    path = _switch_env(tmp_path)
    before = path.read_bytes()
    assert npg.main([command, "--force"] if command == "switch" else [command], env_file=path) == 1
    assert path.read_bytes() == before


def test_switch_requires_native_keys() -> None:
    with pytest.raises(envm.NativePgError, match="NATIVE_DATABASE_URL"):
        envm.switch_updates(envm.raw_env(ENV_TEXT))
    with pytest.raises(envm.NativePgError, match="DOCKER_DATABASE_URL"):
        envm.switch_back_updates(envm.raw_env(ENV_TEXT))


def test_fingerprint_changes_with_counts_and_revision() -> None:
    base = envm.fingerprint({"trades": 1, "accounts": 2}, ("r1",))
    assert base == envm.fingerprint({"accounts": 2, "trades": 1}, ("r1",))
    assert base != envm.fingerprint({"trades": 2, "accounts": 2}, ("r1",))
    assert base != envm.fingerprint({"trades": 1, "accounts": 2}, ("r2",))


# --------------------------------------------------------------------------- copy guards


def _native_active_env(tmp_path: Path) -> Path:
    text = _with_native()
    raw = envm.raw_env(text)
    text = envm.set_env(
        text, {"DATABASE_URL": raw["NATIVE_DATABASE_URL"], "DOCKER_DATABASE_URL": DOCKER_URL}
    )
    path = tmp_path / ".env"
    path.write_bytes(text.encode("utf-8"))
    return path


def _forbid(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in names:
        monkeypatch.setattr(npg, name, lambda *_a, _n=name, **_k: pytest.fail(f"{_n} called"))


def test_copy_refuses_when_native_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    _forbid(monkeypatch, "dump_database", "_prepare_target", "_restore")
    path = _native_active_env(tmp_path)
    with pytest.raises(npg.NativePgError, match="--i-know-native-is-active"):
        npg.cmd_copy(path, replace=True)
    with pytest.raises(npg.NativePgError, match="--replace"):
        npg.cmd_copy(path, replace=False, native_active_ok=True)


def test_copy_with_native_active_dumps_native_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    calls: list[str] = []

    def dump(url: str, _port: int, name: str, _label: str) -> Path:
        calls.append(name.rsplit("-", 1)[0] + ("@5433" if ":5433/" in url else "@5432"))
        return tmp_path / f"{name}.dump"

    def prepare(_native: object, replace: bool) -> None:
        calls.append(f"prepare replace={replace}")
        raise npg.NativePgError("stop here")

    monkeypatch.setattr(npg, "dump_database", dump)
    monkeypatch.setattr(npg, "_prepare_target", prepare)
    with pytest.raises(npg.NativePgError, match="stop here"):
        npg.cmd_copy(_native_active_env(tmp_path), replace=True, native_active_ok=True)
    assert calls == [
        "pre-replace-native@5433",
        "pre-native@5432",
        "prepare replace=True",
    ]


def test_copy_stops_when_native_dump_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    def dump(_url: str, _port: int, name: str, _label: str) -> Path:
        raise npg.NativePgError(f"{name} failed")

    monkeypatch.setattr(npg, "dump_database", dump)
    _forbid(monkeypatch, "_prepare_target", "_restore")
    with pytest.raises(npg.NativePgError, match="pre-replace-native"):
        npg.cmd_copy(_native_active_env(tmp_path), replace=True, native_active_ok=True)


def test_copy_refuses_native_source(tmp_path: Path, stopped_app: Path) -> None:
    text = _with_native()
    raw = envm.raw_env(text)
    path = tmp_path / ".env"
    path.write_bytes(
        envm.set_env(text, {"DOCKER_DATABASE_URL": raw["NATIVE_DATABASE_URL"]}).encode()
    )
    with pytest.raises(npg.NativePgError, match="нативний сервер"):
        npg.cmd_copy(path, replace=False)


def test_ensure_app_stopped() -> None:
    npg.ensure_app_stopped(fake_dev())
    with pytest.raises(npg.NativePgError, match="8000"):
        npg.ensure_app_stopped(fake_dev(busy=[8000]))
    with pytest.raises(npg.NativePgError, match=r"stop\.bat"):
        npg.ensure_app_stopped(fake_dev(orphans=[object()]))


# --------------------------------------------------------------------------- rotation


def test_rotate_writes_new_key_before_alter_then_promotes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _switch_env(tmp_path)
    original = envm.read_env_text(path)
    seen: list[dict[str, str]] = []

    def alter(new: str) -> None:
        assert new == "rotated"
        seen.append(envm.env_values(envm.read_env_text(path)))

    envm.rotate_superuser(path, alter, password=lambda: "rotated")
    assert seen[0]["NATIVE_PG_SUPERUSER_PASSWORD_NEW"] == "rotated"  # saved before ALTER
    assert seen[0]["NATIVE_PG_SUPERUSER_PASSWORD"] == "super"
    text = envm.read_env_text(path)
    assert text == envm.set_env(original, {"NATIVE_PG_SUPERUSER_PASSWORD": "rotated"})
    out = capsys.readouterr().out
    assert "rotated" not in out
    assert "%TEMP%" in out


def test_rotate_alter_fails_keeps_old_and_pending(tmp_path: Path) -> None:
    path = _switch_env(tmp_path)

    def alter(_new: str) -> None:
        raise envm.NativePgError("server said no")

    with pytest.raises(envm.NativePgError, match="configure"):
        envm.rotate_superuser(path, alter, password=lambda: "rotated")
    values = envm.env_values(envm.read_env_text(path))
    assert values["NATIVE_PG_SUPERUSER_PASSWORD"] == "super"
    assert values["NATIVE_PG_SUPERUSER_PASSWORD_NEW"] == "rotated"


def test_rotate_promote_fails_new_password_still_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _switch_env(tmp_path)
    real_update = envm.update_env_file

    def update(p: Path, updates: dict[str, str], remove: tuple[str, ...] = ()) -> None:
        if remove:
            raise envm.NativePgError("disk full")
        real_update(p, updates, remove)

    monkeypatch.setattr(envm, "update_env_file", update)
    with pytest.raises(envm.NativePgError, match="NATIVE_PG_SUPERUSER_PASSWORD_NEW"):
        envm.rotate_superuser(path, lambda _pw: None, password=lambda: "rotated")
    assert envm.env_values(envm.read_env_text(path))["NATIVE_PG_SUPERUSER_PASSWORD_NEW"] == (
        "rotated"
    )


@pytest.mark.parametrize(
    ("accepted", "expected_super"),
    [({"new"}, "new"), ({"super"}, "super")],
)
def test_recover_rotation(tmp_path: Path, accepted: set[str], expected_super: str) -> None:
    path = tmp_path / ".env"
    path.write_bytes(
        envm.set_env(_with_native(), {"NATIVE_PG_SUPERUSER_PASSWORD_NEW": "new"}).encode()
    )
    env = envm.env_values(envm.read_env_text(path))
    envm.recover_rotation(path, env, lambda pw: pw in accepted)
    values = envm.env_values(envm.read_env_text(path))
    assert values["NATIVE_PG_SUPERUSER_PASSWORD"] == expected_super
    assert "NATIVE_PG_SUPERUSER_PASSWORD_NEW" not in values


def test_recover_rotation_neither_works_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(
        envm.set_env(_with_native(), {"NATIVE_PG_SUPERUSER_PASSWORD_NEW": "new"}).encode()
    )
    before = path.read_bytes()
    env = envm.env_values(envm.read_env_text(path))
    with pytest.raises(envm.NativePgError, match=r"services.msc"):
        envm.recover_rotation(path, env, lambda _pw: False)
    assert path.read_bytes() == before
    envm.recover_rotation(path, {}, lambda _pw: pytest.fail("nothing pending"))


def test_configure_parser_flags() -> None:
    parser = npg.build_parser()
    assert parser.parse_args(["configure"]).no_rotate is False
    assert parser.parse_args(["configure", "--no-rotate"]).no_rotate is True
    args = parser.parse_args(["copy", "--replace", "--i-know-native-is-active"])
    assert args.i_know_native_is_active is True


# --------------------------------------------------------------------------- SQL with fakes


class FakeCursor:
    def __init__(self, db: FakeDb) -> None:
        self.db = db

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, statement: Any, _params: object = None) -> None:
        text = statement if isinstance(statement, str) else statement.as_string(None)
        self.db.statements.append(text)
        if any(marker in text for marker in self.db.fail_on):
            import psycopg

            raise psycopg.errors.FeatureNotSupported("not supported here")

    def fetchone(self) -> tuple[Any, ...]:
        return (self.db.fetch,)


class FakeDb:
    def __init__(self, fail_on: tuple[str, ...] = (), fetch: Any = 0) -> None:
        self.fail_on = fail_on
        self.fetch = fetch
        self.statements: list[str] = []
        self.pgconn = SimpleNamespace(
            encrypt_password=lambda pw, user, algo: b"SCRAM-SHA-256$4096:fake-" + user
        )

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def opener(db: FakeDb) -> Any:
    @contextmanager
    def open_db(_name: str) -> Iterator[FakeDb]:
        yield db

    return open_db


def test_role_password_is_sent_as_scram_verifier() -> None:
    db = FakeDb()
    npg.set_role_password(db, "journal", "plain-secret", create=True)
    npg.set_role_password(db, "postgres", "plain-secret-2")
    assert db.statements == [
        "CREATE ROLE \"journal\" WITH LOGIN CREATEDB PASSWORD 'SCRAM-SHA-256$4096:fake-journal'",
        "ALTER ROLE \"postgres\" WITH PASSWORD 'SCRAM-SHA-256$4096:fake-postgres'",
    ]
    assert not any("plain-secret" in s for s in db.statements)


def test_create_database_icu_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(npg, "text_semantics_ok", lambda _open, _name: True)
    db = FakeDb()
    npg.create_database(db, "trading_journal", opener(db))
    assert db.statements == [
        'CREATE DATABASE "trading_journal" OWNER "journal" TEMPLATE template0 '
        "ENCODING 'UTF8' LOCALE_PROVIDER icu ICU_LOCALE 'en-US' LOCALE 'C'"
    ]


def test_create_database_recreates_when_cyrillic_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    results = iter([False, True])
    monkeypatch.setattr(npg, "text_semantics_ok", lambda _open, _name: next(results))
    db = FakeDb()
    npg.create_database(db, "trading_journal", opener(db))
    assert db.statements[1] == 'DROP DATABASE "trading_journal" WITH (FORCE)'
    assert "LC_COLLATE 'C' LC_CTYPE 'en-US'" in db.statements[2]
    assert "кирилиці" in capsys.readouterr().out


def test_create_database_falls_back_without_icu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(npg, "text_semantics_ok", lambda _open, _name: True)
    db = FakeDb(fail_on=("ICU_LOCALE",))
    npg.create_database(db, "trading_journal_test", opener(db))
    assert db.statements[-1] == (
        'CREATE DATABASE "trading_journal_test" OWNER "journal" TEMPLATE template0 '
        "ENCODING 'UTF8'"
    )


def test_create_database_gives_up_with_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(npg, "text_semantics_ok", lambda _open, _name: False)
    db = FakeDb()
    with pytest.raises(npg.NativePgError, match="кирилицею"):
        npg.create_database(db, "trading_journal", opener(db))


def test_existing_non_empty_db_with_broken_cyrillic_is_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(npg, "database_exists", lambda _db, _name: True)
    monkeypatch.setattr(npg, "text_semantics_ok", lambda _open, _name: False)
    db = FakeDb(fetch=12)  # public_relation_count
    with pytest.raises(npg.NativePgError, match="не порожня"):
        npg.ensure_database(db, "trading_journal", opener(db))
    assert not any("DROP" in s for s in db.statements)


def test_text_smoke_sql() -> None:
    db = FakeDb(fetch=True)
    assert npg.text_semantics_ok(opener(db), "x") is True
    assert db.statements == [npg.TEXT_SMOKE_SQL]
    assert "lower('ЖУРНАЛ Є') = 'журнал є'" in npg.TEXT_SMOKE_SQL
    assert "ILIKE '%журнал%'" in npg.TEXT_SMOKE_SQL


# --------------------------------------------------------------------------- comparison


def snap(**over: Any) -> Any:
    base: dict[str, Any] = {
        "counts": {"trades": 10, "accounts": 2, "alembic_version": 1},
        "checksums": {"trades": "aa", "accounts": "bb", "alembic_version": "cc"},
        "alembic": ("rev1",),
    }
    base.update(over)
    return cmpm.Snapshot(**base)


def test_compare_identical_ok() -> None:
    result = cmpm.compare(snap(), snap())
    assert result.ok
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
    result = cmpm.compare(snap(), snap(**target))
    assert not result.ok
    assert len([row for row in result.rows if not row.ok]) == 1
    assert "РІЗНИЦЯ" in "\n".join(cmpm.format_comparison(result))


def test_compare_empty_is_not_ok() -> None:
    empty = cmpm.Snapshot({}, {}, ())
    assert not cmpm.Comparison().ok
    assert not cmpm.compare(empty, empty).ok


def test_checksum_tables_adds_alembic() -> None:
    assert cmpm.checksum_tables(["trades", "accounts"]) == [
        "accounts",
        "alembic_version",
        "trades",
    ]


# --------------------------------------------------------------------------- status helpers


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


# --------------------------------------------------------------------------- DB_MODE


def test_switch_and_back_write_db_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    path = _switch_env(tmp_path)
    assert npg.main(["switch", "--force"], env_file=path) == 0
    assert envm.env_values(envm.read_env_text(path))["DB_MODE"] == "native"
    assert npg.main(["switch-back"], env_file=path) == 0
    text = envm.read_env_text(path)
    assert envm.env_values(text)["DB_MODE"] == "docker"
    assert text.count("DB_MODE=") == 1  # replaced in place, not appended twice


def test_switch_on_native_urls_without_mode_only_writes_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stopped_app: Path
) -> None:
    """Owner switched before DB_MODE existed: `switch` adds DB_MODE=native, no copy needed."""
    monkeypatch.setattr(npg, "source_fingerprint", lambda _url: pytest.fail("no copy check"))
    path = _native_active_env(tmp_path)
    text = envm.read_env_text(path)
    native_test = envm.env_values(text)["NATIVE_TEST_DATABASE_URL"]
    text = envm.set_env(
        text, {"TEST_DATABASE_URL": native_test, "DOCKER_TEST_DATABASE_URL": DOCKER_TEST}
    )
    path.write_bytes(text.encode("utf-8"))
    before = envm.env_values(text)
    assert npg.main(["switch"], env_file=path) == 0
    after = envm.env_values(envm.read_env_text(path))
    assert after["DB_MODE"] == "native"
    assert {k: v for k, v in after.items() if k != "DB_MODE"} == before
    assert npg.main(["switch"], env_file=path) == 1  # now really already native


def test_status_prints_resolved_mode_and_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dev = npg.load_dev()
    monkeypatch.setattr(dev, "tcp_reachable", lambda *_a, **_k: False)
    monkeypatch.setattr(dev, "native_service_state", lambda _s: None)
    monkeypatch.setattr(npg, "load_dev", lambda: dev)
    path = _native_active_env(tmp_path)
    assert npg.main(["status"], env_file=path) == 0
    out = capsys.readouterr().out
    assert "Режим БД: native (127.0.0.1:5433)" in out
    assert "DB_MODE у .env: не задано" in out
    path.write_bytes(envm.set_env(envm.read_env_text(path), {"DB_MODE": "docker"}).encode())
    assert npg.main(["status"], env_file=path) == 0
    out = capsys.readouterr().out
    assert "Режим БД: docker (127.0.0.1:5433)" in out
    assert "DB_MODE у .env: docker" in out
    assert ":app@" not in out  # host/port only, never the URL
