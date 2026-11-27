"""Backfill the initial SL of closed cTrader trades from the order history. Read-only.

    uv run python -m app.tools.backfill_ctrader_sl [--apply] [--account ID]

For every closed trade of an active cTrader account whose initial SL is unknown (never one
the owner entered), the orders of its position are read (2183, the guard's allowlist only)
and `app.ctrader.orders.initial_stop` picks the SL. Dry run by default: one line per trade
and the totals, nothing written. ``--apply`` stores it as source ``order`` with the same
recompute as an owner-entered SL (risk, risk %, R, planned RR, MAE/MFE R from the stored
extremes, violations). The lines also go to ``logs/backfill_ctrader_sl.log``.
Safe while the app runs: the token file is shared under its lock (`TokenManager`); before a
write the row is read again under a row lock (``SELECT ... FOR UPDATE``), so an SL entered or
synced meanwhile is never overwritten. Without the entry deal's order id (not stored) the
opening order is the earliest executed non-closing one (the sync names it exactly).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.trades import apply_initial_sl
from app.ctrader import protocol as p
from app.ctrader.connection import Connector, CtraderConnection, open_websocket
from app.ctrader.errors import CtraderError
from app.ctrader.history import check_account
from app.ctrader.orders import CtOrder, initial_stop, read_position_orders
from app.ctrader.reader import Credentials, authorize_app, endpoint_for
from app.models import Account, SymbolSpec, Trade
from app.models.enums import AccountPlatform, AccountStatus, InitialSlSource

logger = logging.getLogger(__name__)
LOG_FILE = "backfill_ctrader_sl.log"
PAD = timedelta(minutes=1)


@dataclass(frozen=True)
class Target:
    trade_id: int
    account_id: int
    ctid: int
    is_live: bool
    position_id: int
    symbol: str
    side: str
    entry_price: Decimal
    digits: int | None
    start: datetime
    end: datetime


OrdersByTrade = Mapping[int, tuple[CtOrder, ...] | CtraderError]
OrderReader = Callable[[Sequence[Target]], Awaitable[OrdersByTrade]]


@dataclass
class Totals:
    lines: list[str] = field(default_factory=list)
    found: int = 0
    stored: int = 0
    none: int = 0
    failed: int = 0


def targets(session: Session, account_id: int | None = None) -> list[Target]:
    query = (
        select(Trade, Account)
        .join(Account, Account.id == Trade.account_id)
        .where(
            Account.platform == AccountPlatform.CTRADER.value,
            Account.status == AccountStatus.ACTIVE.value,
            Account.ctid_trader_account_id.is_not(None),
            Trade.close_time.is_not(None),
            Trade.initial_sl.is_(None),
            Trade.initial_sl_source.is_(None),
        )
        .order_by(Trade.open_time, Trade.id)
    )
    if account_id is not None:
        query = query.where(Account.id == account_id)
    out: list[Target] = []
    for trade, account in session.execute(query):
        spec = session.scalar(
            select(SymbolSpec).where(
                SymbolSpec.account_id == account.id, SymbolSpec.symbol == trade.broker_symbol
            )
        )
        close_time, ctid = trade.close_time, account.ctid_trader_account_id
        if close_time is None or ctid is None:  # pragma: no cover - excluded by the query
            continue
        out.append(
            Target(
                trade_id=trade.id,
                account_id=account.id,
                ctid=ctid,
                is_live=bool(account.ctrader_is_live),
                position_id=trade.position_id,
                symbol=trade.symbol,
                side=trade.direction,
                entry_price=trade.entry_price,
                digits=spec.digits if spec is not None else None,
                start=trade.open_time - PAD,
                end=close_time + PAD,
            )
        )
    return out


def _kinds(orders: Sequence[CtOrder]) -> str:
    return ", ".join(
        f"{o.order_id}:{o.kind}{'/close' if o.closing else ''}"
        f"{' sl=' + str(o.stop_loss) if o.stop_loss is not None else ''}"
        f"{' rel=' + str(o.relative_stop_loss) if o.relative_stop_loss is not None else ''}"
        f"{' stop=' + str(o.stop_price) if o.stop_price is not None else ''}"
        for o in orders
    )


def _store(session: Session, target: Target, sl: Decimal) -> bool:
    # Fresh from the DB under a row lock: the identity map may hold the stale row of targets().
    trade = session.get(Trade, target.trade_id, populate_existing=True, with_for_update=True)
    if trade is None or trade.initial_sl_source is not None or trade.initial_sl is not None:
        return False  # got an SL meanwhile (owner or sync): never overwritten
    apply_initial_sl(session, trade, sl, InitialSlSource.ORDER)
    session.commit()
    return True


def run(session: Session, read: OrdersByTrade, todo: Sequence[Target], *, apply: bool) -> Totals:
    totals = Totals()
    for target in todo:
        head = (
            f"Угода {target.trade_id} ({target.symbol} {target.side}, позиція "
            f"{target.position_id}, вхід {target.entry_price})"
        )
        result = read.get(target.trade_id)
        if result is None or isinstance(result, CtraderError):
            totals.failed += 1
            reason = result.code.value if isinstance(result, CtraderError) else "не прочитано"
            totals.lines.append(f"{head}: помилка читання ордерів: {reason}")
            continue
        stop = initial_stop(
            result, side=target.side, entry_price=target.entry_price, digits=target.digits
        )
        if stop is None:
            totals.none += 1
            totals.lines.append(f"{head}: SL в історії ордерів немає [{_kinds(result)}]")
            continue
        totals.found += 1
        line = f"{head}: SL {stop.sl} ({stop.kind}, ордер {stop.order_id}) [{_kinds(result)}]"
        if apply:
            stored = _store(session, target, stop.sl)
            totals.stored += int(stored)
            line += " — записано" if stored else " — пропущено: SL вже є"
        totals.lines.append(line)
    return totals


def summary(totals: Totals, apply: bool, count: int) -> str:
    mode = "apply" if apply else "dry run, нічого не записано"
    return (
        f"Угод без SL: {count}; SL знайдено: {totals.found}; записано: {totals.stored}; "
        f"без SL в ордерах: {totals.none}; помилки: {totals.failed} ({mode})"
    )


# --- network ---------------------------------------------------------------------------


async def _authorize_account(connection: CtraderConnection, creds: Credentials, ctid: int) -> None:
    auth = await connection.request(
        p.ACCOUNT_AUTH_REQ,
        {"ctidTraderAccountId": ctid, "accessToken": creds.access_token.get_secret_value()},
        p.ACCOUNT_AUTH_RES,
    )
    check_account(auth, ctid)


async def read_orders(
    creds: Credentials, todo: Sequence[Target], connector: Connector = open_websocket
) -> dict[int, tuple[CtOrder, ...] | CtraderError]:
    """One connection per environment; account auth once per account. Errors per trade."""
    out: dict[int, tuple[CtOrder, ...] | CtraderError] = {}
    for is_live in sorted({t.is_live for t in todo}):
        group = [t for t in todo if t.is_live is is_live]
        connection = CtraderConnection(endpoint_for(is_live), connector, secrets=creds.secrets())
        try:
            await connection.start()
            await authorize_app(connection, creds)
            authorized: set[int] = set()
            refused: dict[int, CtraderError] = {}
            for target in group:
                if target.ctid in refused:
                    out[target.trade_id] = refused[target.ctid]
                    continue
                if target.ctid not in authorized:
                    try:
                        await _authorize_account(connection, creds, target.ctid)
                    except CtraderError as exc:
                        refused[target.ctid] = out[target.trade_id] = exc
                        continue
                    authorized.add(target.ctid)
                try:
                    out[target.trade_id] = await read_position_orders(
                        connection, target.ctid, target.position_id, target.start, target.end
                    )
                except CtraderError as exc:
                    out[target.trade_id] = exc
        except CtraderError as exc:
            for target in group:
                out.setdefault(target.trade_id, exc)
        finally:
            await connection.close()
    return out


def _credentials() -> Credentials:
    from app.config import get_settings
    from app.ctrader.token_manager import TokenManager
    from app.worker.ctrader_job import CtraderJobConfig

    config = CtraderJobConfig.from_settings(get_settings())
    if not config.configured:
        raise SystemExit("Помилка: cTrader не налаштовано")
    manager = TokenManager(config.store, config.client_id, config.client_secret)
    return Credentials(config.client_id, config.client_secret, manager.fresh_access_token())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill cTrader initial SL (read-only).")
    parser.add_argument("--apply", action="store_true", help="store the SL found")
    parser.add_argument("--account", type=int, help="only this account id")
    args = parser.parse_args(argv)

    from app.db import get_session_factory
    from app.logging_setup import setup_logging

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    setup_logging(LOG_FILE)
    for handler in logging.getLogger().handlers:
        if type(handler) is logging.StreamHandler:
            handler.setLevel(logging.WARNING)
    with get_session_factory()() as session:
        todo = targets(session, args.account)
        try:
            read = asyncio.run(read_orders(_credentials(), todo)) if todo else {}
        except CtraderError as exc:
            logger.error("Backfill cTrader SL refused: %s", exc.code.value)
            print(f"Помилка: {exc.message}", file=sys.stderr)
            return 2
        totals = run(session, read, todo, apply=args.apply)
    mode = "apply" if args.apply else "dry run"
    for line in (*totals.lines, summary(totals, args.apply, len(todo))):
        logger.info("Backfill cTrader SL (%s): %s", mode, line)
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
