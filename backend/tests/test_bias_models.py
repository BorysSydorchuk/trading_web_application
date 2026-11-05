"""DB constraints of bias_notes / bias_entries and the audio owner rule (M4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, AudioNote, BiasEntry, BiasNote, ChartLink, Trade
from app.models.enums import AccountPhase, BiasDirection, BiasKind, Direction

MONDAY = date(2026, 11, 2)
TUESDAY = date(2026, 11, 3)


def _note(session: Session, kind: BiasKind = BiasKind.PRE_NY, day: date = TUESDAY) -> BiasNote:
    note = BiasNote(kind=kind, period_date=day, raw_text="золото вгору")
    session.add(note)
    session.flush()
    return note


def _entry(session: Session, note: BiasNote, symbol: str = "XAUUSD", **kw: object) -> BiasEntry:
    entry = BiasEntry(bias_note_id=note.id, symbol=symbol, direction=BiasDirection.BULLISH, **kw)
    session.add(entry)
    session.flush()
    return entry


def _audio(session: Session, **owner: int) -> AudioNote:
    audio = AudioNote(file_path="audio/2026/11/x.webm", mime_type="audio/webm", **owner)
    session.add(audio)
    session.flush()
    return audio


def _trade(session: Session) -> Trade:
    account = Account(
        name="FN bias",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase=AccountPhase.PHASE_1,
        login=4242,
        server="FundedNext-Server",
        starting_balance=Decimal("100000.00"),
        currency="USD",
    )
    session.add(account)
    session.flush()
    trade = Trade(
        account_id=account.id,
        position_id=1,
        symbol="XAUUSD",
        direction=Direction.BUY,
        open_time=datetime(2026, 11, 3, 9, 0, tzinfo=UTC),
        close_time=datetime(2026, 11, 3, 9, 30, tzinfo=UTC),
        entry_price=Decimal("2650"),
        volume=Decimal("1"),
    )
    session.add(trade)
    session.flush()
    return trade


@pytest.mark.parametrize("kind", [BiasKind.PRE_LONDON, BiasKind.PRE_NY])
def test_daily_note_any_weekday(db_session: Session, kind: BiasKind) -> None:
    _note(db_session, kind, TUESDAY)


def test_weekly_note_on_monday_ok(db_session: Session) -> None:
    _note(db_session, BiasKind.WEEKLY, MONDAY)


@pytest.mark.parametrize("day", [TUESDAY, date(2026, 11, 8)])  # Tuesday, Sunday
def test_weekly_note_not_monday_rejected(db_session: Session, day: date) -> None:
    with pytest.raises(IntegrityError, match="ck_bias_notes_weekly_is_monday"):
        _note(db_session, BiasKind.WEEKLY, day)


def test_monthly_note_on_first_ok(db_session: Session) -> None:
    _note(db_session, BiasKind.MONTHLY, date(2026, 11, 1))


def test_monthly_note_not_first_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_bias_notes_monthly_is_first"):
        _note(db_session, BiasKind.MONTHLY, MONDAY)


def test_note_kind_invalid_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_bias_notes_kind_valid"):
        _note(db_session, "daily", TUESDAY)  # type: ignore[arg-type]


def test_one_note_per_kind_and_period(db_session: Session) -> None:
    _note(db_session)
    _note(db_session, BiasKind.PRE_LONDON)  # other kind, same day: fine
    with pytest.raises(IntegrityError, match="uq_bias_notes_kind_period_date"):
        _note(db_session)


def test_one_entry_per_note_and_symbol(db_session: Session) -> None:
    note = _note(db_session)
    _entry(db_session, note, "XAUUSD")
    _entry(db_session, note, "GER40")
    with pytest.raises(IntegrityError, match="uq_bias_entries_bias_note_id_symbol"):
        _entry(db_session, note, "XAUUSD")


def test_entry_needs_note(db_session: Session) -> None:
    db_session.add(BiasEntry(symbol="XAUUSD", direction=BiasDirection.BULLISH))
    with pytest.raises(IntegrityError, match="bias_note_id"):
        db_session.flush()


def test_entry_confidence_range(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_bias_entries_confidence_range"):
        _entry(db_session, _note(db_session), confidence=4)


def test_audio_owned_by_bias_note_ok(db_session: Session) -> None:
    note = _note(db_session)
    audio = _audio(db_session, bias_note_id=note.id)
    assert audio.trade_id is None


def test_audio_without_owner_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_audio_notes_one_owner"):
        _audio(db_session)


def test_audio_with_trade_and_bias_note_rejected(db_session: Session) -> None:
    note = _note(db_session)
    trade = _trade(db_session)
    with pytest.raises(IntegrityError, match="ck_audio_notes_one_owner"):
        _audio(db_session, bias_note_id=note.id, trade_id=trade.id)


def test_note_delete_cascades_entries_links_audio(db_session: Session) -> None:
    note = _note(db_session)
    entry = _entry(db_session, note)
    db_session.add(
        ChartLink(bias_entry_id=entry.id, url="https://www.tradingview.com/x/b/", kind="bias")
    )
    _audio(db_session, bias_note_id=note.id)
    db_session.expunge_all()
    stored = db_session.get(BiasNote, note.id)
    assert stored is not None
    db_session.delete(stored)
    db_session.flush()
    db_session.expunge_all()
    assert db_session.scalars(select(BiasEntry)).all() == []
    assert db_session.scalars(select(ChartLink)).all() == []
    assert db_session.scalars(select(AudioNote)).all() == []


def test_note_relationships_ordered(db_session: Session) -> None:
    note = _note(db_session)
    first = _entry(db_session, note, "XAUUSD")
    second = _entry(db_session, note, "EURUSD")
    db_session.expire(note)
    assert [e.id for e in note.entries] == [first.id, second.id]
