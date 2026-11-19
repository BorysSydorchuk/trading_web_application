# ruff: noqa: RUF001 - Ukrainian console messages
"""Backfill MAE / MFE for past closed trades from MT5 (M8-16). MT5 read-only.

    uv run python -m app.tools.backfill_excursions [--apply] [--account ID] [--retry-unavailable]

Dry run by default: reads MT5 price history, prints one line per trade and the totals,
writes nothing. ``--apply`` stores the values (same code as the worker's sync step).
MAE/MFE needs only the symbol's price history, not the account: when an account's own
terminal does not connect (e.g. an old challenge whose terminal folder was removed), the
history is read from another configured terminal of the same broker (same MT5 server
first, then any terminal of the same firm). Each terminal is opened only with the account
configured for it (as the worker does), never with another account's login. Every result
line names the terminal and server it came from; the lines also go to
``logs/backfill_excursions.log``.
Refuses while the worker runs (a sync in the last few minutes): stop the journal first
(«Торговий журнал — Стоп» or stop.bat), so two processes never use one terminal.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import mt5_password_for
from app.config_files import get_rules
from app.domain.broker_time import BrokerTimeRule, Conversion, choose_conversion, detect_offset
from app.models import Account, SyncLog, Trade
from app.models.enums import AccountStatus, ExcursionStatus
from app.mt5.errors import Mt5Error
from app.mt5.source import Mt5Source, PriceHistory
from app.services.excursions import (
    Fetched,
    Series,
    evaluate,
    series_for,
    store_excursions,
    target_of,
)
from app.services.sync import PasswordLookup

logger = logging.getLogger(__name__)
LOG_FILE = "backfill_excursions.log"

# Outside trading hours the worker syncs only every `interval_idle_seconds` (15 min): a sync
# within that interval plus this slack means the worker may still be running.
WORKER_SLACK = timedelta(minutes=2)


class BackfillError(Exception):
    """Shown to the owner (exit code 2)."""


@dataclass(frozen=True)
class Terminal:
    """A configured MT5 terminal and the account it is logged into."""

    account_name: str
    login: int
    server: str
    path: str

    @classmethod
    def of(cls, account: Account) -> Terminal:
        return cls(account.name, account.login, account.server, account.terminal_path or "")

    @property
    def label(self) -> str:
        return f"термінал {self.account_name}, {self.server}"


@dataclass
class Totals:
    trades: int = 0
    counts: Counter[str] = field(default_factory=Counter)  # computed / no_sl / unavailable / failed
    lines: list[str] = field(default_factory=list)

    @property
    def computed(self) -> int:
        return self.counts["computed"]

    @property
    def failed(self) -> int:
        return self.counts["failed"]


def worker_window() -> timedelta:
    sync = get_rules().sync
    longest = max(sync.interval_idle_seconds, sync.interval_trading_seconds)
    return timedelta(seconds=longest) + WORKER_SLACK


def worker_running(session: Session, now: datetime) -> bool:
    last = session.scalar(select(func.max(SyncLog.started_at)))
    return last is not None and now - last < worker_window()


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


def same_broker_terminals(session: Session, account: Account) -> list[Terminal]:
    """Other configured terminals of the account's broker: the same MT5 server first, then
    the same firm; active accounts first. Archived accounts are never used."""
    server, firm = account.server.strip().casefold(), account.firm.strip().casefold()
    others = session.scalars(
        select(Account)
        .where(
            Account.id != account.id,
            Account.status != AccountStatus.ARCHIVED.value,
            Account.terminal_path.is_not(None),
            Account.terminal_path != "",
        )
        .order_by(Account.id)
    ).all()

    def same_server(other: Account) -> bool:
        return other.server.strip().casefold() == server

    usable = [o for o in others if same_server(o) or o.firm.strip().casefold() == firm]
    usable.sort(key=lambda o: (not same_server(o), o.status != AccountStatus.ACTIVE.value))
    return [Terminal.of(o) for o in usable]


def _line(trade: Trade, series: Series, now: datetime, terminal: Terminal) -> tuple[str, str]:
    """Same classification as the worker's store (`evaluate`), so the dry run counts exactly
    what --apply writes."""
    outcome, result = evaluate(series, now)
    head = f"#{trade.id} {trade.symbol} {trade.direction} {trade.close_time:%Y-%m-%d %H:%M}Z"
    origin = f" [{terminal.label}]"
    if outcome == "unavailable" or result is None:
        reason = "неповна історія цін у MT5" if series.samples else "немає історії цін у MT5"
        kind = "unavailable" if outcome == "unavailable" else "retry"
        later = "" if kind == "unavailable" else " (спробуйте пізніше)"
        return kind, f"{head}: {reason}{later}{origin}"
    if result.mfe_r is None:
        points = f"MFE {result.mfe_points} п., MAE {result.mae_points} п. (без SL)"
        return "no_sl", f"{head}: {points}{origin}"
    values = f"MFE {result.mfe_r} R, MAE {result.mae_r} R ({series.source.value})"
    return "computed", f"{head}: {values}{origin}"


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
    found = _read_from_any_terminal(session, account, source, trades, now, totals, password_for)
    if apply and found:
        store_excursions(session, Fetched(series=found, failed=[]), now)
        session.commit()


def _read_from_any_terminal(
    session: Session,
    account: Account,
    source: Mt5Source,
    trades: Sequence[Trade],
    now: datetime,
    totals: Totals,
    password_for: PasswordLookup,
) -> list[Series]:
    """The account's own terminal, else the first same-broker terminal that connects."""
    own = Terminal.of(account)
    refused: list[str] = []
    for terminal in (own, *same_broker_terminals(session, account)):
        try:
            password = password_for(terminal.login)
            source.connect(terminal.path, terminal.login, password, terminal.server)
        except Mt5Error as exc:  # e.g. the terminal folder was removed: try the next one
            source.shutdown()
            refused.append(f"{terminal.label}: {exc}")
            continue
        try:
            if terminal != own:
                totals.lines.append(
                    f"Рахунок {account.name}: власний термінал недоступний, історія цін з "
                    f"{terminal.label} ({terminal.path})"
                )
            return _read_trades(source, terminal, trades, now, totals)
        except Mt5Error as exc:
            totals.counts["failed"] += len(trades)
            totals.lines.append(f"Рахунок {account.name}: помилка MT5 ({terminal.label}): {exc}")
            return []
        finally:
            source.shutdown()
    totals.counts["failed"] += len(trades)
    totals.lines.append(
        f"Рахунок {account.name}: немає доступного термінала цього брокера: " + "; ".join(refused)
    )
    return []


def _read_trades(
    source: Mt5Source,
    terminal: Terminal,
    trades: Sequence[Trade],
    now: datetime,
    totals: Totals,
) -> list[Series]:
    """Price series of ``trades`` from the connected ``terminal`` (read-only)."""
    if not isinstance(source, PriceHistory):  # checked by the caller; narrows the type
        raise BackfillError("this MT5 source has no price history")
    found: list[Series] = []
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
            totals.counts["failed"] += 1
            totals.lines.append(f"#{trade.id}: помилка MT5 ({terminal.label}): {exc}")
            continue
        kind, line = _line(trade, series, now, terminal)
        totals.counts[kind] += 1
        totals.lines.append(line)
        found.append(series)
    return found


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
            f"журнал працює (синхронізація менше {worker_window().seconds // 60} хв тому): "
            "зупиніть його "
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
        f"Угод без MAE/MFE: {totals.trades}; пораховано з R: {totals.counts['computed']}; "
        f"без SL (лише пункти): {totals.counts['no_sl']}; "
        f"без історії MT5: {totals.counts['unavailable']}; "
        f"спробувати пізніше: {totals.counts['retry']}; "
        f"помилки: {totals.counts['failed']} ({mode})"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill MAE/MFE from MT5 (read-only).")
    parser.add_argument("--apply", action="store_true", help="store the values")
    parser.add_argument("--account", type=int, help="only this account id")
    parser.add_argument("--retry-unavailable", action="store_true")
    args = parser.parse_args(argv)

    from app.db import get_session_factory  # lazy: tests build their own session
    from app.logging_setup import setup_logging
    from app.mt5.real import RealMt5Source

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    setup_logging(LOG_FILE)
    _console_warnings_only()
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
        logger.error("Backfill MAE/MFE refused: %s", exc)
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2
    mode = "apply" if args.apply else "dry run"
    for line in (*totals.lines, summary(totals, args.apply)):
        logger.info("Backfill MAE/MFE (%s): %s", mode, line)
        print(line)
    return 0


def _console_warnings_only() -> None:
    """The report is printed to stdout; the console log handler shows only warnings, the
    log file gets everything (the report lines too)."""
    for handler in logging.getLogger().handlers:
        if type(handler) is logging.StreamHandler:
            handler.setLevel(logging.WARNING)


if __name__ == "__main__":
    raise SystemExit(main())
