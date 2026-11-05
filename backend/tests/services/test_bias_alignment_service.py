"""Bias alignment recompute against the DB (app/services/bias_alignment.py, M4-04)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from app.config_files.loader import ConfigError
from app.db import make_session_factory
from app.domain.bias_alignment import AlignmentSettings
from app.models import Account, BiasEntry, BiasNote, Trade
from app.models.enums import BiasKind
from app.services import bias_alignment as service
from app.services.bias_alignment import (
    NoteScope,
    alignment_settings,
    recompute_after_sync,
    recompute_for_scopes,
    recompute_trades,
    scope_of,
)
from tests.test_trades_api import add_account, add_trade

SETTINGS = AlignmentSettings(
    symbols=("EURUSD", "GBPUSD", "XAUUSD", "GER40"), tz="Europe/Brussels", pre_ny_from=time(11)
)
TUE = date(2026, 11, 3)
LONDON = datetime(2026, 11, 3, 8, 30, tzinfo=UTC)  # 09:30 Brussels
NY = datetime(2026, 11, 3, 13, 30, tzinfo=UTC)  # 14:30 Brussels


def truncate_all(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE accounts, bias_notes RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _clean(db_engine: Engine) -> Iterator[None]:
    truncate_all(db_engine)
    yield
    truncate_all(db_engine)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    db = make_session_factory(db_engine)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def account(session: Session) -> Account:
    return add_account(session, "Alpha", 1)


def note(session: Session, kind: BiasKind, day: date, **directions: str) -> BiasNote:
    row = BiasNote(kind=kind.value, period_date=day)
    row.entries = [BiasEntry(symbol=s, direction=d) for s, d in directions.items()]
    session.add(row)
    session.flush()
    return row


def trade(session: Session, account: Account, **kw: Any) -> Trade:
    return add_trade(session, account, **kw)


def values(session: Session, t: Trade) -> tuple[str | None, str | None, str | None]:
    session.refresh(t)
    return t.bias_alignment, t.bias_alignment_weekly, t.bias_alignment_monthly


def test_real_config_settings() -> None:
    settings = alignment_settings()
    assert settings.pre_ny_from == time(11)
    assert settings.tz == "Europe/Brussels"
    assert "XAUUSD" in settings.symbols


def test_recompute_trades_sets_all_three(session: Session, account: Account) -> None:
    note(session, BiasKind.PRE_LONDON, TUE, XAUUSD="bullish")
    note(session, BiasKind.WEEKLY, date(2026, 11, 2), XAUUSD="bearish")
    t = trade(session, account, open_time=LONDON, close_time=None, status="open")
    assert recompute_trades(session, [t], SETTINGS) == 1
    assert values(session, t) == ("aligned", "counter", "no_bias")
    assert recompute_trades(session, [t], SETTINGS) == 0  # idempotent


def test_one_bias_query_per_batch(session: Session, account: Account, db_engine: Engine) -> None:
    note(session, BiasKind.PRE_NY, TUE, XAUUSD="bullish", GER40="bearish")
    trades = [
        trade(session, account, open_time=NY, symbol=s) for s in ("XAUUSD", "GER40.cash", "US30")
    ]
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(str(args[2]))

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        recompute_trades(session, trades, SETTINGS)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert sum("FROM bias_notes" in s for s in statements) == 1
    assert [values(session, t)[0] for t in trades] == ["aligned", "counter", "no_bias"]


def test_override_untouched(session: Session, account: Account) -> None:
    note(session, BiasKind.PRE_LONDON, TUE, XAUUSD="bearish")
    t = trade(
        session,
        account,
        open_time=LONDON,
        bias_alignment_override="aligned",
        bias_alignment_override_reason="manual",
    )
    recompute_trades(session, [t], SETTINGS)
    session.commit()
    session.refresh(t)
    assert t.bias_alignment == "counter"
    assert (t.bias_alignment_override, t.bias_alignment_override_reason) == ("aligned", "manual")


def test_scope_recompute_selects_period_and_symbol(session: Session, account: Account) -> None:
    hit = trade(session, account, open_time=NY, symbol="XAUUSD+")
    other_day = trade(session, account, open_time=datetime(2026, 11, 4, 13, 30, tzinfo=UTC))
    other_symbol = trade(session, account, open_time=NY, symbol="EURUSD")
    created = note(session, BiasKind.PRE_LONDON, TUE, XAUUSD="bullish")

    assert recompute_for_scopes(session, [None, scope_of(created)], SETTINGS) == 1
    assert values(session, hit)[0] == "aligned"  # pre_ny missing -> pre_london fallback
    assert values(session, other_day)[0] is None  # not selected
    assert values(session, other_symbol)[0] is None


def test_edit_delete_and_kind_change(session: Session, account: Account) -> None:
    london = trade(session, account, open_time=LONDON)
    ny = trade(session, account, open_time=NY)
    n = note(session, BiasKind.PRE_LONDON, TUE, XAUUSD="bullish")
    recompute_for_scopes(session, [scope_of(n)], SETTINGS)
    assert (values(session, london)[0], values(session, ny)[0]) == ("aligned", "aligned")

    # Edit: direction flips.
    old = scope_of(n)
    n.entries[0].direction = "bearish"
    recompute_for_scopes(session, [old, scope_of(n)], SETTINGS)
    assert (values(session, london)[0], values(session, ny)[0]) == ("counter", "counter")

    # Kind change pre_london -> pre_ny: London trade loses its bias, NY trade keeps one.
    old = scope_of(n)
    n.kind = BiasKind.PRE_NY.value
    recompute_for_scopes(session, [old, scope_of(n)], SETTINGS)
    assert (values(session, london)[0], values(session, ny)[0]) == ("no_bias", "counter")

    # Period change to the next day: both lose it.
    old = scope_of(n)
    n.period_date = date(2026, 11, 4)
    recompute_for_scopes(session, [old, scope_of(n)], SETTINGS)
    assert (values(session, london)[0], values(session, ny)[0]) == ("no_bias", "no_bias")

    # Delete.
    n.period_date = TUE
    recompute_for_scopes(session, [scope_of(n)], SETTINGS)
    old = scope_of(n)
    session.delete(n)
    recompute_for_scopes(session, [old, None], SETTINGS)
    assert values(session, ny)[0] == "no_bias"


def test_symbol_removed_from_note_is_recomputed(session: Session, account: Account) -> None:
    t = trade(session, account, open_time=NY, symbol="GER40.cash")
    n = note(session, BiasKind.MONTHLY, date(2026, 11, 1), GER40="bullish", XAUUSD="bearish")
    recompute_for_scopes(session, [scope_of(n)], SETTINGS)
    assert values(session, t)[2] == "aligned"
    old = scope_of(n)
    n.entries = [e for e in n.entries if e.symbol != "GER40"]
    recompute_for_scopes(session, [old, scope_of(n)], SETTINGS)
    assert values(session, t)[2] == "no_bias"


def test_like_wildcards_are_escaped(session: Session, account: Account) -> None:
    t = trade(session, account, open_time=NY, symbol="GERX40")
    scope = NoteScope(BiasKind.PRE_NY, TUE, frozenset({"GER_40", "GER%"}))
    assert recompute_for_scopes(session, [scope], SETTINGS) == 0
    assert values(session, t)[0] is None


def test_after_sync_backfills_unaligned_trades(session: Session, account: Account) -> None:
    note(session, BiasKind.PRE_LONDON, TUE, XAUUSD="bullish")
    old = trade(session, account, open_time=LONDON)  # never aligned
    done = trade(
        session,
        account,
        open_time=LONDON,
        bias_alignment="counter",
        bias_alignment_weekly="no_bias",
        bias_alignment_monthly="no_bias",
    )
    recompute_after_sync(session, account.id, [])
    assert values(session, old) == ("aligned", "no_bias", "no_bias")
    assert values(session, done)[0] == "counter"  # not pending, not synced: untouched


def test_after_sync_broken_config_logs(
    session: Session,
    account: Account,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> AlignmentSettings:
        raise ConfigError(Path("bias.yaml"), ["symbols: missing"])

    monkeypatch.setattr(service, "alignment_settings", broken)
    t = trade(session, account, open_time=LONDON)
    recompute_after_sync(session, account.id, [t])
    assert values(session, t)[0] is None
    assert "bias alignment not computed" in caplog.text
