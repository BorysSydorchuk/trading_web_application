"""M6 launcher safety checks; subprocesses and HTTP are stubbed and no DB is contacted."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.config import REPO_ROOT
from tests.fixtures.mt5 import build_digest_qa, digest_qa_seed
from tests.fixtures.mt5.build_fixtures import render

QA_DB = "trading_journal_qa_m6"
NORMAL_PORTS = (8000, 5173)


@pytest.fixture
def qa(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "tj_qa_m6", REPO_ROOT / "scripts" / "qa_live_check_m6.py"
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
    "check_ports_free",
    "prepare_config",
    "validate_config",
    "ensure_database",
    "run_dev",
    "run_seed",
    "start_servers",
    "write_clock",
)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:sensitive@remote.example/trading_journal_qa_m6",
        "postgresql+psycopg://u:sensitive@127.0.0.1/trading_journal",
        "postgresql+psycopg://u:sensitive@127.0.0.1/trading_journal_test",
        "postgresql+psycopg://u:sensitive@127.0.0.1/trading_journal_qa_m6_test",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m5",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m6x",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m6?host=remote",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m6#extra",
        "sqlite:///trading_journal_qa_m6",
        "postgresql+psycopg://[broken",
        "postgresql+psycopg://u:sensitive@localhost:bad/trading_journal_qa_m6",
        "postgresql://u:sensitive@localhost/trading_journal_qa_m6",
    ],
)
@pytest.mark.parametrize("mode", [[], ["--prepare-only"], ["--seed"]])
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


def test_default_url_is_the_m6_database(qa: ModuleType) -> None:
    assert qa.QA_DB_NAME == QA_DB
    assert qa.QA_DATABASE_URL.endswith(f"@127.0.0.1:5432/{QA_DB}")
    qa.check_qa_database(qa.QA_DATABASE_URL)


def test_own_ports_never_the_normal_app_ports(qa: ModuleType) -> None:
    """Borys's app keeps running on 8000/5173 during the QA: the QA app must not use them."""
    assert qa.API_PORT not in NORMAL_PORTS
    assert qa.WEB_PORT not in NORMAL_PORTS
    assert qa.API_PORT != qa.WEB_PORT


def test_environment_is_offline_and_isolated(qa: ModuleType, tmp_path: Path) -> None:
    original = {
        "ANTHROPIC_API_KEY": "sentinel",
        "anthropic_api_key": "lowercase",
        "MT5_SOURCE": "real",
        "mt5_source": "real",
        "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1/trading_journal",
        "TJ_API_PORT": "8000",
        "KEEP": "yes",
    }
    env = qa.qa_env(tmp_path, tmp_path / "config", qa.QA_DATABASE_URL, environ=original)
    assert original["ANTHROPIC_API_KEY"] == "sentinel"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert "anthropic_api_key" not in env
    assert "mt5_source" not in env
    assert env["MT5_SOURCE"] == "fixture:backend/tests/fixtures/mt5/digest_qa.json"
    assert env["DATABASE_URL"] == qa.QA_DATABASE_URL
    assert env["DATA_DIR"] == str(tmp_path / "data")
    assert env["LOG_DIR"] == str(tmp_path / "logs")
    assert env["CONFIG_DIR"] == str(tmp_path / "config")
    assert env["TJ_API_PORT"] == str(qa.API_PORT)
    assert env["TJ_WEB_PORT"] == str(qa.WEB_PORT)
    assert env["TJ_QA_CLOCK_FILE"] == str(tmp_path / qa.CLOCK_FILE)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["KEEP"] == "yes"
    shown = qa.shown_env(env)
    assert "sentinel" not in shown
    assert "journal:journal" not in shown


def test_busy_own_port_is_refused(qa: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dev = SimpleNamespace(port_in_use=lambda port: port == qa.WEB_PORT)
    monkeypatch.setattr(qa, "load_dev", lambda: fake_dev)
    with pytest.raises(qa.QaError, match=str(qa.WEB_PORT)):
        qa.check_ports_free([qa.API_PORT, qa.WEB_PORT])


def test_normal_app_ports_are_refused_even_when_free(
    qa: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qa, "load_dev", lambda: SimpleNamespace(port_in_use=lambda port: False))
    for port in NORMAL_PORTS:
        with pytest.raises(qa.QaError):
            qa.check_ports_free([port])


def test_free_ports_pass(qa: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def in_use(port: int) -> bool:
        seen.append(port)
        return False

    monkeypatch.setattr(qa, "load_dev", lambda: SimpleNamespace(port_in_use=in_use))
    qa.check_ports_free([qa.API_PORT, qa.WEB_PORT])
    assert seen == [qa.API_PORT, qa.WEB_PORT]


def test_busy_ports_refused_before_db_and_launch(
    qa: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(qa, "load_dev", lambda: SimpleNamespace(port_in_use=lambda port: True))
    _forbid(
        monkeypatch,
        qa,
        "prepare_config",
        "validate_config",
        "ensure_database",
        "run_dev",
        "start_servers",
    )
    assert qa.main(["--base-dir", str(tmp_path / "qa")]) == 1
    assert str(qa.API_PORT) in capsys.readouterr().out


def test_main_runs_dev_only_to_migrate_then_own_servers(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dev.py without --ensure-db would stop the running normal app: never call it so."""
    seen: list[Any] = []
    monkeypatch.setattr(qa, "check_ports_free", lambda ports: seen.append(list(ports)))
    monkeypatch.setattr(qa, "validate_config", lambda env: seen.append("validate"))
    monkeypatch.setattr(qa, "ensure_database", lambda env: seen.append("ensure_db"))

    def dev(env: dict[str, str], args: list[str]) -> int:
        assert args == ["--ensure-db"]
        assert env["ANTHROPIC_API_KEY"] == ""
        seen.append("migrate")
        return 0

    def servers(env: dict[str, str], base: Path) -> int:
        assert env["TJ_API_PORT"] == str(qa.API_PORT)
        assert (base / qa.CLOCK_FILE).read_text(encoding="utf-8").strip() == (
            "2026-11-13T15:00:00Z"
        )
        seen.append("servers")
        return 0

    monkeypatch.setattr(qa, "run_dev", dev)
    monkeypatch.setattr(qa, "start_servers", servers)
    base = tmp_path / "qa"
    assert qa.main(["--base-dir", str(base), "--now", "2026-11-13T15:00:00Z"]) == 0
    assert seen == [[qa.API_PORT, qa.WEB_PORT], "validate", "ensure_db", "migrate", "servers"]


def test_seed_mode_migrates_then_seeds_without_servers(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    _forbid(monkeypatch, qa, "check_ports_free", "start_servers")
    monkeypatch.setattr(qa, "validate_config", lambda env: seen.append("validate"))
    monkeypatch.setattr(qa, "ensure_database", lambda env: seen.append("ensure_db"))
    monkeypatch.setattr(qa, "run_dev", lambda env, args: _record(seen, args, 0))
    monkeypatch.setattr(qa, "run_seed", lambda env: _record(seen, "seed", 0))
    assert qa.main(["--seed", "--base-dir", str(tmp_path / "qa")]) == 0
    assert seen == ["validate", "ensure_db", ["--ensure-db"], "seed"]


@pytest.mark.parametrize("value", ["2026-11-13 16:00", "2026-11-13T16:00:00", "soon", ""])
def test_clock_must_be_an_aware_instant(qa: ModuleType, tmp_path: Path, value: str) -> None:
    with pytest.raises(qa.QaError):
        qa.write_clock(tmp_path, value)
    assert not (tmp_path / qa.CLOCK_FILE).exists()


def test_clock_is_stored_as_utc(qa: ModuleType, tmp_path: Path) -> None:
    qa.write_clock(tmp_path, "2026-11-13T16:00:00+01:00")
    assert (tmp_path / qa.CLOCK_FILE).read_text(encoding="utf-8").strip() == (
        "2026-11-13T15:00:00Z"
    )


def test_api_child_pins_the_clock_and_binds_localhost(qa: ModuleType) -> None:
    code = qa.API_SCRIPT
    assert "dependency_overrides[utc_now]" in code
    assert "dependency_overrides[sync_status.utc_now]" in code
    assert '"127.0.0.1"' in code
    compile(code, "<api>", "exec")


def test_vite_ports_come_from_the_launcher_env() -> None:
    text = (REPO_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "process.env.TJ_WEB_PORT ?? 5173" in text
    assert "process.env.TJ_API_PORT ?? 8000" in text


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


def test_foreign_or_m5_config_is_never_deleted(qa: ModuleType, tmp_path: Path) -> None:
    target = tmp_path / "config"
    target.mkdir()
    existing = target / "rules.yaml"
    existing.write_bytes(b"private rules")
    with pytest.raises(qa.QaError):
        qa.prepare_config(REPO_ROOT / "config", target)
    (target / ".tj-qa-m5-copy").write_text("scripts/qa_live_check_m5.py\n", encoding="utf-8")
    with pytest.raises(qa.QaError):
        qa.prepare_config(REPO_ROOT / "config", target)
    assert existing.read_bytes() == b"private rules"


@pytest.mark.parametrize("base", [REPO_ROOT, REPO_ROOT / "config", REPO_ROOT.parent])
def test_repository_paths_refused_before_copy(
    qa: ModuleType, base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid(monkeypatch, qa, *SIDE_EFFECTS)
    assert qa.main(["--base-dir", str(base)]) == 1


def test_create_db_script_never_destroys(qa: ModuleType) -> None:
    code = qa.CREATE_DB_SCRIPT.upper()
    for word in ("DROP", "TRUNCATE", "DELETE", "ALTER", "TEMPLATE"):
        assert word not in code
    assert "CREATE DATABASE" in code
    assert QA_DB in qa.CREATE_DB_SCRIPT


def test_seed_module_refuses_other_databases() -> None:
    for url in (
        "postgresql+psycopg://u:p@127.0.0.1/trading_journal",
        "postgresql+psycopg://u:p@127.0.0.1/trading_journal_test",
        "postgresql+psycopg://u:p@remote.example/trading_journal_qa_m6",
        "postgresql+psycopg://u:p@127.0.0.1/trading_journal_qa_m6?host=x",
    ):
        with pytest.raises(digest_qa_seed.SeedError):
            digest_qa_seed.check_target(url)
    digest_qa_seed.check_target(f"postgresql+psycopg://u:p@127.0.0.1:5432/{QA_DB}")


def test_seed_module_never_destroys() -> None:
    code = Path(digest_qa_seed.__file__).read_text(encoding="utf-8").upper()
    for word in ("DROP ", "TRUNCATE", "DELETE(", ".DELETE", "ALTER "):
        assert word not in code


def test_seed_refuses_a_database_that_has_accounts() -> None:
    class _Session:
        def __enter__(self) -> _Session:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def scalar(self, query: object) -> int:
            return 1

        def add(self, row: object) -> None:
            raise AssertionError("must not write")

    with pytest.raises(digest_qa_seed.SeedError, match="already"):
        digest_qa_seed.seed(lambda: _Session(), digest_qa_seed.load_fixture())  # type: ignore[arg-type]


def test_fixture_is_synthetic_and_matches_its_generator(qa: ModuleType) -> None:
    path = REPO_ROOT / qa.FIXTURE_REL
    text = path.read_text(encoding="utf-8")
    assert text == render(build_digest_qa.digest_qa()), "run build_digest_qa"
    data = json.loads(text)
    assert "SYNTHETIC" in data["description"]
    sizes = {a["key"]: (a["size"], a["currency"], a["archive"]) for a in data["accounts"]}
    assert sizes == {
        "A": ("10000.00", "USD", False),
        "B": ("20000.00", "USD", False),
        "C": ("10000.00", "USD", True),
    }
    for account in data["accounts"]:
        assert "SYNTHETIC" in account["fixture"]["description"]


def test_fixture_server_times_follow_ny_close() -> None:
    """Summer (before Sun 2026-11-01) UTC+3, winter UTC+2; Brussels switched on 10-25."""
    assert build_digest_qa.server_wall("2026-09-28 09:00") == "2026-09-28 10:00:00"
    assert build_digest_qa.server_wall("2026-10-26 09:00") == "2026-10-26 11:00:00"
    assert build_digest_qa.server_wall("2026-11-09 09:00") == "2026-11-09 10:00:00"
    assert build_digest_qa.utc_iso("2026-11-15 23:30") == "2026-11-15T22:30:00Z"


class _FakeHttp:
    def __init__(self, notes: list[Any]) -> None:
        self.notes = notes
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        self.calls.append((method, path))
        if method == "GET" and path == "/api/bias/notes":
            return 200, {"items": self.notes}
        raise AssertionError(f"unexpected {method} {path}")


def test_api_seed_is_skipped_when_already_seeded(qa: ModuleType) -> None:
    http = _FakeHttp(notes=[{"id": 1}])
    assert qa.seed_api(http, qa.load_fixture()) is False
    assert http.calls == [("GET", "/api/bias/notes")]


def test_api_seed_only_talks_to_the_qa_api(qa: ModuleType) -> None:
    assert f"http://127.0.0.1:{qa.API_PORT}" == qa.API_BASE


def test_stop_kills_only_verified_qa_processes(
    qa: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    alive = SimpleNamespace(pid=11)
    fake_dev = SimpleNamespace(
        read_run_file=None,
        alive_records=lambda records: [(r, object()) for r in records if r.pid == 11],
        kill_process_tree=lambda pid: killed.append(pid),
        RUN_FILE=REPO_ROOT / "logs" / "dev-run.json",
    )
    monkeypatch.setattr(qa, "load_dev", lambda: fake_dev)
    seen_paths: list[Path] = []
    records = [alive, SimpleNamespace(pid=12)]
    fake_dev.read_run_file = lambda path: _record(seen_paths, path, records)
    assert qa.stop_recorded(tmp_path) == 0
    assert killed == [11]
    assert seen_paths == [tmp_path / qa.RUN_FILE]
    assert seen_paths[0] != fake_dev.RUN_FILE  # never the normal app's run file


def test_load_dev_really_loads_the_launcher(qa: ModuleType) -> None:
    dev = qa.load_dev()
    for name in ("port_in_use", "alive_records", "read_run_file", "kill_process_tree"):
        assert callable(getattr(dev, name))
