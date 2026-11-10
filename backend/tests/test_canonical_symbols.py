"""Canonical symbols end to end against the test DB (docs/api.md "M5-08 Canonical symbols").

The real FundedNext case: the broker names the DAX GER30, the app shows and aggregates it as
GER40 everywhere except MT5 calls. Fixture `funded_next_ger30.json` (SYNTHETIC values, see
tests/fixtures/mt5/README.md); `config/symbols.yaml` is the real file unless stated.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT
from app.config_files import ConfigError, get_rules, reload_config
from app.config_files.rules import RulesConfig
from app.config_files.symbols import SymbolsConfig
from app.db import make_session_factory
from app.models import Account, BiasEntry, BiasNote, RuleViolation, SymbolSpec, SyncLog, Trade
from app.models.calculator import CalculatorMarginRequest
from app.models.enums import AccountStatus, BiasKind
from app.mt5.fixture import FixtureMt5Source
from app.services.symbol_map import apply_symbol_map
from app.services.sync import sync_account
from app.services.trade_rules import recompute_rules
from app.worker import sync_job
from app.worker.margin_job import run_margin_cycle
from app.worker.sync_job import reapply_symbol_map, run_sync_cycle
from tests.services.test_bias_alignment_service import truncate_all
from tests.symbols_fixture import TEST_SYMBOLS, use_test_config
from tests.test_calculator_api import make_margin_request
from tests.test_sync import (
    DST_LOGIN,
    DST_NOW,
    FIXTURES,
    add_account,
    password,
    source,
    trades_by_pid,
)
from tests.test_trades_api import T0, add_trade

D = Decimal
# Fixed copy of the contract's symbols.yaml (tests/symbols_fixture.py), also active via
# CONFIG_DIR for code that reads get_symbols_config() itself.
REAL_SYMBOLS = TEST_SYMBOLS
# Same names, no firm override.
GENERIC_SYMBOLS = SymbolsConfig.model_validate(
    {
        "symbols": [
            {"name": "EURUSD"},
            {"name": "GBPUSD"},
            {"name": "XAUUSD"},
            {"name": "GER40", "broker_names": ["GER30", "GER40.cash", "DE40"]},
        ]
    }
)
GER30_FIXTURE = "funded_next_ger30.json"
GER30_LOGIN = 51234571
GER30_NOW = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)  # 15:00 Brussels, trading hours
CLOSED_PID = 8000101  # GER30 buy, Tue 09:30 Brussels (london)
OPEN_PID = 8000201  # GER30 sell, open, SL only on the position
TUESDAY = date(2026, 11, 3)


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    truncate_all(db_engine)
    yield
    truncate_all(db_engine)


@pytest.fixture(autouse=True)
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    yield use_test_config(tmp_path, monkeypatch)
    reload_config()


def _break(path: Path) -> None:
    path.write_text("symbols: [\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))


def _restore(cfg_dir: Path, name: str) -> None:
    shutil.copy(REPO_ROOT / "config" / name, cfg_dir / name)
    later = time.time() + 10
    os.utime(cfg_dir / name, (later, later))


@pytest.fixture
def factory(db_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(db_engine)


@pytest.fixture
def session(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def rules() -> RulesConfig:
    return get_rules()


def sync(
    session: Session,
    account: Account,
    src: FixtureMt5Source,
    rules: RulesConfig,
    now: datetime = GER30_NOW,
    symbols: SymbolsConfig = REAL_SYMBOLS,
) -> SyncLog:
    return sync_account(session, account, src, rules, now, password_for=password, symbols=symbols)


def specs_of(session: Session, account: Account) -> dict[str, SymbolSpec]:
    session.expire_all()
    rows = session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account.id))
    return {row.symbol: row for row in rows}


def ger30_account(session: Session, **kw: Any) -> Account:
    return add_account(session, GER30_LOGIN, **kw)


def ger30_trade(session: Session, account: Account, **kw: Any) -> Trade:
    """A trade as the migration leaves it: symbol = broker_symbol = GER30."""
    return add_trade(session, account, symbol="GER30", broker_symbol="GER30", **kw)


# --- ORM defaults: a row without the new column copies `symbol` --------------------------------


def test_new_columns_default_to_the_symbol(session: Session) -> None:
    account = ger30_account(session)
    trade = add_trade(session, account, symbol="EURUSD")
    spec = SymbolSpec(
        account_id=account.id,
        symbol="EURUSD",
        contract_size=D(100000),
        tick_size=D("0.00001"),
        tick_value=D(1),
        volume_min=D("0.01"),
        volume_step=D("0.01"),
        volume_max=D(50),
        digits=5,
        currency_profit="USD",
        currency_margin="EUR",
        synced_at=GER30_NOW,
    )
    session.add(spec)
    session.commit()
    request = make_margin_request(session, account, symbol="EURUSD")
    session.expire_all()
    assert trade.broker_symbol == "EURUSD"
    assert spec.canonical_symbol == "EURUSD"
    assert request.broker_symbol == "EURUSD"


# --- sync with the real FundedNext case --------------------------------------------------------


def test_ger30_sync_stores_canonical_trades_and_broker_spec(
    session: Session, rules: RulesConfig
) -> None:
    account = ger30_account(session)
    log = sync(session, account, source(GER30_FIXTURE), rules)

    assert log.ok is True, log.error_message
    assert log.trades_created == 2
    assert log.symbols_synced == 4
    specs = specs_of(session, account)
    assert {s: row.canonical_symbol for s, row in specs.items()} == {
        "EURUSD": "EURUSD",
        "GBPUSD": "GBPUSD",
        "XAUUSD": "XAUUSD",
        "GER30": "GER40",
    }
    assert (specs["GER30"].point, specs["GER30"].tick_value_loss) == (D("0.01"), D("0.01161"))

    trades = trades_by_pid(session, account.id)
    assert {pid: (t.symbol, t.broker_symbol) for pid, t in trades.items()} == {
        CLOSED_PID: ("GER40", "GER30"),
        OPEN_PID: ("GER40", "GER30"),
    }
    closed, still_open = trades[CLOSED_PID], trades[OPEN_PID]
    assert (closed.risk_amount, closed.r_multiple, closed.planned_rr) == (
        D("34.80"),
        D("1.0000"),
        D("2.0000"),
    )
    # Open position: risk from the GER30 spec, found by the broker name.
    assert (still_open.initial_sl, still_open.initial_sl_source) == (D("24130"), "position")
    assert still_open.risk_amount == D("69.60")  # 30 / 0.01 * 0.0116 * 2
    assert still_open.status == "open"


def test_second_ger30_sync_changes_nothing(session: Session, rules: RulesConfig) -> None:
    account = ger30_account(session)
    src = source(GER30_FIXTURE)
    assert sync(session, account, src, rules).ok is True
    log = sync(session, account, src, rules, GER30_NOW + timedelta(minutes=1))
    assert log.ok is True, log.error_message
    assert (log.trades_created, log.trades_updated) == (0, 0)
    assert len(specs_of(session, account)) == 4


def test_stale_ger30_spec_is_refreshed_and_renamed(session: Session, rules: RulesConfig) -> None:
    """Dev DB 2026-11-10: a GER30 spec synced before point was captured, never refreshed."""
    account = ger30_account(session)
    session.add(
        SymbolSpec(
            account_id=account.id,
            symbol="GER30",
            contract_size=D(1),
            tick_size=D("0.01"),
            tick_value=D("0.0116"),
            point=None,
            tick_value_loss=None,
            volume_min=D("0.1"),
            volume_step=D("0.1"),
            volume_max=D(100),
            digits=2,
            currency_profit="EUR",
            currency_margin="EUR",
            synced_at=datetime(2026, 10, 30, 8, 0, tzinfo=UTC),
        )
    )
    session.commit()

    assert sync(session, account, source(GER30_FIXTURE), rules).ok is True

    ger30 = specs_of(session, account)["GER30"]
    assert ger30.canonical_symbol == "GER40"
    assert (ger30.point, ger30.tick_value_loss) == (D("0.01"), D("0.01161"))
    assert ger30.synced_at == GER30_NOW


def test_ger40_spec_resolved_without_any_ger30_trade(session: Session, rules: RulesConfig) -> None:
    """The watch list (symbols.yaml) finds GER30 for GER40 on its own, not via traded deals."""
    data = json.loads((FIXTURES / GER30_FIXTURE).read_text(encoding="utf-8"))
    quiet = FixtureMt5Source(data | {"deals": data["deals"][:1], "orders": [], "positions": []})
    account = ger30_account(session)
    log = sync(session, account, quiet, rules)
    assert log.ok is True, log.error_message
    assert log.trades_created == 0
    assert specs_of(session, account)["GER30"].canonical_symbol == "GER40"


def test_without_firm_override_ger30_is_still_found(session: Session, rules: RulesConfig) -> None:
    account = ger30_account(session, firm="Other firm")
    log = sync(session, account, source(GER30_FIXTURE), rules, symbols=GENERIC_SYMBOLS)
    assert log.ok is True, log.error_message
    assert specs_of(session, account)["GER30"].canonical_symbol == "GER40"


def test_configured_symbol_missing_at_the_broker_is_a_warning(
    session: Session, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    """dst_switch has only EURUSD: GER40 (and GBPUSD, XAUUSD) are not found, sync still OK."""
    account = add_account(session, DST_LOGIN)
    with caplog.at_level(logging.WARNING, logger="app.services.sync"):
        log = sync(session, account, source("dst_switch.json"), rules, DST_NOW)
    assert log.ok is True, log.error_message
    assert set(specs_of(session, account)) == {"EURUSD"}
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("GER40" in m and "not found" in m for m in warnings), warnings


def test_ger40_bias_aligns_with_the_ger30_trade(session: Session, rules: RulesConfig) -> None:
    note = BiasNote(kind=BiasKind.PRE_LONDON.value, period_date=TUESDAY)
    note.entries = [BiasEntry(symbol="GER40", direction="bullish")]
    session.add(note)
    session.commit()
    account = ger30_account(session)

    assert sync(session, account, source(GER30_FIXTURE), rules).ok is True

    closed = trades_by_pid(session, account.id)[CLOSED_PID]  # buy, Tue 09:30 Brussels
    assert closed.bias_alignment == "aligned"


def test_sync_resolves_specs_from_the_current_symbols_config(
    session: Session, rules: RulesConfig
) -> None:
    """Without the `symbols` argument the sync reads config/symbols.yaml itself."""
    account = ger30_account(session)
    log = sync_account(
        session, account, source(GER30_FIXTURE), rules, GER30_NOW, password_for=password
    )
    assert log.ok is True, log.error_message
    assert trades_by_pid(session, account.id)[CLOSED_PID].symbol == "GER40"


# --- re-apply step (worker start + every sync cycle) ------------------------------------------


def _seed_pre_mapping_rows(session: Session) -> tuple[Account, Trade, Trade, Trade]:
    account = ger30_account(session)
    first = ger30_trade(session, account)
    second = ger30_trade(
        session, account, open_time=T0 + timedelta(hours=1), close_time=T0 + timedelta(hours=2)
    )
    eurusd = add_trade(session, account, symbol="EURUSD")
    session.add(
        SymbolSpec(
            account_id=account.id,
            symbol="GER30",
            contract_size=D(1),
            tick_size=D("0.01"),
            tick_value=D("0.0116"),
            volume_min=D("0.1"),
            volume_step=D("0.1"),
            volume_max=D(100),
            digits=2,
            currency_profit="EUR",
            currency_margin="EUR",
            synced_at=GER30_NOW,
        )
    )
    session.commit()
    make_margin_request(session, account, symbol="GER30", broker_symbol="GER30")
    return account, first, second, eurusd


def test_apply_renames_stored_rows_and_is_idempotent(session: Session) -> None:
    account, first, second, eurusd = _seed_pre_mapping_rows(session)

    changed = apply_symbol_map(session, REAL_SYMBOLS)
    session.commit()

    assert changed == 4  # two trades, one spec, one margin request
    session.expire_all()
    assert [(t.symbol, t.broker_symbol) for t in (first, second)] == [("GER40", "GER30")] * 2
    assert (eurusd.symbol, eurusd.broker_symbol) == ("EURUSD", "EURUSD")
    spec = specs_of(session, account)["GER30"]
    assert spec.canonical_symbol == "GER40"
    request = session.scalars(select(CalculatorMarginRequest)).one()
    assert (request.symbol, request.broker_symbol) == ("GER40", "GER30")

    assert apply_symbol_map(session, REAL_SYMBOLS) == 0
    session.commit()
    session.expire_all()
    assert first.symbol == "GER40"


def test_later_map_edits_apply_to_history(session: Session) -> None:
    _, first, _, _ = _seed_pre_mapping_rows(session)
    apply_symbol_map(session, REAL_SYMBOLS)
    session.commit()

    without_alias = SymbolsConfig.model_validate(
        {"symbols": [{"name": "EURUSD"}, {"name": "GER40"}]}
    )
    assert apply_symbol_map(session, without_alias) == 4
    session.commit()
    session.expire_all()
    assert (first.symbol, first.broker_symbol) == ("GER30", "GER30")  # unconfigured: own name


def test_apply_realigns_renamed_trades_with_the_bias(session: Session) -> None:
    note = BiasNote(kind=BiasKind.PRE_LONDON.value, period_date=T0.date())
    note.entries = [BiasEntry(symbol="GER40", direction="bullish")]
    session.add(note)
    session.commit()
    account = ger30_account(session)
    trade = ger30_trade(session, account)  # buy, Wed 09:00 Brussels

    apply_symbol_map(session, REAL_SYMBOLS)
    session.commit()
    session.refresh(trade)
    assert trade.bias_alignment == "aligned"


def test_apply_recomputes_reentry_by_canonical_symbol(session: Session) -> None:
    """A GER30 loss then a GER40 entry of the same idea: a re-entry once both are GER40."""
    account = ger30_account(session)
    loss = ger30_trade(
        session,
        account,
        close_time=T0 + timedelta(minutes=20),
        net_pnl=D("-50.00"),
        gross_pnl=D("-50.00"),
    )
    later = add_trade(
        session,
        account,
        symbol="GER40",
        open_time=T0 + timedelta(minutes=40),
        close_time=T0 + timedelta(minutes=70),
    )
    for trade in (loss, later):  # add_trade's first parameter is called `session`
        trade.direction, trade.session = "buy", "london"
    session.commit()
    recompute_rules(session, account.id, T0, get_rules())
    session.commit()
    session.refresh(later)
    assert later.is_reentry is False  # GER30 vs GER40: different ideas before the mapping

    apply_symbol_map(session, REAL_SYMBOLS)
    session.commit()
    session.refresh(later)
    assert later.is_reentry is True


def test_reapply_symbol_map_commits_and_returns_the_count(
    factory: sessionmaker[Session], session: Session
) -> None:
    _, first, _, _ = _seed_pre_mapping_rows(session)
    assert reapply_symbol_map(factory, symbols_getter=lambda: REAL_SYMBOLS) == 4
    session.expire_all()
    assert first.symbol == "GER40"


def test_reapply_symbol_map_never_raises(
    factory: sessionmaker[Session], session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    _, first, _, _ = _seed_pre_mapping_rows(session)

    def broken() -> SymbolsConfig:
        raise ConfigError(Path("symbols.yaml"), ["symbols: missing"])

    with caplog.at_level(logging.ERROR):
        # None = not applied (review M5-08: distinguishable from 0 = nothing to change).
        assert reapply_symbol_map(factory, symbols_getter=broken) is None
    assert "symbols.yaml" in caplog.text
    session.expire_all()
    assert first.symbol == "GER30"


def test_reapply_symbol_map_returns_none_on_an_unexpected_error(
    factory: sessionmaker[Session],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed_pre_mapping_rows(session)

    def exploding(*_args: Any) -> int:
        raise RuntimeError("database went away")

    monkeypatch.setattr(sync_job, "apply_symbol_map", exploding)
    with caplog.at_level(logging.ERROR):
        assert reapply_symbol_map(factory, symbols_getter=lambda: REAL_SYMBOLS) is None
    assert "RuntimeError: database went away" in caplog.text


@pytest.mark.parametrize("name", ["bias.yaml", "rules.yaml"])
def test_broken_bias_or_rules_renames_nothing_until_fixed(
    session: Session, cfg_dir: Path, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    """Rename and recompute are one step: never a renamed trade with a stale alignment."""
    note = BiasNote(kind=BiasKind.PRE_LONDON.value, period_date=T0.date())
    note.entries = [BiasEntry(symbol="GER40", direction="bullish")]
    session.add(note)
    session.commit()
    account, first, _, _ = _seed_pre_mapping_rows(session)
    _break(cfg_dir / name)

    with caplog.at_level(logging.ERROR):
        assert apply_symbol_map(session, REAL_SYMBOLS) is None
    session.commit()
    session.expire_all()
    assert name in caplog.text
    assert first.symbol == "GER30"
    assert specs_of(session, account)["GER30"].canonical_symbol == "GER30"
    request = session.scalars(select(CalculatorMarginRequest)).one()
    assert request.symbol == "GER30"

    _restore(cfg_dir, name)
    assert apply_symbol_map(session, REAL_SYMBOLS) == 4
    session.commit()
    session.expire_all()
    assert (first.symbol, first.bias_alignment) == ("GER40", "aligned")


def test_broken_bias_yaml_does_not_block_when_nothing_to_rename(
    session: Session, cfg_dir: Path
) -> None:
    account = ger30_account(session)
    add_trade(session, account, symbol="EURUSD")
    _break(cfg_dir / "bias.yaml")
    assert apply_symbol_map(session, REAL_SYMBOLS) == 0


def test_sync_cycle_skipped_when_the_symbol_map_fails(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    cfg_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed re-apply is as visible as a broken rules.yaml: the cycle is skipped."""
    account = ger30_account(session)
    ger30_trade(session, account)  # a rename is pending
    _break(cfg_dir / "bias.yaml")

    with caplog.at_level(logging.ERROR):
        synced = run_sync_cycle(
            factory,
            source(GER30_FIXTURE),
            now=lambda: GER30_NOW,
            rules_getter=lambda: rules,
            symbols_getter=lambda: REAL_SYMBOLS,
        )

    assert synced == []
    assert "MT5 sync skipped" in caplog.text
    assert session.scalars(select(SyncLog)).all() == []


def test_every_sync_cycle_reapplies_the_map_first(
    factory: sessionmaker[Session], session: Session, rules: RulesConfig
) -> None:
    archived = ger30_account(session, status=AccountStatus.ARCHIVED.value)
    trade = ger30_trade(session, archived)

    synced = run_sync_cycle(
        factory,
        source(GER30_FIXTURE),
        now=lambda: GER30_NOW,
        rules_getter=lambda: rules,
        symbols_getter=lambda: REAL_SYMBOLS,
    )

    assert synced == []  # no active account; the map is applied anyway
    session.refresh(trade)
    assert (trade.symbol, trade.broker_symbol) == ("GER40", "GER30")


def test_sync_cycle_skipped_when_symbols_config_broken(
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ger30_account(session)

    def broken() -> SymbolsConfig:
        raise ConfigError(Path("symbols.yaml"), ["symbols: missing"])

    synced = run_sync_cycle(
        factory,
        source(GER30_FIXTURE),
        now=lambda: GER30_NOW,
        rules_getter=lambda: rules,
        symbols_getter=broken,
    )
    assert synced == []
    assert "MT5 sync skipped" in caplog.text
    assert session.scalars(select(SyncLog)).all() == []


# --- rules: tick size by the broker symbol ---------------------------------------------------


def test_breakeven_rule_uses_the_broker_symbol_tick_size(session: Session) -> None:
    account = ger30_account(session)
    session.add(
        SymbolSpec(
            account_id=account.id,
            symbol="GER30",
            canonical_symbol="GER40",
            contract_size=D(1),
            tick_size=D(1),
            tick_value=D("1.16"),
            volume_min=D("0.1"),
            volume_step=D("0.1"),
            volume_max=D(100),
            digits=0,
            currency_profit="EUR",
            currency_margin="EUR",
            synced_at=GER30_NOW,
        )
    )
    # SL moved to 24000.5: within one 1.0 tick of the entry = breakeven (exact compare without).
    trade = add_trade(
        session,
        account,
        symbol="GER40",
        broker_symbol="GER30",
        entry_price=D("24000"),
        exit_price=D("24010"),
        initial_sl=D("23900"),
        initial_sl_source="deal",
        last_sl=D("24000.5"),
        tp=None,
    )

    recompute_rules(session, account.id, T0, get_rules())
    session.commit()

    keys = session.scalars(select(RuleViolation.rule_key).where(RuleViolation.trade_id == trade.id))
    assert "no_breakeven" in set(keys)


# --- journal: canonical filter and list, spec by broker symbol --------------------------------


def test_journal_lists_and_filters_by_canonical_symbol(
    client: TestClient, session: Session
) -> None:
    account = ger30_account(session)
    dax = add_trade(session, account, symbol="GER40", broker_symbol="GER30")
    add_trade(session, account, symbol="EURUSD")

    assert client.get("/api/trades/symbols").json() == {"items": ["EURUSD", "GER40"]}
    items = client.get("/api/trades", params={"symbol": "GER40"}).json()["items"]
    assert [i["id"] for i in items] == [dax.id]
    assert items[0]["symbol"] == "GER40"
    assert client.get("/api/trades", params={"symbol": "GER30"}).json()["items"] == []


def test_patch_initial_sl_finds_the_spec_by_broker_symbol(
    client: TestClient, session: Session
) -> None:
    account = ger30_account(session)
    session.add(
        SymbolSpec(
            account_id=account.id,
            symbol="GER30",
            canonical_symbol="GER40",
            contract_size=D(1),
            tick_size=D("0.01"),
            tick_value=D("0.0116"),
            volume_min=D("0.1"),
            volume_step=D("0.1"),
            volume_max=D(100),
            digits=2,
            currency_profit="EUR",
            currency_margin="EUR",
            synced_at=GER30_NOW,
        )
    )
    session.commit()
    # Breakeven exit: nothing realised, so the risk needs the spec.
    trade = add_trade(
        session,
        account,
        symbol="GER40",
        broker_symbol="GER30",
        status="needs_sl",
        entry_price=D("24000"),
        exit_price=D("24000"),
        volume=D("1"),
        gross_pnl=D("0.00"),
        net_pnl=D("0.00"),
        tp=None,
    )

    data = client.patch(f"/api/trades/{trade.id}", json={"initial_sl": "23970"}).json()
    assert data["risk_amount"] == "34.80"  # 30 / 0.01 * 0.0116 * 1


# --- acceptance: sync -> calculate GER40 -> margin via MT5 with GER30 ---------------------------


def test_acceptance_calculate_ger40_and_margin_with_ger30(
    client: TestClient,
    factory: sessionmaker[Session],
    session: Session,
    rules: RulesConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = ger30_account(session)
    src = source(GER30_FIXTURE)
    assert sync(session, account, src, rules).ok is True

    listed = client.get(f"/api/accounts/{account.id}/symbol-specs").json()
    by_symbol = {item["symbol"]: item for item in listed["items"]}
    assert by_symbol["GER40"]["broker_symbol"] == "GER30"
    assert listed["missing"] == []

    body = {
        "account_id": account.id,
        "symbol": "GER40",
        "direction": "buy",
        "entry": "24000",
        "sl_price": "23970",
    }
    calculated = client.post("/api/calculator/calculate", json=body)
    assert calculated.status_code == 200, calculated.text
    assert calculated.json()["symbol"] == "GER40"

    queued = client.post("/api/calculator/margin-requests", json=body)
    assert queued.status_code == 202, queued.text
    request_id = queued.json()["id"]
    assert queued.json()["symbol"] == "GER40"

    calls: list[str] = []
    original = src.calc_margin

    def recording(direction: Any, symbol: str, volume: Decimal, price: Decimal) -> Decimal:
        calls.append(symbol)
        return original(direction, symbol, volume, price)

    monkeypatch.setattr(src, "calc_margin", recording)
    assert run_margin_cycle(factory, src, threading.Lock(), password_for=password) == request_id
    assert calls == ["GER30"]
    done = client.get(f"/api/calculator/margin-requests/{request_id}").json()
    assert done["status"] == "done", done
    assert done["symbol"] == "GER40"
