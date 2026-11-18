# ruff: noqa: RUF001 - Ukrainian console messages
"""Backfill MAE / MFE for past closed trades from MT5 (M8-16). MT5 read-only.

    uv run python -m app.tools.backfill_excursions [--apply] [--account ID] [--retry-unavailable]

Dry run by default: reads MT5 price history, prints one line per trade and the totals,
writes nothing. ``--apply`` stores the values (same code as the worker's sync step).
Refuses while the worker runs (a sync in the last few minutes): stop the journal first
(«Торговий журнал — Стоп» or stop.bat), so two processes never use one terminal.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import mt5_password_for
from app.config_files import get_rules
from app.domain.broker_time import BrokerTimeRule, Conversion, choose_conversion, detect_offset
from app.domain.excursion import compute_excursion
from app.models import Account, SyncLog, Trade
from app.models.enums import AccountStatus, ExcursionStatus
from app.mt5.errors import Mt5Error
from app.mt5.source import Mt5Source, PriceHistory, connected
from app.services.excursions import Series, series_for, store_excursions, target_of
from app.services.sync import PasswordLookup

WORKER_RECENT = timedelta(minutes=3)


class BackfillError(Exception):
    """Shown to the owner (exit code 2)."""


@dataclass
class Totals:
    trades: int = 0
    computed: int = 0
    no_sl: int = 0
    unavailable: int = 0
    failed: int = 0
    lines: list[str] = field(default_factory=list)


def worker_running(session: Session, now: datetime) -> bool:
    last = session.scalar(select(func.max(SyncLog.started_at)))
    return last is not None and now - last < WORKER_RECENT


def pending_trades(session: Session, account_id: int, retry_unavailable: bool) -> list[Trade]:
    """Closed trades without a final value (``unavailable`` only with the flag)."""
    skip = [ExcursionStatus.FINAL.value]
    if not retry_unavailable:
        skip.append(ExcursionStatus.UNAVAILABLE.value)
    return list(
        session.scalars(
            select(Trade)
            .where(
                Trade.account_id == account_id,
                Trade.close_time.is_not(None),
                or_(Trade.excursion_status.is_(None), Trade.excursion_status.not_in(skip)),
            )
            .order_by(Trade.close_time, Trade.id)
        )
    )


def _conversion(
    source: Mt5Source, symbols: Sequence[str], rule: BrokerTimeRule, now: datetime
) -> Conversion:
    detected: int | None = None
    for symbol in symbols:
        tick = source.server_tick_epoch(symbol)
        detected = detect_offset(tick, now) if tick is not None else None
        if detected is not None:
            break
    choice = choose_conversion(detected, rule, now)
    return choice.conversion if choice.conversion is not None else rule


def _line(trade: Trade, series: Series) -> tuple[str, str]:
    target = series.target
    result = compute_excursion(
        target.direction,
        target.entry_price,
        target.initial_sl,
        target.open_time,
        series.end_time,
        series.samples,
        series.point,
    )
    head = f"#{trade.id} {trade.symbol} {trade.direction} {trade.close_time:%Y-%m-%d %H:%M}Z"
    if result is None:
        return "unavailable", f"{head}: немає історії цін у MT5"
    if result.mfe_r is None:
        return "no_sl", f"{head}: MFE {result.mfe_points} п., MAE {result.mae_points} п. (без SL)"
    return "computed", f"{head}: MFE {result.mfe_r} R, MAE {result.mae_r} R ({series.source.value})"


def backfill_account(
    session: Session,
    account: Account,
    source: Mt5Source,
    now: datetime,
    *,
    apply: bool,
    retry_unavailable: bool,
    totals: Totals,
    password_for: PasswordLookup = mt5_password_for,
) -> None:
    trades = pending_trades(session, account.id, retry_unavailable)
    totals.trades += len(trades)
    if not trades:
        return
    if not isinstance(source, PriceHistory):
        raise BackfillError("this MT5 source has no price history")
    password = password_for(account.login)
    found: list[Series] = []
    with connected(source, account.terminal_path or "", account.login, password, account.server):
        symbols = sorted({t.broker_symbol for t in trades})
        conversion = _conversion(source, symbols, BrokerTimeRule(get_rules().broker_time), now)
        specs = {s: source.symbol_spec(s) for s in symbols}
        for trade in trades:
            spec = specs.get(trade.broker_symbol)
            try:
                series = series_for(
                    source, target_of(trade), conversion, spec.point if spec else None, now
                )
            except (Mt5Error, ValueError) as exc:
                totals.failed += 1
                totals.lines.append(f"#{trade.id}: помилка MT5: {exc}")
                continue
            kind, line = _line(trade, series)
            setattr(totals, kind, getattr(totals, kind) + 1)
            totals.lines.append(line)
            found.append(series)
    if apply and found:
        store_excursions(session, found, now)
        session.commit()


def run(
    session: Session,
    source: Mt5Source,
    now: datetime,
    *,
    apply: bool,
    account_id: int | None = None,
    retry_unavailable: bool = False,
    password_for: PasswordLookup = mt5_password_for,
) -> Totals:
    if worker_running(session, now):
        raise BackfillError(
            "журнал працює (синхронізація була менше 3 хв тому): зупиніть його "
            "(«Торговий журнал — Стоп» або stop.bat) і запустіть знову"
        )
    query = select(Account).where(Account.status != AccountStatus.ARCHIVED.value)
    if account_id is not None:
        query = query.where(Account.id == account_id)
    totals = Totals()
    for account in session.scalars(query.order_by(Account.id)).all():
        backfill_account(
            session,
            account,
            source,
            now,
            apply=apply,
            retry_unavailable=retry_unavailable,
            totals=totals,
            password_for=password_for,
        )
    return totals


def summary(totals: Totals, apply: bool) -> str:
    mode = "записано" if apply else "пробний запуск, нічого не записано"
    return (
        f"Угод без MAE/MFE: {totals.trades}; пораховано з R: {totals.computed}; "
        f"без SL (лише пункти): {totals.no_sl}; без історії MT5: {totals.unavailable}; "
        f"помилки: {totals.failed} ({mode})"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill MAE/MFE from MT5 (read-only).")
    parser.add_argument("--apply", action="store_true", help="store the values")
    parser.add_argument("--account", type=int, help="only this account id")
    parser.add_argument("--retry-unavailable", action="store_true")
    args = parser.parse_args(argv)

    from app.db import get_session_factory  # lazy: tests build their own session
    from app.mt5.real import RealMt5Source

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        with get_session_factory()() as session:
            totals = run(
                session,
                RealMt5Source(),
                datetime.now(UTC),
                apply=args.apply,
                account_id=args.account,
                retry_unavailable=args.retry_unavailable,
            )
    except (BackfillError, Mt5Error) as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2
    for line in totals.lines:
        print(line)
    print(summary(totals, args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
