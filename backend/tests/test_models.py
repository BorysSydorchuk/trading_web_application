"""DB-level constraints and defaults of the schema (run against the migrated test DB)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, BiasEntry, ChartLink, Digest, RuleViolation, Trade, TradeExitDeal
from app.models.enums import (
    AccountPhase,
    BiasDirection,
    BiasKind,
    ChartLinkKind,
    DigestKind,
    Direction,
    TradeStatus,
    ViolationSource,
)

OPEN_TIME = datetime(2026, 10, 30, 8, 15, tzinfo=UTC)
CLOSE_TIME = datetime(2026, 10, 30, 9, 40, tzinfo=UTC)


def _account(session: Session, login: int = 1001) -> Account:
    account = Account(
        name=f"FundedNext {login}",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase=AccountPhase.PHASE_1,
        login=login,
        server="FundedNext-Server",
        starting_balance=Decimal("100000.00"),
        currency="USD",
    )
    session.add(account)
    session.flush()
    return account


def _trade(session: Session, account: Account, position_id: int = 555, **kw: object) -> Trade:
    fields: dict[str, object] = {
        "account_id": account.id,
        "position_id": position_id,
        "symbol": "GER40",
        "direction": Direction.BUY,
        "open_time": OPEN_TIME,
        "close_time": CLOSE_TIME,
        "entry_price": Decimal("19500.50"),
        "volume": Decimal("1.25"),
    }
    trade = Trade(**(fields | kw))
    session.add(trade)
    session.flush()
    return trade


def test_trade_defaults(db_session: Session) -> None:
    trade = _trade(db_session, _account(db_session))
    db_session.refresh(trade)

    assert trade.extra == {}
    assert trade.ai_filled_fields == []
    assert trade.status == TradeStatus.NEEDS_DESCRIPTION
    assert trade.is_reentry is False
    assert trade.commission == Decimal("0.00")
    assert trade.created_at.tzinfo is not None
    assert trade.updated_at.tzinfo is not None
    # Decimal round-trip keeps precision.
    assert trade.entry_price == Decimal("19500.50000000")


def test_account_defaults_to_active(db_session: Session) -> None:
    account = _account(db_session)
    db_session.refresh(account)
    assert account.status == "active"


def test_extra_accepts_unknown_journal_keys(db_session: Session) -> None:
    trade = _trade(db_session, _account(db_session), extra={"news_event": "NFP"})
    db_session.expire_all()
    stored = db_session.scalars(select(Trade).where(Trade.id == trade.id)).one()
    assert stored.extra == {"news_event": "NFP"}


def test_journal_option_fields_have_no_check(db_session: Session) -> None:
    """Options live in journal_fields.yaml; any (old or new) value must be storable."""
    _trade(
        db_session,
        _account(db_session),
        entry_model="some_deprecated_model",
        emotion_before="new_emotion",
    )


def test_position_unique_per_account(db_session: Session) -> None:
    account = _account(db_session)
    _trade(db_session, account, position_id=777)
    with pytest.raises(IntegrityError, match="uq_trades_account_id_position_id"):
        _trade(db_session, account, position_id=777)


def test_same_position_id_allowed_on_other_account(db_session: Session) -> None:
    _trade(db_session, _account(db_session, login=1), position_id=777)
    _trade(db_session, _account(db_session, login=2), position_id=777)


@pytest.mark.parametrize("rating", [0, 6])
def test_quality_rating_out_of_range_rejected(db_session: Session, rating: int) -> None:
    with pytest.raises(IntegrityError, match="ck_trades_quality_rating_range"):
        _trade(db_session, _account(db_session), quality_rating=rating)


@pytest.mark.parametrize("rating", [1, 5])
def test_quality_rating_bounds_accepted(db_session: Session, rating: int) -> None:
    _trade(db_session, _account(db_session), quality_rating=rating)


def test_invalid_system_enum_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_trades_direction_valid"):
        _trade(db_session, _account(db_session), direction="long")


def test_extra_must_be_object(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_trades_extra_is_object"):
        _trade(db_session, _account(db_session), extra=[1, 2])


def _bias(session: Session) -> BiasEntry:
    bias = BiasEntry(
        kind=BiasKind.PRE_LONDON,
        period_date=date(2026, 10, 30),
        symbol="GER40",
        direction=BiasDirection.BULLISH,
        confidence=2,
    )
    session.add(bias)
    session.flush()
    return bias


def test_chart_link_with_one_owner_ok(db_session: Session) -> None:
    trade = _trade(db_session, _account(db_session))
    bias = _bias(db_session)
    db_session.add_all(
        [
            ChartLink(trade_id=trade.id, url="https://www.tradingview.com/x/a/", kind="before"),
            ChartLink(bias_entry_id=bias.id, url="https://www.tradingview.com/x/b/", kind="bias"),
        ]
    )
    db_session.flush()


def test_chart_link_without_owner_rejected(db_session: Session) -> None:
    db_session.add(ChartLink(url="https://www.tradingview.com/x/a/", kind=ChartLinkKind.BEFORE))
    with pytest.raises(IntegrityError, match="ck_chart_links_one_owner"):
        db_session.flush()


def test_chart_link_with_two_owners_rejected(db_session: Session) -> None:
    trade = _trade(db_session, _account(db_session))
    bias = _bias(db_session)
    db_session.add(
        ChartLink(
            trade_id=trade.id,
            bias_entry_id=bias.id,
            url="https://www.tradingview.com/x/a/",
            kind=ChartLinkKind.BEFORE,
        )
    )
    with pytest.raises(IntegrityError, match="ck_chart_links_one_owner"):
        db_session.flush()


def test_bias_unique_per_kind_date_symbol(db_session: Session) -> None:
    _bias(db_session)
    with pytest.raises(IntegrityError, match="uq_bias_entries_kind_period_date_symbol"):
        _bias(db_session)


def test_bias_confidence_range(db_session: Session) -> None:
    db_session.add(
        BiasEntry(
            kind=BiasKind.PRE_NY,
            period_date=date(2026, 10, 30),
            symbol="XAUUSD",
            direction=BiasDirection.NO_TRADE,
            confidence=4,
        )
    )
    with pytest.raises(IntegrityError, match="ck_bias_entries_confidence_range"):
        db_session.flush()


def test_rule_violation_unique_per_trade(db_session: Session) -> None:
    trade = _trade(db_session, _account(db_session))
    db_session.add(RuleViolation(trade_id=trade.id, rule_key="min_rr", source=ViolationSource.AUTO))
    db_session.flush()
    db_session.add(RuleViolation(trade_id=trade.id, rule_key="min_rr", source=ViolationSource.USER))
    with pytest.raises(IntegrityError, match="uq_rule_violations_trade_id_rule_key"):
        db_session.flush()


def test_trade_delete_cascades_children(db_session: Session) -> None:
    account = _account(db_session)
    trade = _trade(db_session, account)
    db_session.add_all(
        [
            TradeExitDeal(
                trade_id=trade.id,
                account_id=account.id,
                ticket=9001,
                time=OPEN_TIME,
                price=Decimal("19520"),
                volume=Decimal("1.25"),
                profit=Decimal("25.00"),
            ),
            RuleViolation(trade_id=trade.id, rule_key="session", source=ViolationSource.AUTO),
            ChartLink(trade_id=trade.id, url="https://www.tradingview.com/x/a/", kind="before"),
        ]
    )
    db_session.flush()
    db_session.delete(trade)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.scalars(select(TradeExitDeal)).all() == []
    assert db_session.scalars(select(RuleViolation)).all() == []
    assert db_session.scalars(select(ChartLink)).all() == []


def test_account_with_trades_cannot_be_deleted(db_session: Session) -> None:
    account = _account(db_session)
    _trade(db_session, account)
    db_session.expunge_all()
    stored = db_session.get(Account, account.id)
    assert stored is not None
    db_session.delete(stored)
    with pytest.raises(IntegrityError, match="fk_trades_account_id_accounts"):
        db_session.flush()


def test_digest_period_order(db_session: Session) -> None:
    db_session.add(
        Digest(
            kind=DigestKind.WEEKLY,
            period_start=date(2026, 10, 26),
            period_end=date(2026, 10, 25),
        )
    )
    with pytest.raises(IntegrityError, match="ck_digests_period_order"):
        db_session.flush()


def test_open_trade_has_no_close_time(db_session: Session) -> None:
    trade = _trade(db_session, _account(db_session), status=TradeStatus.OPEN, close_time=None)
    assert trade.close_time is None


def test_open_status_with_close_time_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_trades_open_iff_no_close_time"):
        _trade(db_session, _account(db_session), status=TradeStatus.OPEN)


def test_closed_status_without_close_time_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_trades_open_iff_no_close_time"):
        _trade(db_session, _account(db_session), close_time=None)


def test_new_sync_columns_nullable(db_session: Session) -> None:
    account = _account(db_session)
    trade = _trade(db_session, account, last_sl=Decimal("19500.50"))
    db_session.add(
        TradeExitDeal(
            trade_id=trade.id,
            account_id=account.id,
            ticket=9002,
            time=CLOSE_TIME,
            price=Decimal("19500.50"),
            volume=Decimal("1.25"),
            profit=Decimal("0.00"),
            reason="sl",
        )
    )
    account.balance = Decimal("100250.00")
    account.equity = Decimal("100100.00")
    account.balance_synced_at = CLOSE_TIME
    db_session.flush()
    db_session.refresh(account)
    assert account.balance == Decimal("100250.00")


@pytest.mark.parametrize("source", ["deal", "order", "position", "user", None])
def test_initial_sl_source_values(db_session: Session, source: str | None) -> None:
    trade = _trade(db_session, _account(db_session), initial_sl_source=source)
    db_session.refresh(trade)
    assert trade.initial_sl_source == source


def test_initial_sl_source_invalid_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_trades_initial_sl_source_valid"):
        _trade(db_session, _account(db_session), initial_sl_source="guess")
