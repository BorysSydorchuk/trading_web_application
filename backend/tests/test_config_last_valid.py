"""Hardening (owner/PM 2026-11-27): a config file that fails validation never stops sync.

The last valid version stays in use, the file is listed as not applied (status bar warning
«Конфіг не застосовано: <file>, див. лог») and the details are logged once at ERROR.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT
from app.config_files import (
    config_not_applied,
    get_journal_fields,
    get_rules,
    get_violations,
    reload_config,
    stale_configs,
)
from app.config_files.loader import CONFIG_DIR_ENV, ConfigError, FileCache
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from app.db import make_session_factory
from app.models import SyncLog, Trade
from app.services import open_positions_snapshot as snapshot
from app.worker.ctrader_job import CtraderJobConfig, run_ctrader_balance_cycle
from tests.ctrader_fakes import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    REFRESH_TOKEN,
    FakeConnector,
    make_ctrader_account,
    no_sleep,
)
from tests.ctrader_history_fakes import HistoryServer, load
from tests.symbols_fixture import TEST_SYMBOLS

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
BROKEN = "rules:\n  max_risk_pct: { value: oops }\n"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    copy = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", copy)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(copy))
    reload_config()
    yield copy
    reload_config()


def _break(path: Path, body: str = BROKEN) -> None:
    before = path.stat().st_mtime_ns
    path.write_text(body, encoding="utf-8")
    # A changed stamp is what triggers the reload (mtime or size).
    os.utime(path, ns=(before + 10_000_000, before + 10_000_000))


# --- the cache -------------------------------------------------------------------------------


def test_a_broken_reload_keeps_the_last_valid_value_and_is_listed(
    config: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = get_rules()
    _break(config / "rules.yaml")

    with caplog.at_level(logging.ERROR):
        assert get_rules() is good
        assert get_rules() is good  # second call: no second log line
    assert [s.path.name for s in stale_configs()] == ["rules.yaml"]
    assert config_not_applied() == ["rules.yaml"]
    errors = [r for r in caplog.records if "CONFIG NOT APPLIED" in r.getMessage()]
    assert len(errors) == 1
    assert "max_risk_pct" in errors[0].getMessage()


def test_a_fixed_file_is_applied_again(config: Path) -> None:
    get_rules()
    original = (REPO_ROOT / "config" / "rules.yaml").read_text(encoding="utf-8")
    _break(config / "rules.yaml")
    get_rules()
    _break(config / "rules.yaml", original.replace("value: 1.1,", "value: 1.2,"))

    assert get_rules().rules.max_risk_pct.value == Decimal("1.2")
    assert stale_configs() == []
    assert config_not_applied() == []


@pytest.mark.parametrize("name", ["rules.yaml", "violations.yaml"])
def test_a_dependent_config_reloading_never_hides_the_warning(config: Path, name: str) -> None:
    """journal_fields reads rules.yaml and violations.yaml too and loads fine on their last
    valid values: the warning must stay while the file is broken (review 2026-11-27)."""
    get_rules()
    get_violations()
    get_journal_fields()
    _break(config / name, "not: [valid")

    get_journal_fields()
    assert config_not_applied() == [name]
    assert config_not_applied() == [name]  # a second poll too


def test_a_fixed_file_clears_the_warning_with_dependent_caches(config: Path) -> None:
    original = (config / "rules.yaml").read_text(encoding="utf-8")
    get_rules()
    get_journal_fields()
    _break(config / "rules.yaml")
    assert config_not_applied() == ["rules.yaml"]
    _break(config / "rules.yaml", original)
    get_journal_fields()
    assert config_not_applied() == []


def test_reload_config_forgets_the_warnings(config: Path) -> None:
    get_rules()
    _break(config / "rules.yaml")
    get_rules()
    reload_config()
    assert stale_configs() == []


def test_without_a_valid_version_the_error_is_raised(config: Path) -> None:
    _break(config / "rules.yaml")
    with pytest.raises(ConfigError):
        get_rules()
    assert config_not_applied() == ["rules.yaml"]


def test_file_cache_unit(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_text("1", encoding="utf-8")

    def parse() -> int:
        raw = path.read_text(encoding="utf-8")
        if not raw.isdigit():
            raise ConfigError(path, ["not a number"])
        return int(raw)

    cache = FileCache(lambda: [path], parse)
    assert cache.get() == 1
    _break(path, "x")
    assert cache.get() == 1
    cache.clear()  # an explicit reset forgets the last valid value too
    with pytest.raises(ConfigError):
        cache.get()


# --- sync keeps running ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


def test_invalid_rules_yaml_while_running_sync_continues_and_the_status_warns(
    config: Path, factory: sessionmaker[Session], tmp_path: Path, client: TestClient
) -> None:
    with factory() as session:
        account = make_ctrader_account(session, reference_balance=Decimal("1000.00"))
        account_id = account.id
    store = TokenStore(tokens_path(tmp_path))
    store.write(
        TokenPair(SecretStr(ACCESS_TOKEN), SecretStr(REFRESH_TOKEN), NOW + timedelta(days=30), NOW)
    )
    get_rules()  # the running worker loaded a valid rules.yaml
    _break(config / "rules.yaml")  # the owner saves a broken one

    server = HistoryServer(load("closed_simple.json")["deals"])
    job = CtraderJobConfig(
        client_id=CLIENT_ID,
        client_secret=SecretStr(CLIENT_SECRET),
        store=store,
        connector=FakeConnector(server.transport()),
        sleep=no_sleep,
        now=lambda: NOW,
        symbols_getter=lambda: TEST_SYMBOLS,
        snapshot_path=snapshot.snapshot_path(tmp_path),
    )
    assert run_ctrader_balance_cycle(factory, job) == [account_id]

    with factory() as session:
        row = session.scalars(select(SyncLog).where(SyncLog.account_id == account_id)).one()
        assert row.ok is True
        assert session.scalars(select(Trade.position_id)).all() == [5001]

    status = client.get("/api/sync/status")
    assert status.status_code == 200
    assert status.json()["config_not_applied"] == ["rules.yaml"]
