"""M5 launcher safety checks; subprocesses are stubbed and no DB is contacted."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.config import REPO_ROOT

QA_DB = "trading_journal_qa_m5"


@pytest.fixture
def qa(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "tj_qa_m5", REPO_ROOT / "scripts" / "qa_live_check_m5.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _forbid(monkeypatch: pytest.MonkeyPatch, qa: ModuleType, *names: str) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("must refuse before side effects")

    for name in names:
        monkeypatch.setattr(qa, name, forbidden)


def _record(seen: list[Any], value: Any, result: Any = None) -> Any:
    seen.append(value)
    return result


SIDE_EFFECTS = (
    "check_nothing_running",
    "prepare_config",
    "validate_config",
    "ensure_database",
    "run_dev",
    "run_api",
)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:sensitive@remote.example/trading_journal_qa_m5",
        "postgresql+psycopg://u:sensitive@127.0.0.1/trading_journal",
        "postgresql+psycopg://u:sensitive@127.0.0.1/trading_journal_test",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m4",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m5x",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m5?host=remote",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m5#extra",
        "sqlite:///trading_journal_qa_m5",
        "postgresql+psycopg://[broken",
        "postgresql+psycopg://u:sensitive@localhost:bad/trading_journal_qa_m5",
        "postgresql://u:sensitive@localhost/trading_journal_qa_m5",
    ],
)
@pytest.mark.parametrize("mode", [[], ["--prepare-only"], ["--api-only"]])
def test_bad_database_refused_before_files_or_processes(
    qa: ModuleType,
    url: str,
    mode: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _forbid(monkeypatch, qa, *SIDE_EFFECTS)
    base = tmp_path / "qa"
    assert qa.main([*mode, "--database-url", url, "--base-dir", str(base)]) == 1
    assert not base.exists()
    assert "sensitive" not in capsys.readouterr().out


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_exact_local_database_accepted(qa: ModuleType, host: str) -> None:
    qa.check_qa_database(f"postgresql+psycopg://u:p@{host}:5432/{QA_DB}")


def test_default_url_is_the_m5_database(qa: ModuleType) -> None:
    assert qa.QA_DB_NAME == QA_DB
    assert qa.QA_DATABASE_URL.endswith(f"@127.0.0.1:5432/{QA_DB}")
    qa.check_qa_database(qa.QA_DATABASE_URL)


def test_environment_is_offline_and_isolated(qa: ModuleType, tmp_path: Path) -> None:
    original = {
        "ANTHROPIC_API_KEY": "sentinel",
        "anthropic_api_key": "lowercase",
        "MT5_SOURCE": "real",
        "mt5_source": "real",
        "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1/trading_journal",
        "KEEP": "yes",
    }
    env = qa.qa_env(tmp_path, tmp_path / "config", qa.QA_DATABASE_URL, environ=original)
    assert original["ANTHROPIC_API_KEY"] == "sentinel"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert "anthropic_api_key" not in env
    assert "mt5_source" not in env
    assert env["MT5_SOURCE"] == "fixture:backend/tests/fixtures/mt5/calculator_qa.json"
    assert env[f"MT5_PASSWORD_{qa.QA_LOGIN}"]
    assert env["DATABASE_URL"] == qa.QA_DATABASE_URL
    assert env["DATA_DIR"] == str(tmp_path / "data")
    assert env["LOG_DIR"] == str(tmp_path / "logs")
    assert env["CONFIG_DIR"] == str(tmp_path / "config")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["KEEP"] == "yes"
    shown = qa.shown_env(env)
    assert "sentinel" not in shown
    assert "journal:journal" not in shown


def test_fixture_is_synthetic_and_matches_the_login(qa: ModuleType) -> None:
    path = REPO_ROOT / qa.FIXTURE_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "SYNTHETIC" in data["description"]
    assert data["account"]["login"] == qa.QA_LOGIN
    names = {s["name"] for s in data["symbols"]}
    assert {"EURUSD", "GBPUSD", "XAUUSD", "GER40.cash"} <= names
    # Three symbols have margins for both directions, GER40.cash has none.
    assert set(data["margins"]) == {"EURUSD", "GBPUSD", "XAUUSD"}
    assert all(set(v) == {"buy", "sell"} for v in data["margins"].values())


def test_config_copy_is_byte_identical_and_keeps_data(qa: ModuleType, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    kept = data / "kept.ogg"
    kept.write_bytes(b"audio")
    target = tmp_path / "config"
    qa.prepare_config(REPO_ROOT / "config", target)
    qa.prepare_config(REPO_ROOT / "config", target)
    for source in (REPO_ROOT / "config").iterdir():
        if source.is_file():
            assert (target / source.name).read_bytes() == source.read_bytes()
    assert (target / qa.COPY_MARKER).is_file()
    assert kept.read_bytes() == b"audio"


def test_foreign_or_m4_config_is_never_deleted(qa: ModuleType, tmp_path: Path) -> None:
    target = tmp_path / "config"
    target.mkdir()
    existing = target / "rules.yaml"
    existing.write_bytes(b"private rules")
    with pytest.raises(qa.QaError):
        qa.prepare_config(REPO_ROOT / "config", target)
    (target / ".tj-qa-m4-copy").write_text("scripts/qa_live_check_m4.py\n", encoding="utf-8")
    with pytest.raises(qa.QaError):
        qa.prepare_config(REPO_ROOT / "config", target)
    assert existing.read_bytes() == b"private rules"


@pytest.mark.parametrize("base", [REPO_ROOT, REPO_ROOT / "config", REPO_ROOT.parent])
def test_repository_paths_refused_before_copy(
    qa: ModuleType, base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid(monkeypatch, qa, *SIDE_EFFECTS)
    assert qa.main(["--base-dir", str(base)]) == 1


def test_running_app_refused_before_db_and_launch(
    qa: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """dev.py stops a previous run itself: never let it touch an app we did not start."""
    fake_dev = SimpleNamespace(
        busy_ports=lambda ports: [8000],
        RUN_FILE=tmp_path / "none.json",
        read_run_file=lambda path: [],
        alive_records=lambda records: [],
        find_orphan_workers=lambda: [],
    )
    monkeypatch.setattr(qa, "load_dev", lambda: fake_dev)
    _forbid(monkeypatch, qa, "prepare_config", "validate_config", "ensure_database", "run_dev")
    assert qa.main(["--no-browser", "--base-dir", str(tmp_path / "qa")]) == 1
    assert "8000" in capsys.readouterr().out


@pytest.mark.parametrize(
    "state",
    [
        {"alive_records": lambda records: ["launcher"]},
        {"find_orphan_workers": lambda: ["worker"]},
    ],
)
def test_running_launcher_or_worker_refused(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]
) -> None:
    values: dict[str, Any] = {
        "busy_ports": lambda ports: [],
        "RUN_FILE": tmp_path / "none.json",
        "read_run_file": lambda path: [],
        "alive_records": lambda records: [],
        "find_orphan_workers": lambda: [],
    }
    values.update(state)
    monkeypatch.setattr(qa, "load_dev", lambda: SimpleNamespace(**values))
    with pytest.raises(qa.QaError):
        qa.check_nothing_running([8000, 5173])


def test_nothing_running_passes(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[int]] = []
    fake_dev = SimpleNamespace(
        busy_ports=lambda ports: _record(seen, list(ports), []),
        RUN_FILE=tmp_path / "none.json",
        read_run_file=lambda path: [],
        alive_records=lambda records: [],
        find_orphan_workers=lambda: [],
    )
    monkeypatch.setattr(qa, "load_dev", lambda: fake_dev)
    qa.check_nothing_running([8000, 5173])
    assert seen == [[8000, 5173]]


def test_create_db_script_never_destroys(qa: ModuleType) -> None:
    code = qa.CREATE_DB_SCRIPT.upper()
    for word in ("DROP", "TRUNCATE", "DELETE", "ALTER", "TEMPLATE"):
        assert word not in code
    assert "CREATE DATABASE" in code


def test_ensure_database_passes_url_only_via_env(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((argv, kwargs["env"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(qa.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(qa.subprocess, "run", fake_run)
    env = qa.qa_env(tmp_path, tmp_path / "config", qa.QA_DATABASE_URL, environ={})
    qa.ensure_database(env)
    ((argv, child_env),) = calls
    assert child_env["DATABASE_URL"] == qa.QA_DATABASE_URL
    assert all("journal:journal" not in part for part in argv)


def test_ensure_database_failure_is_a_qa_error(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qa.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(qa.subprocess, "run", lambda argv, **kwargs: SimpleNamespace(returncode=1))
    env = qa.qa_env(tmp_path, tmp_path / "config", qa.QA_DATABASE_URL, environ={})
    with pytest.raises(qa.QaError):
        qa.ensure_database(env)


class _FakeConn:
    def __init__(self, exists: bool) -> None:
        self.exists = exists
        self.sql: list[str] = []

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: Any, params: Any = None) -> SimpleNamespace:
        self.sql.append(query if isinstance(query, str) else query.as_string(None))
        return SimpleNamespace(fetchone=lambda: (1,) if self.exists else None)


def _run_create_script(
    qa: ModuleType, monkeypatch: pytest.MonkeyPatch, url: str, conn: _FakeConn | None
) -> tuple[int, list[dict[str, Any]]]:
    import psycopg

    connects: list[dict[str, Any]] = []

    def fake_connect(**kwargs: Any) -> _FakeConn:
        connects.append(kwargs)
        if conn is None:
            raise AssertionError("must not connect")
        return conn

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(SystemExit) as exc:
        exec(compile(qa.CREATE_DB_SCRIPT, "<create-db>", "exec"), {"__name__": "__main__"})  # noqa: S102
    code = exc.value.code
    return (0 if code is None else int(code)), connects


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@127.0.0.1/trading_journal",
        "postgresql+psycopg://u:p@remote.example/trading_journal_qa_m5",
        "postgresql+psycopg://u:p@127.0.0.1/trading_journal_qa_m5?host=x",
    ],
)
def test_create_script_refuses_other_targets(
    qa: ModuleType, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    code, connects = _run_create_script(qa, monkeypatch, url, None)
    assert code != 0
    assert connects == []


@pytest.mark.parametrize("exists", [True, False])
def test_create_script_creates_only_when_missing(
    qa: ModuleType, monkeypatch: pytest.MonkeyPatch, exists: bool
) -> None:
    conn = _FakeConn(exists)
    url = f"postgresql+psycopg://u:p@127.0.0.1:5432/{QA_DB}"
    code, connects = _run_create_script(qa, monkeypatch, url, conn)
    assert code == 0
    (kwargs,) = connects
    assert kwargs["dbname"] == "postgres"
    assert kwargs["autocommit"] is True
    created = [q for q in conn.sql if "CREATE DATABASE" in q.upper()]
    assert len(created) == (0 if exists else 1)


def test_main_validates_creates_then_launches_offline(
    qa: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(qa, "check_nothing_running", lambda ports: seen.append("ports"))

    def validate(env: dict[str, str]) -> None:
        assert env["ANTHROPIC_API_KEY"] == ""
        assert Path(env["CONFIG_DIR"]).is_dir()
        seen.append("validate")

    def ensure(env: dict[str, str]) -> None:
        assert env["DATABASE_URL"] == qa.QA_DATABASE_URL
        seen.append("ensure_db")

    def launch(env: dict[str, str], args: list[str]) -> int:
        assert args == ["--no-browser"]
        assert env["ANTHROPIC_API_KEY"] == ""
        seen.append("launch")
        return 7

    monkeypatch.setattr(qa, "validate_config", validate)
    monkeypatch.setattr(qa, "ensure_database", ensure)
    monkeypatch.setattr(qa, "run_dev", launch)
    assert qa.main(["--no-browser", "--base-dir", str(tmp_path / "qa")]) == 7
    assert seen == ["ports", "validate", "ensure_db", "launch"]
    assert QA_DB in capsys.readouterr().out


def test_prepare_only_migrates_without_port_check(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    _forbid(monkeypatch, qa, "check_nothing_running", "run_api")
    monkeypatch.setattr(qa, "validate_config", lambda env: seen.append("validate"))
    monkeypatch.setattr(qa, "ensure_database", lambda env: seen.append("ensure_db"))
    monkeypatch.setattr(qa, "run_dev", lambda env, args: _record(seen, args, 0))
    assert qa.main(["--prepare-only", "--base-dir", str(tmp_path / "qa")]) == 0
    assert seen == ["validate", "ensure_db", ["--ensure-db"]]


def test_api_only_migrates_then_starts_api_without_worker(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(qa, "check_nothing_running", lambda ports: seen.append(list(ports)))
    monkeypatch.setattr(qa, "validate_config", lambda env: seen.append("validate"))
    monkeypatch.setattr(qa, "ensure_database", lambda env: seen.append("ensure_db"))
    monkeypatch.setattr(qa, "run_dev", lambda env, args: _record(seen, args, 0))

    def api(env: dict[str, str], port: int) -> int:
        assert env["ANTHROPIC_API_KEY"] == ""
        seen.append(("api", port))
        return 0

    monkeypatch.setattr(qa, "run_api", api)
    assert qa.main(["--api-only", "--base-dir", str(tmp_path / "qa")]) == 0
    port = qa.API_ONLY_PORT
    assert port not in (8000, 5173)
    assert seen == [[port], "validate", "ensure_db", ["--ensure-db"], ("api", port)]


def test_load_dev_really_loads_the_launcher(qa: ModuleType) -> None:
    """Not stubbed: dev.py defines dataclasses, so it must be importable this way."""
    dev = qa.load_dev()
    assert dev.APP_PORTS == qa.APP_PORTS
    for name in ("busy_ports", "alive_records", "read_run_file", "find_orphan_workers"):
        assert callable(getattr(dev, name))
