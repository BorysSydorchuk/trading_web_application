"""Trade check tool: DB trades (seeded from basic_week via the domain) vs fixture MT5 deals."""

# ruff: noqa: RUF001
# RUF001: expected report text is Ukrainian with math signs on purpose.

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.db import make_session_factory
from app.domain.broker_time import BrokerTimeRule
from app.domain.metrics import (
    balance_at_open,
    planned_rr,
    pnl_pct,
    r_multiple,
    risk_amount,
    risk_pct,
)
from app.domain.trade_builder import DealType, OrderStops, build_trades, next_status
from app.models.account import Account
from app.models.enums import AccountPhase
from app.models.trade import Trade
from app.mt5.convert import digits_by_symbol, order_stops, to_deals
from app.mt5.errors import Mt5Error, Mt5ErrorCode
from app.mt5.fixture import FixtureMt5Source
from app.mt5.types import RawDeal, from_json_dict
from app.tools import trade_check
from app.tools.trade_check import TradeCheckError, build_report, mt5_side

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mt5" / "basic_week.json"
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)  # basic_week step 0 ("now" tick)
LOGIN = 51234567
SECRET = "topsecret-investor"  # noqa: S105 - fake test password
RULE = BrokerTimeRule.NY_CLOSE


def password_for(login: int) -> SecretStr | None:
    return SecretStr(SECRET) if login == LOGIN else None


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    def truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE accounts RESTART IDENTITY CASCADE"))

    truncate()
    yield
    truncate()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    db = make_session_factory(db_engine)()
    try:
        yield db
    finally:
        db.close()


def fixture_source() -> FixtureMt5Source:
    return FixtureMt5Source.from_file(FIXTURE)


def seed(session: Session) -> Account:
    """Closed basic_week trades into the DB the way a sync would compute them."""
    account = Account(
        name="FN P1",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase=AccountPhase.PHASE_1.value,
        login=LOGIN,
        server="FundedNext-Server",
        terminal_path="D:/MT5/fn/terminal64.exe",
        starting_balance=Decimal("100000.00"),
        reference_balance=Decimal("100000.00"),  # account size (M5-10)
        currency="USD",
    )
    session.add(account)
    session.commit()

    src = fixture_source()
    info = src.connect("x", LOGIN, SecretStr(SECRET), "FundedNext-Server")
    specs = {s.name: s for s in src.symbols_matching(["EURUSD", "GBPUSD", "XAUUSD", "GER40"])}
    digits = digits_by_symbol(specs.values())
    deals = to_deals(src.deals(0, 2**31), RULE, digits)
    orders: dict[int, OrderStops] = {}
    for d in deals:
        if d.type in (DealType.BUY, DealType.SELL):
            o = src.opening_order(d.order)
            if o is not None:
                orders[o.ticket] = order_stops(o, digits)
    result = build_trades(deals, orders)
    for t in result.trades:
        if not t.is_closed:
            continue
        spec = specs[t.symbol]
        risk = risk_amount(
            entry_price=t.entry_price,
            initial_sl=t.initial_sl,
            volume=t.volume,
            exit_price=t.exit_price,
            exit_volume=t.exit_volume,
            gross_pnl=t.gross_pnl,
            tick_size=spec.tick_size,
            tick_value=spec.tick_value,
        )
        bal = balance_at_open(info.balance, t.open_time, deals)
        values: dict[str, Any] = {
            "account_id": account.id,
            "position_id": t.position_id,
            "symbol": t.symbol,
            "direction": t.direction.value,
            "open_time": t.open_time,
            "close_time": t.close_time,
            "duration_seconds": t.duration_seconds,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "volume": t.volume,
            "initial_sl": t.initial_sl,
            "initial_sl_source": t.initial_sl_source.value if t.initial_sl_source else None,
            "tp": t.tp,
            "commission": t.commission,
            "swap": t.swap,
            "gross_pnl": t.gross_pnl,
            "net_pnl": t.net_pnl,
            "balance_at_open": bal,
            "risk_amount": risk,
            "risk_pct": risk_pct(risk, account_size=account.reference_balance),
            "pnl_pct": pnl_pct(t.net_pnl, account_size=account.reference_balance),
            "r_multiple": r_multiple(t.net_pnl, risk),
            "planned_rr": planned_rr(t.entry_price, t.initial_sl, t.tp),
            "status": next_status(
                None, is_closed=True, has_initial_sl=t.initial_sl is not None
            ).value,
        }
        session.add(Trade(**values))
    session.commit()
    return account


def report(session: Session, source: Any = None, last: int = 5, **kw: Any) -> Any:
    src = fixture_source() if source is None else source
    return build_report(
        session, "FN P1", last, src, now=NOW, password_for=password_for, rule=RULE, **kw
    )


def test_last_five_trades_all_match(session: Session) -> None:
    seed(session)
    rep = report(session)
    assert [b.trade.position_id for b in rep.blocks] == [
        2000201,
        2000301,
        2000401,
        2000501,
        2000601,
    ]
    assert rep.mt5_error is None
    assert rep.all_match, rep.markdown
    assert "**Підсумок: 5/5 trades match** ✓" in rep.markdown
    assert SECRET not in rep.markdown
    # Server time (MT5 History) and Brussels time of T2 (Mon 15:05 server = 14:05 Brussels).
    md = rep.markdown
    assert "| Відкриття, час сервера | 2026-10-19 15:05:00 | 2026-10-19 15:05:00 | ✓ |" in md
    assert "| Відкриття, Брюссель | 2026-10-19 14:05:00 |  |  |" in md
    assert "| Ціна входу (VWAP) | 1.34050 | 1.34050 | ✓ |" in md  # scale-in VWAP
    assert "| Чистий P&L | 92.80 | 92.80 | ✓ |" in md
    assert "| Обсяг, лоти | 1.00 | 1.00 | ✓ |" in md
    assert "| R | 0.9829 |  |  |" in md
    assert "R = чистий P&L / ризик = 497.00 / 350.00 = 1.4200." in md
    assert "Ризик % = ризик / розмір рахунку × 100 = 500.00 / 100000.00 × 100 = 0.5000 %." in md
    assert "статус needs_sl" in md  # T5 has no SL


def test_partial_close_trade_and_formula(session: Session) -> None:
    seed(session)
    rep = report(session, last=6)
    t1 = rep.blocks[0]
    assert t1.trade.position_id == 2000101
    assert not t1.mismatches
    md = rep.markdown
    assert "| Ціна виходу (VWAP) | 1.16790 | 1.16790 | ✓ |" in md
    assert "| Закриття, час сервера | 2026-10-19 12:30:00 | 2026-10-19 12:30:00 | ✓ |" in md
    assert (
        "Ризик = |валовий P&L| × |вхід − SL| / |вихід − вхід| = 290.00 × |1.16500 − 1.16200| "
        "/ |1.16790 − 1.16500| ≈ 300.00"
    ) in md
    assert "6/6 trades match" in md


def test_mismatch_is_flagged(session: Session) -> None:
    account = seed(session)
    trade = session.query(Trade).filter_by(account_id=account.id, position_id=2000601).one()
    trade.net_pnl = Decimal("349.00")
    trade.exit_price = Decimal("24260.02")
    session.commit()
    rep = report(session)
    assert not rep.all_match
    block = next(b for b in rep.blocks if b.trade.position_id == 2000601)
    assert block.mismatches == ["Ціна виходу (VWAP)", "Чистий P&L"]
    assert "| Чистий P&L | 349.00 | 348.00 | ✗ |" in rep.markdown
    assert (
        "**Підсумок: 4/5 trades match** ✗ — розбіжності: позиція 2000601: "
        "Ціна виходу (VWAP), Чистий P&L"
    ) in rep.markdown


def test_money_within_one_cent_matches(session: Session) -> None:
    account = seed(session)
    trade = session.query(Trade).filter_by(account_id=account.id, position_id=2000601).one()
    trade.commission = Decimal("0.01")
    session.commit()
    assert report(session).all_match


def test_terminal_unreachable_prints_app_side(session: Session) -> None:
    seed(session)
    src = fixture_source()
    src.fail("connect", Mt5Error(Mt5ErrorCode.LOGIN_FAILED, "initialize failed: auth"))
    rep = report(session, source=src)
    assert rep.mt5_error == "[login_failed] initialize failed: auth"
    assert not rep.all_match
    assert "**MT5 недоступний: [login_failed]" in rep.markdown
    assert "| Чистий P&L | 344.00 |  |  |" in rep.markdown
    assert "порівняння з MT5 не виконано" in rep.markdown


def test_password_missing_is_reported(session: Session) -> None:
    seed(session)
    rep = build_report(
        session, "fn p1", 5, fixture_source(), now=NOW, password_for=lambda _: None, rule=RULE
    )
    assert rep.mt5_error is not None
    assert "password_missing" in rep.mt5_error
    assert f"MT5_PASSWORD_{LOGIN}" in rep.mt5_error


def test_no_source_and_unknown_account(session: Session) -> None:
    seed(session)
    rep = build_report(session, "1", 5, None, now=NOW, password_for=password_for, rule=RULE)
    assert "MT5 не запитувався" in rep.markdown
    with pytest.raises(TradeCheckError, match="not found"):
        build_report(session, "nope", 5, None, now=NOW, rule=RULE)


def test_position_missing_in_mt5(session: Session) -> None:
    account = seed(session)
    trade = session.query(Trade).filter_by(account_id=account.id, position_id=2000601).one()
    trade.position_id = 9999999
    session.commit()
    rep = report(session)
    assert "MT5 не повернув угод для цієї позиції." in rep.markdown
    assert "позиція 9999999: немає в MT5" in rep.markdown


def _raw(ticket: int, entry: int, typ: int, volume: str, price: str, **kw: Any) -> RawDeal:
    data: dict[str, Any] = {
        "ticket": ticket,
        "order": ticket,
        "position_id": 1,
        "time": 1_000 + ticket,
        "type": typ,
        "entry": entry,
        "volume": volume,
        "price": price,
        "profit": "0",
        "symbol": "EURUSD",
    }
    data.update(kw)
    return from_json_dict(RawDeal, data)


def test_mt5_side_sums() -> None:
    deals = [
        _raw(1, 0, 0, "1", "1.1", commission="-3"),
        _raw(2, 1, 1, "0.4", "1.2", profit="40", commission="-1.2", fee="-0.1"),
        _raw(3, 1, 1, "0.6", "1.3", profit="120", swap="-2"),
        _raw(9, 0, 2, "0", "0", profit="1000"),  # balance deal is ignored
    ]
    side = mt5_side(1, deals)
    assert side is not None
    assert side.entry_price == Decimal("1.1")
    assert side.exit_price == Decimal("1.26")
    assert side.volume == Decimal("1")
    assert side.profit == Decimal("160")
    assert side.commission == Decimal("-4.3")
    assert side.net == Decimal("153.7")
    assert side.close_server == datetime(1970, 1, 1, 0, 16, 43)  # noqa: DTZ001 - server wall
    open_only = mt5_side(1, deals[:2])
    assert open_only is not None
    assert open_only.close_server is None
    assert mt5_side(1, [deals[3]]) is None
    inout = mt5_side(1, [deals[0], _raw(4, 2, 1, "2", "1.2")])
    assert inout is not None
    assert inout.note is not None


def test_cli_writes_markdown(session: Session, tmp_path: Path) -> None:
    seed(session)
    out = tmp_path / "check.md"
    code = trade_check.main(
        ["--account", "FN P1", "--last", "5", "--source", "none", "--out", str(out)]
    )
    assert code == 0
    text_out = out.read_text(encoding="utf-8")
    assert text_out.startswith("# Звірка угод: FN P1")
    assert trade_check.main(["--account", "missing", "--source", "none"]) == 2


def test_formats() -> None:
    assert trade_check.fmt_volume(Decimal("1")) == "1.00"
    assert trade_check.fmt_volume(Decimal("0.125")) == "0.125"
    assert trade_check.fmt_ratio(Decimal("2")) == "2.0000"
    assert trade_check.fmt_price(Decimal("1.1679"), 5) == "1.16790"
    assert trade_check.fmt_price(Decimal("1.16790000"), None) == "1.1679"


def test_make_source_specs(tmp_path: Path) -> None:
    assert trade_check.make_source("none") is None
    assert isinstance(trade_check.make_source(f"fixture:{FIXTURE}"), FixtureMt5Source)
    assert type(trade_check.make_source("real")).__name__ == "RealMt5Source"
    with pytest.raises(TradeCheckError, match="fixture not found"):
        trade_check.make_source(f"fixture:{tmp_path / 'x.json'}")
    with pytest.raises(TradeCheckError, match="--source"):
        trade_check.make_source("bogus")


def test_mt5_deals_are_compared_with_the_broker_symbol(session: Session) -> None:
    """M5-08: the stored `symbol` is canonical; MT5 deals carry the broker name."""
    account = seed(session)
    for trade in session.scalars(select(Trade).where(Trade.account_id == account.id)):
        if trade.symbol == "GER40":
            trade.symbol = "DAX"  # canonical name differs from the broker's GER40
    session.commit()

    rep = report(session)

    assert [b.trade.symbol for b in rep.blocks].count("DAX") == 2
    assert rep.mt5_error is None
    assert rep.all_match, rep.markdown


def test_risk_percent_formula_uses_the_account_size_not_the_balance_at_open(
    session: Session,
) -> None:
    account = seed(session)
    account.reference_balance = Decimal("50000.00")
    trade = session.query(Trade).filter_by(account_id=account.id, position_id=2000301).one()
    trade.risk_pct = Decimal("1.0000")  # 500.00 / 50000.00
    session.commit()

    md = report(session).markdown

    assert "Ризик % = ризик / розмір рахунку × 100 = 500.00 / 50000.00 × 100 = 1.0000 %." in md
    assert "баланс на відкритті × 100" not in md
    assert "| Баланс на відкритті |" in md  # still shown as information
