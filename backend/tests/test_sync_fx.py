"""Sync writes the FX rate and the MT5 loss-value check (docs/api.md "M5-09 Cross-currency").

Per sync cycle, for every cross-currency spec (profit currency != account currency):

- find the conversion pair at the broker (direct ``<P><A>`` -> ask, inverse ``<A><P>`` -> 1/bid),
  read its quote, upsert ``fx_rates`` (unique per account + from + to): ``rate_at`` = the quote's
  server time converted to UTC with the account's server offset, ``synced_at`` = sync time;
- run ``calc_profit`` (1 lot, buy at the symbol's own ask p, close at p - N * tick_size with
  N = floor(p * 0.01 / tick_size)) and store ``symbol_specs.mt5_loss_per_tick`` = |result| / N and
  ``mt5_loss_per_tick_at`` = sync time; WARNING (both values) when it differs by > 0.5 %;
- no pair or no quote: no row is written, WARNING; check failure: WARNING, no check value, the
  rate row is still written. None of this fails the sync.
- the open trade's risk uses the rate written in the same sync (or the check value by the 0.5 %
  rule).

Fixture: tests/fixtures/mt5/funded_next_ger30.json plus the optional keys ``quotes`` and
``profit_per_tick`` (tests/fixtures/mt5/README.md "Quotes and profit check"). Fixture values are
SYNTHETIC: GER30 contract size 1, tick 0.01 -> 0.01 * 1 * 1.1091 = 0.011091 per tick per lot.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config_files import get_rules
from app.config_files.rules import RulesConfig
from app.config_files.symbols import SymbolsConfig
from app.db import make_session_factory
from app.models import Account, FxRate, SymbolSpec, SyncLog, Trade
from app.mt5.convert import server_epoch
from app.mt5.fixture import FixtureMt5Source
from app.services.sync import sync_account
from tests.services.test_bias_alignment_service import truncate_all
from tests.symbols_fixture import TEST_SYMBOLS
from tests.test_sync import FIXTURES, add_account, password

D = Decimal
GER30_LOGIN = 51234571
NOW = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)  # 15:00 Brussels; server (ny_close, +2) 16:00
SERVER_WALL = datetime(2026, 11, 3, 16, 0)  # noqa: DTZ001  # naive server wall clock of NOW
QUOTE_TIME = server_epoch(SERVER_WALL)
RATE_AT = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
OPEN_PID = 8000201  # GER30 sell 2.0 lots, entry 24100, SL 24130 (3000 ticks), open


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    truncate_all(db_engine)
    yield
    truncate_all(db_engine)


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


def quote(bid: str, ask: str, time: int = QUOTE_TIME) -> dict[str, Any]:
    return {"bid": bid, "ask": ask, "time": time}


def fx_data(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "funded_next_ger30.json").read_text("utf-8"))
    data = copy.deepcopy(data)
    data["quotes"] = {
        "EURUSD": quote("1.10905", "1.1091"),
        "GER30": quote("24099.50", "24100.50"),
    }
    data["profit_per_tick"] = {"GER30": "0.011091"}  # agrees with the rate: 0.01 * 1 * 1.1091
    return data | extra


def run(
    session: Session,
    account: Account,
    src: FixtureMt5Source,
    rules: RulesConfig,
    now: datetime = NOW,
    symbols: SymbolsConfig = TEST_SYMBOLS,
) -> SyncLog:
    return sync_account(session, account, src, rules, now, password_for=password, symbols=symbols)


def rates(session: Session, account: Account) -> list[FxRate]:
    session.expire_all()
    return list(
        session.scalars(
            select(FxRate).where(FxRate.account_id == account.id).order_by(FxRate.from_currency)
        )
    )


def spec(session: Session, account: Account, name: str = "GER30") -> SymbolSpec:
    session.expire_all()
    return session.scalars(
        select(SymbolSpec).where(SymbolSpec.account_id == account.id, SymbolSpec.symbol == name)
    ).one()


def open_trade(session: Session, account: Account) -> Trade:
    session.expire_all()
    return session.scalars(
        select(Trade).where(Trade.account_id == account.id, Trade.position_id == OPEN_PID)
    ).one()


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.fixture
def account(session: Session) -> Account:
    return add_account(session, GER30_LOGIN)


# --- the rate row ----------------------------------------------------------------------------


def test_sync_writes_one_rate_row_for_the_cross_currency_spec(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    log = run(session, account, FixtureMt5Source(fx_data()), rules)

    assert log.ok is True, log.error_message
    [row] = rates(session, account)  # EURUSD/GBPUSD/XAUUSD are USD-profit: no rows for them
    assert (row.from_currency, row.to_currency) == ("EUR", "USD")
    assert row.pair == "EURUSD"
    assert row.inverted is False
    assert (row.bid, row.ask, row.rate) == (D("1.10905"), D("1.1091"), D("1.1091"))
    assert row.rate_at == RATE_AT  # quote time (server 16:00, +2) -> 14:00 UTC, not sync time
    assert row.synced_at == NOW


def test_rate_at_is_the_quote_time_not_the_sync_time(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    earlier = server_epoch(datetime(2026, 11, 3, 15, 41))  # noqa: DTZ001  # 13:41 UTC
    data = fx_data(
        quotes={"EURUSD": quote("1.1", "1.1001", earlier), "GER30": quote("1", "24100.5")}
    )

    run(session, account, FixtureMt5Source(data), rules)

    [row] = rates(session, account)
    assert row.rate_at == datetime(2026, 11, 3, 13, 41, tzinfo=UTC)
    assert row.synced_at == NOW


def test_second_sync_updates_the_same_row(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    later = QUOTE_TIME + 600
    data = fx_data(steps=[{"quotes": {
        "EURUSD": quote("1.1200", "1.1201", later),
        "GER30": quote("24099.50", "24100.50", later),
    }}])  # fmt: skip
    src = FixtureMt5Source(data)
    assert run(session, account, src, rules).ok is True
    src.advance()

    log = run(session, account, src, rules, NOW + timedelta(minutes=10))

    assert log.ok is True, log.error_message
    [row] = rates(session, account)
    assert row.rate == D("1.1201")
    assert (row.bid, row.ask) == (D("1.1200"), D("1.1201"))
    assert row.rate_at == RATE_AT + timedelta(minutes=10)
    assert row.synced_at == NOW + timedelta(minutes=10)


def test_inverse_pair_stores_one_over_bid(session: Session, rules: RulesConfig) -> None:
    """Swiss index (profit CHF) on a USD account; only USDCHF exists: rate = 1 / bid."""
    swi = {
        "name": "SWI20", "digits": 0, "contract_size": "1", "tick_size": "1", "tick_value": "1.1",
        "volume_min": "0.1", "volume_step": "0.1", "volume_max": "100", "currency_profit": "CHF",
        "currency_margin": "CHF", "point": "1", "tick_value_loss": "1.1",
    }  # fmt: skip
    usdchf = swi | {
        "name": "USDCHF",
        "digits": 5,
        "tick_size": "0.00001",
        "point": "0.00001",
        "contract_size": "100000",
        "currency_margin": "USD",
    }
    data = fx_data(
        symbols=[swi, usdchf],
        quotes={"USDCHF": quote("0.8", "0.8002"), "SWI20": quote("11000", "11001")},
        profit_per_tick={"SWI20": "1.25"},
        deals=[],
        orders=[],
        positions=[],
        ticks={},
    )
    symbols = SymbolsConfig.model_validate({"symbols": [{"name": "SWI20"}, {"name": "USDCHF"}]})
    account = add_account(session, GER30_LOGIN)

    log = run(session, account, FixtureMt5Source(data), rules, symbols=symbols)

    assert log.ok is True, log.error_message
    by_from = {r.from_currency: r for r in rates(session, account)}
    row = by_from["CHF"]
    assert (row.to_currency, row.pair, row.inverted) == ("USD", "USDCHF", True)
    assert (row.bid, row.ask, row.rate) == (D("0.8"), D("0.8002"), D("1.25"))


def test_currencies_are_stored_upper_case_so_mixed_case_reuses_one_row(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    data = fx_data()
    data["account"]["currency"] = "usd"
    data["symbols"] = [
        s | {"currency_profit": "eur"} if s["name"] == "GER30" else s for s in data["symbols"]
    ]
    assert run(session, account, FixtureMt5Source(fx_data()), rules).ok is True

    log = run(session, account, FixtureMt5Source(data), rules, NOW + timedelta(minutes=1))

    assert log.ok is True, log.error_message
    [row] = rates(session, account)
    assert (row.from_currency, row.to_currency) == ("EUR", "USD")
    assert row.synced_at == NOW + timedelta(minutes=1)
    assert open_trade(session, account).risk_amount == D("66.55")


def test_symbols_in_the_account_currency_get_no_rate_rows(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    data = fx_data()
    data["symbols"] = [s for s in data["symbols"] if s["name"] != "GER30"]

    run(session, account, FixtureMt5Source(data), rules)

    assert rates(session, account) == []


# --- missing pair / quote ----------------------------------------------------------------------


def test_no_conversion_pair_at_the_broker_writes_no_row_and_warns(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = fx_data()
    data["symbols"] = [s for s in data["symbols"] if s["name"] != "EURUSD"]
    data["ticks"].pop("EURUSD", None)
    data["quotes"].pop("EURUSD")

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    assert rates(session, account) == []
    assert any("EUR" in m and "USD" in m for m in warnings(caplog)), warnings(caplog)


def test_pair_without_a_quote_writes_no_row_and_warns(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = fx_data()
    data["quotes"].pop("EURUSD")

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    assert rates(session, account) == []
    assert any("EURUSD" in m for m in warnings(caplog)), warnings(caplog)


def test_a_quote_error_is_a_warning_and_never_fails_the_sync(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = fx_data(failures={"quote": {"code": "mt5_error", "message": "tick boom"}})

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    assert rates(session, account) == []
    assert (spec(session, account).mt5_loss_per_tick, open_trade(session, account).risk_amount) == (
        None,
        None,
    )
    assert any("tick boom" in m and "EURUSD" in m for m in warnings(caplog)), warnings(caplog)


def test_a_missing_quote_does_not_replace_an_older_rate_row(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    data = fx_data(steps=[{"quotes": {"GER30": quote("24099.50", "24100.50")}}])  # no EURUSD
    src = FixtureMt5Source(data)
    assert run(session, account, src, rules).ok is True
    before = rates(session, account)[0]
    src.advance()

    log = run(session, account, src, rules, NOW + timedelta(minutes=1))

    assert log.ok is True, log.error_message  # a missing rate never fails the sync
    [row] = rates(session, account)
    assert (row.rate, row.rate_at, row.synced_at) == (before.rate, RATE_AT, NOW)


# --- the MT5 check ---------------------------------------------------------------------------


def test_check_value_and_time_are_stored_without_a_warning_when_it_agrees(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    src = FixtureMt5Source(fx_data())

    with caplog.at_level(logging.WARNING):
        log = run(session, account, src, rules)

    assert log.ok is True, log.error_message
    ger30 = spec(session, account)
    assert ger30.mt5_loss_per_tick == D("0.011091")
    assert ger30.mt5_loss_per_tick_at == NOW
    assert not [m for m in warnings(caplog) if "GER30" in m or "0.011091" in m], warnings(caplog)


def test_check_runs_one_lot_with_a_one_percent_move_from_the_symbol_ask(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    calls: list[tuple[Any, ...]] = []
    src = FixtureMt5Source(fx_data())
    original = src.calc_profit

    def spy(
        direction: Any, symbol: str, volume: Decimal, price_open: Decimal, price_close: Decimal
    ) -> Decimal:
        calls.append((direction, symbol, volume, price_open, price_close))
        return original(direction, symbol, volume, price_open, price_close)

    src.calc_profit = spy  # type: ignore[method-assign]

    run(session, account, src, rules)

    # p = GER30 ask 24100.50; N = floor(24100.50 * 0.01 / 0.01) = 24100; close = p - N * tick.
    assert calls == [
        ("buy", "GER30", D("1"), D("24100.50"), D("24100.50") - D("24100") * D("0.01"))
    ]


def test_check_differing_by_more_than_half_a_percent_warns_with_both_values(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = fx_data(profit_per_tick={"GER30": "0.0125"})  # +12.7 % against 0.011091

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    assert spec(session, account).mt5_loss_per_tick == D("0.0125")
    messages = [m for m in warnings(caplog) if "0.0125" in m]
    assert messages, warnings(caplog)
    assert any("0.011091" in m for m in messages)


def test_check_failure_keeps_the_rate_and_stores_no_check_value(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = fx_data(failures={"calc_profit": {"code": "mt5_error", "message": "boom"}})

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    [row] = rates(session, account)
    assert row.rate == D("1.1091")
    ger30 = spec(session, account)
    assert (ger30.mt5_loss_per_tick, ger30.mt5_loss_per_tick_at) == (None, None)
    assert any("boom" in m or "calc_profit" in m or "check" in m.lower() for m in warnings(caplog))


def test_a_failed_check_clears_the_previous_check_value(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    assert run(session, account, FixtureMt5Source(fx_data()), rules).ok is True
    assert spec(session, account).mt5_loss_per_tick is not None
    failing = FixtureMt5Source(
        fx_data(failures={"calc_profit": {"code": "mt5_error", "message": "boom"}})
    )

    run(session, account, failing, rules, NOW + timedelta(minutes=1))

    ger30 = spec(session, account)
    assert (ger30.mt5_loss_per_tick, ger30.mt5_loss_per_tick_at) == (None, None)


def test_no_check_for_same_currency_specs(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    run(session, account, FixtureMt5Source(fx_data()), rules)

    for name in ("EURUSD", "GBPUSD", "XAUUSD"):
        row = spec(session, account, name)
        assert (row.mt5_loss_per_tick, row.mt5_loss_per_tick_at) == (None, None), name


# --- open trade risk in the same sync -------------------------------------------------------


def test_open_cross_currency_trade_risk_uses_the_rate_of_the_same_sync(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    run(session, account, FixtureMt5Source(fx_data()), rules)

    # 3000 ticks * 0.011091 * 2.0 lots = 66.546 -> 66.55 (tick_value 0.0116 would give 69.60).
    assert open_trade(session, account).risk_amount == D("66.55")


def test_open_trade_risk_uses_the_check_value_when_it_disagrees_by_more_than_half_a_percent(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    data = fx_data(profit_per_tick={"GER30": "0.0125"})

    run(session, account, FixtureMt5Source(data), rules)

    assert open_trade(session, account).risk_amount == D("75.00")  # 3000 * 0.0125 * 2


def test_open_trade_risk_is_none_without_any_rate(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    data = fx_data()
    data["quotes"].pop("EURUSD")

    run(session, account, FixtureMt5Source(data), rules)

    assert open_trade(session, account).risk_amount is None  # never the spec's tick_value


def test_closed_trade_keeps_its_realised_risk_with_a_rate(
    session: Session, account: Account, rules: RulesConfig
) -> None:
    run(session, account, FixtureMt5Source(fx_data()), rules)

    session.expire_all()
    closed = session.scalars(
        select(Trade).where(Trade.account_id == account.id, Trade.position_id == 8000101)
    ).one()
    assert closed.risk_amount == D("34.80")  # realised: 34.80 * 30 / 30


# --- bad data never fails the cycle (review HIGH-2) -------------------------------------------

WITH_FRA40 = SymbolsConfig.model_validate(
    {
        "symbols": [*TEST_SYMBOLS.model_dump()["symbols"], {"name": "FRA40"}],
        "firms": TEST_SYMBOLS.model_dump()["firms"],
    }
)


def with_fra40(**overrides: str) -> dict[str, Any]:
    """fx_data plus a second EUR-profit index FRA40 (with its own quote) carrying ``overrides``."""
    data = fx_data()
    ger30 = next(s for s in data["symbols"] if s["name"] == "GER30")
    data["symbols"] = [*data["symbols"], ger30 | {"name": "FRA40"} | overrides]
    data["quotes"]["FRA40"] = quote("8000", "8001")
    data["profit_per_tick"]["FRA40"] = "0.011091"
    return data


def assert_others_synced(session: Session, account: Account, log: SyncLog) -> None:
    assert log.ok is True, log.error_message
    for name in ("EURUSD", "GBPUSD", "XAUUSD", "GER30", "FRA40"):
        assert spec(session, account, name).synced_at == NOW, name
    [row] = rates(session, account)  # GER30's EUR->USD rate is still written
    assert (row.from_currency, row.rate) == ("EUR", D("1.1091"))
    assert open_trade(session, account).risk_amount == D("66.55")


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"currency_profit": ""}, "currency"),
        ({"tick_size": "0"}, "tick_size"),
        ({"tick_size": "-0.01"}, "tick_size"),
        ({"contract_size": "0"}, "contract_size"),
        ({"contract_size": "-1"}, "contract_size"),
    ],
)
def test_a_cross_spec_with_bad_fx_fields_is_skipped_with_a_warning(
    session: Session,
    account: Account,
    rules: RulesConfig,
    caplog: pytest.LogCaptureFixture,
    overrides: dict[str, str],
    needle: str,
) -> None:
    data = with_fra40(**overrides)

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules, symbols=WITH_FRA40)

    assert_others_synced(session, account, log)
    assert any("FRA40" in m and needle in m for m in warnings(caplog)), warnings(caplog)
    fra40 = spec(session, account, "FRA40")
    assert (fra40.mt5_loss_per_tick, fra40.mt5_loss_per_tick_at) == (None, None)


def test_blank_account_currency_skips_fx_with_a_warning(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = fx_data()
    data["account"]["currency"] = ""

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    assert rates(session, account) == []
    for name in ("EURUSD", "GBPUSD", "XAUUSD", "GER30"):
        assert spec(session, account, name).synced_at == NOW, name
    assert any("account currency" in m.lower() for m in warnings(caplog)), warnings(caplog)


def _patched_calc_profit(src: FixtureMt5Source, target: str, outcome: Decimal | Exception) -> None:
    original = src.calc_profit

    def patched(
        direction: Any, symbol: str, volume: Decimal, price_open: Decimal, price_close: Decimal
    ) -> Decimal:
        if symbol != target:
            return original(direction, symbol, volume, price_open, price_close)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    src.calc_profit = patched  # type: ignore[method-assign]


def test_an_arithmetic_error_in_the_check_is_a_warning(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    src = FixtureMt5Source(with_fra40())
    _patched_calc_profit(src, "FRA40", InvalidOperation("bad decimal"))

    with caplog.at_level(logging.WARNING):
        log = run(session, account, src, rules, symbols=WITH_FRA40)

    assert_others_synced(session, account, log)
    assert any("FRA40" in m and "check" in m for m in warnings(caplog)), warnings(caplog)
    assert spec(session, account, "FRA40").mt5_loss_per_tick is None


def test_a_positive_check_result_for_a_losing_buy_is_ignored_with_a_warning(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    """BUY closed lower must lose: a positive order_calc_profit is a sign anomaly, not used."""
    src = FixtureMt5Source(with_fra40())
    _patched_calc_profit(src, "FRA40", D("88.72"))

    with caplog.at_level(logging.WARNING):
        log = run(session, account, src, rules, symbols=WITH_FRA40)

    assert_others_synced(session, account, log)
    assert any("FRA40" in m and "88.72" in m for m in warnings(caplog)), warnings(caplog)
    fra40 = spec(session, account, "FRA40")
    assert (fra40.mt5_loss_per_tick, fra40.mt5_loss_per_tick_at) == (None, None)


# --- conversion pair prefix match (review HIGH-3) ---------------------------------------------


def _rename_eurusd(data: dict[str, Any], *names: str) -> dict[str, Any]:
    eurusd = next(s for s in data["symbols"] if s["name"] == "EURUSD")
    data["symbols"] = [s for s in data["symbols"] if s["name"] != "EURUSD"]
    data["symbols"] += [eurusd | {"name": n} for n in names]
    data["ticks"].pop("EURUSD", None)
    usd = data["quotes"].pop("EURUSD")
    data["quotes"] |= dict.fromkeys(names, usd)
    return data


def test_a_prefix_matched_pair_is_logged_at_info(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = _rename_eurusd(fx_data(), "EURUSD.r")

    with caplog.at_level(logging.INFO):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    [row] = rates(session, account)
    assert row.pair == "EURUSD.r"
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("EURUSD.r" in m for m in infos), infos
    assert not [m for m in warnings(caplog) if "EURUSD.r" in m], warnings(caplog)


def test_several_prefix_candidates_take_the_first_sorted_and_warn(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = _rename_eurusd(fx_data(), "EURUSD.r", "EURUSD#")

    with caplog.at_level(logging.INFO):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    [row] = rates(session, account)
    assert row.pair == "EURUSD#"
    assert any("EURUSD#" in m and "EURUSD.r" in m for m in warnings(caplog)), warnings(caplog)


def test_a_letter_suffixed_symbol_is_not_the_conversion_pair(
    session: Session, account: Account, rules: RulesConfig, caplog: pytest.LogCaptureFixture
) -> None:
    data = _rename_eurusd(fx_data(), "EURUSDT")

    with caplog.at_level(logging.WARNING):
        log = run(session, account, FixtureMt5Source(data), rules)

    assert log.ok is True, log.error_message
    assert rates(session, account) == []
    assert open_trade(session, account).risk_amount is None
