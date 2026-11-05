"""Unit tests for `scripts/qa_live_check.py` (config copy, env, QA-DB guard; nothing started)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.config import REPO_ROOT
from app.config_files import get_journal_fields, reload_config
from app.config_files.loader import CONFIG_DIR_ENV

SCRIPT = REPO_ROOT / "scripts" / "qa_live_check.py"
REAL_CONFIG = REPO_ROOT / "config"
IN_REPO = "лежить у репозиторії"  # noqa: RUF001 - Ukrainian message


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tj_qa_live_check", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qa = _load()


def _diff_lines(before: bytes, after: bytes) -> list[tuple[bytes, bytes]]:
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    assert len(old) == len(new)
    return [(a, b) for a, b in zip(old, new, strict=True) if a != b]


def test_prepare_config_makes_only_lesson_required(tmp_path: Path) -> None:
    dest = tmp_path / "config"

    changed = qa.prepare_config(REAL_CONFIG, dest)

    assert changed is True
    before = (REAL_CONFIG / "journal_fields.yaml").read_bytes()
    after = (dest / "journal_fields.yaml").read_bytes()
    assert not after.startswith(b"\xef\xbb\xbf")
    diff = _diff_lines(before, after)
    assert len(diff) == 1
    assert diff[0][0].replace(b"required: false", b"required: true") == diff[0][1]
    for src in REAL_CONFIG.iterdir():
        if src.name != "journal_fields.yaml":
            assert (dest / src.name).read_bytes() == src.read_bytes()


def test_prepared_config_loads_with_lesson_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "config"
    qa.prepare_config(REAL_CONFIG, dest)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(dest))
    reload_config()
    try:
        config = get_journal_fields()
    finally:
        monkeypatch.delenv(CONFIG_DIR_ENV)
        reload_config()
    lesson = next(f for f in config.fields if f.key == "lesson")
    assert lesson.required is True
    assert lesson.label == "Урок"
    real = get_journal_fields()
    assert [(f.key, f.label) for f in config.fields] == [(f.key, f.label) for f in real.fields]


def test_prepare_config_replaces_an_old_copy(tmp_path: Path) -> None:
    dest = tmp_path / "config"
    dest.mkdir()
    (dest / qa.COPY_MARKER).write_text("x\n", encoding="utf-8")
    (dest / "stale.yaml").write_text("x: 1\n", encoding="utf-8")
    (dest / "journal_fields.yaml").write_bytes(b"\xef\xbb\xbfgarbage")

    qa.prepare_config(REAL_CONFIG, dest)

    assert not (dest / "stale.yaml").exists()
    assert (dest / "journal_fields.yaml").read_bytes().startswith(b"# ")


def test_make_field_required_keeps_crlf_and_other_fields() -> None:
    text = (
        "fields:\r\n"
        "  - key: lesson_x\r\n"
        "    required: false\r\n"
        "  - key: lesson\r\n"
        '    label: "Урок"\r\n'
        "    required: false  # later\r\n"
        "  - key: after\r\n"
        "    required: false\r\n"
    )
    new, changed = qa.make_field_required(text)
    assert changed is True
    assert new == text.replace("required: false  # later", "required: true  # later")


def test_make_field_required_already_true_and_missing() -> None:
    text = "fields:\n  - key: lesson\n    required: true\n"
    assert qa.make_field_required(text) == (text, False)
    with pytest.raises(qa.QaError, match="key: lesson"):
        qa.make_field_required("fields:\n  - key: other\n    required: false\n")
    with pytest.raises(qa.QaError):
        qa.make_field_required("fields:\n  - key: lesson\n  - key: b\n    required: false\n")


def test_prepare_config_refuses_non_utf8(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "journal_fields.yaml").write_bytes("label: Урок".encode("cp1251"))
    with pytest.raises(qa.QaError, match="UTF-8"):
        qa.prepare_config(src, tmp_path / "dest")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal",
        "postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal_test",
        "postgresql+psycopg://journal:secret@127.0.0.1:5432/trading_journal_qa_m3x",
        "postgresql+psycopg://journal:journal@127.0.0.1:5432/",
        "sqlite:///trading_journal_qa_m3",
    ],
)
def test_refuses_non_qa_database(url: str, tmp_path: Path) -> None:
    with pytest.raises(qa.QaError) as info:
        qa.qa_env(tmp_path, tmp_path / "config", url, False, environ={})
    assert "secret" not in str(info.value)


def test_refuses_non_qa_database_before_touching_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(qa, "validate_config", _fail)
    monkeypatch.setattr(qa, "run_dev", _fail)
    url = "postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal"

    code = qa.main(["--database-url", url, "--base-dir", str(tmp_path / "qa")])

    assert code == 1
    assert not (tmp_path / "qa").exists()
    assert "Відмовляюся запускати" in capsys.readouterr().out


def _fail(*_args: object) -> int:
    raise AssertionError("must not be called")


def test_qa_env_sets_qa_variables(tmp_path: Path) -> None:
    env = qa.qa_env(tmp_path, tmp_path / "config", qa.QA_DATABASE_URL, True, environ={"KEEP": "1"})
    assert env["DATABASE_URL"].endswith("/trading_journal_qa_m3")
    assert env["MT5_SOURCE"] == "fixture:backend/tests/fixtures/mt5/basic_week.json"
    assert env["MT5_PASSWORD_51234567"] == "qa"  # noqa: S105 - the fixture account
    assert env["DATA_DIR"] == str(tmp_path / "data")
    assert env["CONFIG_DIR"] == str(tmp_path / "config")
    assert env["WHISPER_BEAM_SIZE"] == "1"
    assert env["WHISPER_CPU_THREADS"] == "auto"
    assert env["WHISPER_CONDITION_ON_PREVIOUS_TEXT"] == "true"
    assert env["KEEP"] == "1"
    assert "journal:journal" not in qa.shown_env(env)
    plain = qa.qa_env(tmp_path, tmp_path / "c", qa.QA_DATABASE_URL, False, environ={})
    assert "WHISPER_CONDITION_ON_PREVIOUS_TEXT" not in plain


def test_main_runs_dev_with_qa_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(qa, "validate_config", lambda env: seen.update(checked=env["CONFIG_DIR"]))

    def fake_run_dev(env: dict[str, str], args: list[str]) -> int:
        seen.update(env=env, args=args)
        return 0

    monkeypatch.setattr(qa, "run_dev", fake_run_dev)
    base = tmp_path / "qa"

    assert qa.main(["--no-browser", "--base-dir", str(base)]) == 0

    assert seen["checked"] == str(base.resolve() / "config")
    assert seen["args"] == ["--no-browser"]
    assert (base / "config" / "journal_fields.yaml").exists()
    out = capsys.readouterr().out
    assert "QA-база trading_journal_qa_m3" in out
    assert "поле «lesson» тепер обовʼязкове" in out


def test_prepare_config_replaces_a_copy_from_before_the_marker(tmp_path: Path) -> None:
    dest = tmp_path / "config"
    dest.mkdir()
    (dest / "journal_fields.yaml").write_bytes(b"\xef\xbb\xbfgarbage")
    (dest / "rules.yaml").write_text("x: 1\n", encoding="utf-8")

    qa.prepare_config(REAL_CONFIG, dest)

    assert (dest / qa.COPY_MARKER).is_file()
    assert (dest / "rules.yaml").read_bytes() == (REAL_CONFIG / "rules.yaml").read_bytes()


@pytest.mark.parametrize("extra", ["notes.txt", "sub"])
def test_prepare_config_never_deletes_a_foreign_folder(tmp_path: Path, extra: str) -> None:
    dest = tmp_path / "config"
    dest.mkdir()
    (dest / "journal_fields.yaml").write_text("mine\n", encoding="utf-8")
    if extra == "sub":
        (dest / extra).mkdir()
    else:
        (dest / extra).write_text("keep\n", encoding="utf-8")

    with pytest.raises(qa.QaError, match="Відмовляюся видаляти"):
        qa.prepare_config(REAL_CONFIG, dest)

    assert (dest / "journal_fields.yaml").read_text(encoding="utf-8") == "mine\n"
    assert (dest / extra).exists()


@pytest.mark.parametrize(
    "base",
    [
        REPO_ROOT,
        REPO_ROOT / "config",
        REPO_ROOT / "data",
        REPO_ROOT / "backend" / "tmp",
        REPO_ROOT.parent,
        Path(REPO_ROOT.anchor),
    ],
)
def test_check_base_dir_refuses_repo_and_its_parents(base: Path) -> None:
    with pytest.raises(qa.QaError, match=IN_REPO):
        qa.check_base_dir(base)


def test_check_base_dir_accepts_a_temp_dir(tmp_path: Path) -> None:
    qa.check_base_dir(tmp_path / "tj-qa")


@pytest.mark.parametrize("base", [".", "config", "backend"])
def test_main_refuses_base_dir_in_repo_before_touching_files(
    base: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(qa, "prepare_config", _fail)
    monkeypatch.setattr(qa, "validate_config", _fail)
    monkeypatch.setattr(qa, "run_dev", _fail)

    assert qa.main(["--base-dir", base]) == 1

    assert IN_REPO in capsys.readouterr().out
