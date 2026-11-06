"""M4 launcher safety checks; subprocesses are stubbed and no DB is contacted."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.config import REPO_ROOT


@pytest.fixture
def qa(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "tj_qa_m4", REPO_ROOT / "scripts" / "qa_live_check_m4.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:sensitive@remote.example/trading_journal_qa_m4",
        "postgresql+psycopg://u:sensitive@127.0.0.1/trading_journal",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m3",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m4x",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m4?host=remote",
        "postgresql+psycopg://u:sensitive@localhost/trading_journal_qa_m4#extra",
        "sqlite:///trading_journal_qa_m4",
        "postgresql+psycopg://[broken",
        "postgresql+psycopg://u:sensitive@localhost:bad/trading_journal_qa_m4",
        "postgresql://u:sensitive@localhost/trading_journal_qa_m4",
    ],
)
def test_bad_database_refused_before_files_or_processes(
    qa: ModuleType,
    url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("must refuse before side effects")

    monkeypatch.setattr(qa, "prepare_config", forbidden)
    monkeypatch.setattr(qa, "validate_config", forbidden)
    monkeypatch.setattr(qa, "run_dev", forbidden)
    base = tmp_path / "qa"
    assert qa.main(["--database-url", url, "--base-dir", str(base)]) == 1
    assert not base.exists()
    assert "sensitive" not in capsys.readouterr().out


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_exact_local_database_accepted(qa: ModuleType, host: str) -> None:
    qa.check_qa_database(f"postgresql+psycopg://u:p@{host}:5432/trading_journal_qa_m4")


def test_environment_is_offline_and_isolated(qa: ModuleType, tmp_path: Path) -> None:
    original = {
        "ANTHROPIC_API_KEY": "sentinel",
        "anthropic_api_key": "lowercase",
        "MT5_SOURCE": "real",
        "KEEP": "yes",
    }
    env = qa.qa_env(tmp_path, tmp_path / "config", qa.QA_DATABASE_URL, environ=original)
    assert original["ANTHROPIC_API_KEY"] == "sentinel"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert "anthropic_api_key" not in env
    assert env["MT5_SOURCE"] == "fixture:backend/tests/fixtures/mt5/basic_week.json"
    assert env["DATABASE_URL"].endswith("/trading_journal_qa_m4")
    assert env["DATA_DIR"] == str(tmp_path / "data")
    assert env["LOG_DIR"] == str(tmp_path / "logs")
    assert env["CONFIG_DIR"] == str(tmp_path / "config")
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["KEEP"] == "yes"
    assert "sentinel" not in qa.shown_env(env)
    assert "u:p" not in qa.shown_env(env)


def test_config_copy_is_byte_identical_and_keeps_audio(qa: ModuleType, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    audio = data / "kept.ogg"
    audio.write_bytes(b"audio")
    target = tmp_path / "config"
    qa.prepare_config(REPO_ROOT / "config", target)
    qa.prepare_config(REPO_ROOT / "config", target)
    for source in (REPO_ROOT / "config").iterdir():
        if source.is_file():
            assert (target / source.name).read_bytes() == source.read_bytes()
    assert audio.read_bytes() == b"audio"


def test_foreign_config_is_never_deleted(qa: ModuleType, tmp_path: Path) -> None:
    target = tmp_path / "config"
    target.mkdir()
    existing = target / "rules.yaml"
    existing.write_bytes(b"private rules")
    with pytest.raises(qa.QaError):
        qa.prepare_config(REPO_ROOT / "config", target)
    assert existing.read_bytes() == b"private rules"


@pytest.mark.parametrize("base", [REPO_ROOT, REPO_ROOT / "config", REPO_ROOT.parent])
def test_repository_paths_refused_before_copy(
    qa: ModuleType,
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("must refuse before side effects")

    monkeypatch.setattr(qa, "prepare_config", forbidden)
    assert qa.main(["--base-dir", str(base)]) == 1


def test_main_validates_then_launches_offline(
    qa: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[str] = []

    def validate(env: dict[str, str]) -> None:
        assert env["ANTHROPIC_API_KEY"] == ""
        assert Path(env["CONFIG_DIR"]).is_dir()
        seen.append("validate")

    def launch(env: dict[str, str], args: list[str]) -> int:
        assert args == ["--no-browser"]
        assert env["ANTHROPIC_API_KEY"] == ""
        seen.append("launch")
        return 7

    monkeypatch.setattr(qa, "validate_config", validate)
    monkeypatch.setattr(qa, "run_dev", launch)
    assert qa.main(["--no-browser", "--base-dir", str(tmp_path / "qa")]) == 7
    assert seen == ["validate", "launch"]
    assert "trading_journal_qa_m4" in capsys.readouterr().out
