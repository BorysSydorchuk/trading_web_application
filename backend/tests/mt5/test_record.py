"""The fixture recorder round-trips: record from a source -> FixtureMt5Source sees the same data."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.mt5 import record
from app.mt5.fixture import FixtureMt5Source
from tests.fixtures.mt5 import build_fixtures

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mt5"
PASSWORD = "do-not-store-me"  # noqa: S105 - fake test password


@pytest.fixture
def env_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MT5_PASSWORD_51234567", PASSWORD)


@pytest.mark.usefixtures("env_password")
def test_record_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: build_fixtures.sv("2026-10-23 10:00:00"))
    src = FixtureMt5Source.from_file(FIXTURES / "basic_week.json")
    out = tmp_path / "rec.json"
    argv = ["--terminal", "x", "--login", "51234567", "--server", "FundedNext-Server"]
    code = record.main([*argv, "--days", "10", "--out", str(out)], source=src)
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert PASSWORD not in text
    assert "shutdown" in src.calls

    original = FixtureMt5Source.from_file(FIXTURES / "basic_week.json")
    copy = FixtureMt5Source.from_file(out)
    for s in (original, copy):
        s.connect("x", 51234567, _pw(), "FundedNext-Server")
    assert copy.deals(0, 2**31) == original.deals(0, 2**31)
    assert copy.open_positions() == original.open_positions()
    assert copy.account_info() == original.account_info()
    assert copy.symbols_matching(["EUR", "GBP", "XAU", "GER"]) == original.symbols_matching(
        ["EUR", "GBP", "XAU", "GER"]
    )
    assert copy.opening_order(2000201) == original.opening_order(2000201)


@pytest.mark.usefixtures("env_password")
def test_record_anonymize(tmp_path: Path) -> None:
    src = FixtureMt5Source.from_file(FIXTURES / "basic_week.json")
    out = tmp_path / "anon.json"
    argv = ["--terminal", "x", "--login", "51234567", "--server", "FundedNext-Server"]
    assert record.main([*argv, "--anonymize", "--out", str(out)], source=src) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["account"]["login"] == record.ANON_LOGIN
    assert data["account"]["server"] == record.ANON_SERVER
    assert "51234567" not in json.dumps(data["account"])


def test_record_reports_mt5_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MT5_PASSWORD_51234569", raising=False)
    monkeypatch.setattr(record, "mt5_password_for", lambda login: _pw())
    src = FixtureMt5Source.from_file(FIXTURES / "fail_login.json")
    argv = ["--terminal", "x", "--login", "51234569", "--server", "FundedNext-Server"]
    assert record.main([*argv, "--out", str(tmp_path / "x.json")], source=src) == 1
    assert "login_failed" in capsys.readouterr().err
    assert not (tmp_path / "x.json").exists()


def _pw() -> SecretStr:
    return SecretStr(PASSWORD)
