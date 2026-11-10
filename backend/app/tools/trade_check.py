"""Compare the app's last N closed trades with MT5's raw deals (M1 5-trade check).

    (repo root, PowerShell or cmd)
    python -m uv run --project backend python -m app.tools.trade_check --account "FN P1" \\
        --last 5 --out docs/reports/M1_trade_check.md

App values come from the DB. MT5 values are recomputed here *independently* from the raw
deals of each position (`Mt5Source.deals_for_position`), deliberately without the domain
trade builder, so the table is a real cross-check. Times are compared in broker server time,
which is what the MT5 History tab shows. Read-only; passwords are never printed.

Source: ``--source real`` (default), ``--source fixture:<path>``, or env/.env ``MT5_SOURCE``.
If MT5 is unreachable, the app side is still printed with a clear note.
"""

# ruff: noqa: RUF001
# RUF001: the report text is Ukrainian on purpose (Cyrillic letters, math signs).

from __future__ import annotations

import argparse
import io
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import ENV_FILE, REPO_ROOT, mt5_password_for
from app.config_files import get_rules
from app.domain.broker_time import (
    BrokerTimeRule,
    Conversion,
    choose_conversion,
    detect_offset,
    server_epoch_to_wall,
    utc_to_server,
)
from app.domain.sessions import to_local
from app.models.account import Account, SymbolSpec
from app.models.trade import Trade
from app.mt5.errors import Mt5Error
from app.mt5.fixture import FixtureMt5Source
from app.mt5.real import RealMt5Source
from app.mt5.source import Mt5Source, connected
from app.mt5.types import RawDeal

MONEY_TOLERANCE = Decimal("0.01")
TIME_FMT = "%Y-%m-%d %H:%M:%S"
DASH = "—"
OK = "✓"
BAD = "✗"
TZ = "Europe/Brussels"
BUY, SELL = 0, 1
ENTRY_IN, ENTRY_OUT, ENTRY_INOUT, ENTRY_OUT_BY = 0, 1, 2, 3

type PasswordLookup = Callable[[int], SecretStr | None]


class TradeCheckError(Exception):
    """Usage problem (unknown account, bad source spec); message is user-readable."""


# --- MT5 side, computed straight from raw deals ----------------------------------------


@dataclass(frozen=True)
class Mt5Side:
    position_id: int
    symbol: str
    direction: str
    open_server: datetime
    close_server: datetime | None
    entry_price: Decimal | None
    exit_price: Decimal | None
    volume: Decimal
    profit: Decimal
    commission: Decimal  # commission + fee
    swap: Decimal
    net: Decimal
    note: str | None = None


def _vwap(parts: Iterable[tuple[Decimal, Decimal]]) -> Decimal | None:
    total_v = Decimal(0)
    total = Decimal(0)
    for volume, price in parts:
        total_v += volume
        total += volume * price
    return None if total_v == 0 else total / total_v


def mt5_side(position_id: int, deals: Sequence[RawDeal]) -> Mt5Side | None:
    """Plain sums over the position's buy/sell deals. None if MT5 has no deals for it."""
    trade = sorted((d for d in deals if d.type in (BUY, SELL)), key=lambda d: (d.time, d.ticket))
    if not trade:
        return None
    entries = [d for d in trade if d.entry == ENTRY_IN]
    exits = [d for d in trade if d.entry in (ENTRY_OUT, ENTRY_OUT_BY)]
    note = (
        "є угода розвороту (inout) — не підтримується"
        if any(d.entry == ENTRY_INOUT for d in trade)
        else None
    )
    first = entries[0] if entries else trade[0]
    vol_in = sum((d.volume for d in entries), Decimal(0))
    vol_out = sum((d.volume for d in exits), Decimal(0))
    closed = bool(exits) and vol_out == vol_in
    profit = sum((d.profit for d in trade), Decimal(0))
    commission = sum((d.commission + d.fee for d in trade), Decimal(0))
    swap = sum((d.swap for d in trade), Decimal(0))
    return Mt5Side(
        position_id=position_id,
        symbol=first.symbol,
        direction="buy" if first.type == BUY else "sell",
        open_server=server_epoch_to_wall(first.time),
        close_server=server_epoch_to_wall(exits[-1].time) if closed else None,
        entry_price=_vwap((d.volume, d.price) for d in entries),
        exit_price=_vwap((d.volume, d.price) for d in exits),
        volume=vol_in,
        profit=profit,
        commission=commission,
        swap=swap,
        net=profit + commission + swap,
        note=note,
    )


# --- formatting / comparison ------------------------------------------------------------


def _q(value: Decimal, digits: int | None) -> Decimal:
    if digits is None:
        return value.normalize()
    return value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def fmt_price(value: Decimal | None, digits: int | None) -> str:
    return DASH if value is None else f"{_q(value, digits):f}"


def fmt_money(value: Decimal | None) -> str:
    return DASH if value is None else f"{_q(value, 2):f}"


def fmt_ratio(value: Decimal | None) -> str:
    """Percent and R as stored (NUMERIC(10,4))."""
    return DASH if value is None else f"{_q(value, 4):f}"


def fmt_volume(value: Decimal | None) -> str:
    """Lots with at least 2 decimals, like MT5 (1.00, 0.50, 0.125)."""
    if value is None:
        return DASH
    exponent = value.normalize().as_tuple().exponent
    places = max(2, -exponent) if isinstance(exponent, int) else 2
    return f"{_q(value, places):f}"


def fmt_time(value: datetime | None) -> str:
    return DASH if value is None else value.strftime(TIME_FMT)


@dataclass
class Row:
    label: str
    app: str
    mt5: str = ""
    match: bool | None = None  # None = not compared

    @property
    def mark(self) -> str:
        return "" if self.match is None else (OK if self.match else BAD)


@dataclass
class TradeBlock:
    trade: Trade
    mt5: Mt5Side | None
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def mismatches(self) -> list[str]:
        return [r.label for r in self.rows if r.match is False]


def _eq_price(a: Decimal | None, b: Decimal | None, digits: int | None) -> bool:
    if a is None or b is None:
        return a is b
    # Unknown digits: compare at the DB's price scale (8 dp), not full precision.
    return _q(a, 8 if digits is None else digits) == _q(b, 8 if digits is None else digits)


def _eq_money(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= MONEY_TOLERANCE


def _eq_time(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.replace(microsecond=0) == b.replace(microsecond=0)


def _server(utc_dt: datetime | None, conversion: Conversion) -> datetime | None:
    return None if utc_dt is None else utc_to_server(utc_dt, conversion)


def _brussels(utc_dt: datetime | None) -> datetime | None:
    return None if utc_dt is None else to_local(utc_dt, TZ)


def build_block(
    trade: Trade, mt5: Mt5Side | None, digits: int | None, conversion: Conversion, have_mt5: bool
) -> TradeBlock:
    block = TradeBlock(trade, mt5)
    rows = block.rows

    def cmp(label: str, app: str, mt5_text: str | None, ok: bool | None) -> None:
        if mt5 is None:
            rows.append(Row(label, app, DASH if have_mt5 else "", None))
        else:
            rows.append(Row(label, app, mt5_text or DASH, ok))

    m = mt5
    cmp("Позиція (ticket)", str(trade.position_id), str(m.position_id) if m else None, True)
    # MT5 deals carry the broker name; trade.symbol is canonical (M5-08).
    broker = trade.broker_symbol
    cmp("Символ", broker, m.symbol if m else None, m is not None and m.symbol == broker)
    cmp(
        "Напрям",
        trade.direction,
        m.direction if m else None,
        m is not None and m.direction == trade.direction,
    )
    open_srv = _server(trade.open_time, conversion)
    close_srv = _server(trade.close_time, conversion)
    cmp(
        "Відкриття, час сервера",
        fmt_time(open_srv),
        fmt_time(m.open_server) if m else None,
        m is not None and _eq_time(open_srv, m.open_server),
    )
    cmp(
        "Закриття, час сервера",
        fmt_time(close_srv),
        fmt_time(m.close_server) if m else None,
        m is not None and _eq_time(close_srv, m.close_server),
    )
    rows.append(Row("Відкриття, Брюссель", fmt_time(_brussels(trade.open_time))))
    rows.append(Row("Закриття, Брюссель", fmt_time(_brussels(trade.close_time))))
    cmp(
        "Ціна входу (VWAP)",
        fmt_price(trade.entry_price, digits),
        fmt_price(m.entry_price, digits) if m else None,
        m is not None and _eq_price(trade.entry_price, m.entry_price, digits),
    )
    cmp(
        "Ціна виходу (VWAP)",
        fmt_price(trade.exit_price, digits),
        fmt_price(m.exit_price, digits) if m else None,
        m is not None and _eq_price(trade.exit_price, m.exit_price, digits),
    )
    cmp(
        "Обсяг, лоти",
        fmt_volume(trade.volume),
        fmt_volume(m.volume) if m else None,
        m is not None and trade.volume == m.volume,
    )
    for label, app_value, mt5_value in (
        ("Валовий P&L (Σ profit)", trade.gross_pnl, m.profit if m else None),
        ("Комісія (Σ commission + fee)", trade.commission, m.commission if m else None),
        ("Своп", trade.swap, m.swap if m else None),
        ("Чистий P&L", trade.net_pnl, m.net if m else None),
    ):
        cmp(
            label,
            fmt_money(app_value),
            fmt_money(mt5_value) if m else None,
            m is not None and _eq_money(app_value, mt5_value),
        )
    sl = trade.initial_sl
    source = f" ({trade.initial_sl_source})" if trade.initial_sl_source else ""
    rows.append(Row("Початковий SL", fmt_price(sl, digits) + (source if sl is not None else "")))
    rows.append(Row("Баланс на відкритті", fmt_money(trade.balance_at_open)))
    rows.append(Row("Ризик, $", fmt_money(trade.risk_amount)))
    rows.append(Row("Ризик, %", fmt_ratio(trade.risk_pct)))
    rows.append(Row("R", fmt_ratio(trade.r_multiple)))

    if m is not None and m.note:
        block.notes.append(m.note)
    if have_mt5 and m is None:
        block.notes.append("MT5 не повернув угод для цієї позиції.")
    block.notes.extend(_formulas(trade, digits))
    return block


def _formulas(t: Trade, digits: int | None) -> list[str]:
    """The app-only values written out with numbers, so Borys can recompute them by hand."""
    out: list[str] = []
    if t.initial_sl is None:
        return ["Початкового SL немає → ризик, ризик % і R не рахуються (статус needs_sl)."]
    e, x, sl = t.entry_price, t.exit_price, t.initial_sl
    if t.risk_amount is not None and x is not None and t.gross_pnl is not None and x != e:
        out.append(
            f"Ризик = |валовий P&L| × |вхід − SL| / |вихід − вхід| = {fmt_money(abs(t.gross_pnl))}"
            f" × |{fmt_price(e, digits)} − {fmt_price(sl, digits)}| / |{fmt_price(x, digits)} − "
            f"{fmt_price(e, digits)}| ≈ {fmt_money(t.risk_amount)} "
            "(якщо вихід ≈ вхід, застосунок рахує через tick value символу)."
        )
    if t.risk_pct is not None and t.risk_amount is not None and t.balance_at_open is not None:
        out.append(
            f"Ризик % = ризик / баланс на відкритті × 100 = {fmt_money(t.risk_amount)} / "
            f"{fmt_money(t.balance_at_open)} × 100 = {fmt_ratio(t.risk_pct)} %."
        )
    if t.r_multiple is not None and t.risk_amount is not None and t.net_pnl is not None:
        out.append(
            f"R = чистий P&L / ризик = {fmt_money(t.net_pnl)} / {fmt_money(t.risk_amount)} = "
            f"{fmt_ratio(t.r_multiple)}."
        )
    return out


# --- report ------------------------------------------------------------------------------

INSTRUCTION = """\
**Як звірити з MT5 (≈2 хв).** У терміналі відкрийте вкладку «Історія» (Ctrl+T → «Історія»),
правий клік → «Позиції» і потрібний період. Для кожної угоди нижче знайдіть рядок з тим самим
номером позиції (ticket) і порівняйте: час відкриття/закриття, ціну входу/виходу, обсяг,
комісію, своп і прибуток.

- **Час у MT5 — це час сервера брокера, не Брюссель і не UTC.** Тому в таблиці є рядки
  «час сервера» (звіряйте з MT5) і «Брюссель» (так показує журнал).
- Колонка MT5 порахована цим скриптом прямо з угод термінала (не з бази журналу);
  ✓/✗ — автоматичне порівняння: ціни до знаків символу, гроші до 0.01, час до секунди.
- При частковому закритті MT5 показує середню ціну виходу так само (зважену за обсягом).
- «Прибуток» у MT5 = валовий P&L; чистий = прибуток + комісія + своп.
- Ризик, ризик % і R є тільки в журналі: вони рахуються від початкового SL (формули з
  числами — під кожною таблицею, можна перерахувати вручну).
"""


@dataclass
class Report:
    markdown: str
    blocks: list[TradeBlock]
    mt5_error: str | None

    @property
    def all_match(self) -> bool:
        return (
            self.mt5_error is None
            and bool(self.blocks)
            and all(b.mt5 is not None and not b.mismatches for b in self.blocks)
        )


def find_account(session: Session, ref: str) -> Account:
    ref = ref.strip()
    account: Account | None = None
    if ref.isdigit():
        account = session.get(Account, int(ref))
    if account is None:
        account = session.scalars(
            select(Account).where(func.lower(Account.name) == ref.lower())
        ).first()
    if account is None:
        names = ", ".join(f"{a.id}: {a.name}" for a in session.scalars(select(Account)))
        raise TradeCheckError(f"account {ref!r} not found (known: {names or 'none'})")
    return account


def last_closed_trades(session: Session, account_id: int, n: int) -> list[Trade]:
    rows = session.scalars(
        select(Trade)
        .where(Trade.account_id == account_id, Trade.close_time.is_not(None))
        .order_by(Trade.close_time.desc(), Trade.position_id.desc())
        .limit(n)
    ).all()
    return sorted(rows, key=lambda t: (t.close_time or t.open_time, t.position_id))


@dataclass
class _Fetched:
    sides: dict[int, Mt5Side | None]
    conversion: Conversion
    digits: dict[str, int]
    note: str


def _fetch_mt5(
    source: Mt5Source,
    account: Account,
    trades: Sequence[Trade],
    password_for: PasswordLookup,
    rule: BrokerTimeRule,
    now: datetime,
) -> _Fetched:
    password = password_for(account.login)
    with connected(source, account.terminal_path or "", account.login, password, account.server):
        detected: int | None = None
        digits: dict[str, int] = {}
        for symbol in sorted({t.broker_symbol for t in trades}):
            spec = source.symbol_spec(symbol)
            if spec is not None:
                digits[symbol] = spec.digits
            if detected is None:
                tick = source.server_tick_epoch(symbol)
                detected = detect_offset(tick, now) if tick is not None else None
        choice = choose_conversion(detected, rule, now)
        conversion = choice.conversion if choice.conversion is not None else rule
        sides = {
            t.position_id: mt5_side(t.position_id, source.deals_for_position(t.position_id))
            for t in trades
        }
    return _Fetched(sides, conversion, digits, choice.message)


def build_report(
    session: Session,
    account_ref: str,
    last: int,
    source: Mt5Source | None,
    *,
    now: datetime | None = None,
    password_for: PasswordLookup = mt5_password_for,
    rule: BrokerTimeRule | None = None,
) -> Report:
    now = now or datetime.now(UTC)
    rule = rule or BrokerTimeRule(get_rules().broker_time)
    account = find_account(session, account_ref)
    trades = last_closed_trades(session, account.id, last)
    db_digits = {
        s.symbol: s.digits
        for s in session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account.id))
    }

    mt5_error: str | None = None
    fetched: _Fetched | None = None
    if source is not None and trades:
        try:
            fetched = _fetch_mt5(source, account, trades, password_for, rule, now)
        except Mt5Error as exc:
            mt5_error = f"[{exc.code}] {exc.message}"
    elif source is None:
        mt5_error = "MT5 не запитувався (--source none)"

    conversion: Conversion = fetched.conversion if fetched else rule
    digits = {**db_digits, **(fetched.digits if fetched else {})}
    blocks = [
        build_block(
            t,
            fetched.sides.get(t.position_id) if fetched else None,
            digits.get(t.broker_symbol),
            conversion,
            fetched is not None,
        )
        for t in trades
    ]

    lines = [
        f"# Звірка угод: {account.name} (логін {account.login}, {account.server})",
        "",
        f"Згенеровано {now.astimezone(UTC):%Y-%m-%d %H:%M} UTC. Останні {len(trades)} "
        f"закритих угод (запитано {last}).",
        "",
        INSTRUCTION,
    ]
    if fetched is not None:
        lines += [f"Час сервера: {fetched.note}.", ""]
    if mt5_error is not None:
        lines += [
            f"> **MT5 недоступний: {mt5_error}.** Нижче лише значення журналу; колонку MT5 "
            "заповніть вручну з вкладки «Історія».",
            "",
        ]
    if not trades:
        lines += ["Закритих угод для цього рахунку ще немає.", ""]
    for i, block in enumerate(blocks, start=1):
        t = block.trade
        lines += [f"## {i}. {t.symbol} {t.direction} — позиція {t.position_id}", ""]
        lines += ["| Поле | Журнал | MT5 | |", "|---|---|---|---|"]
        lines += [f"| {r.label} | {r.app} | {r.mt5} | {r.mark} |" for r in block.rows]
        lines.append("")
        lines += [f"- {n}" for n in block.notes]
        lines.append("")

    report = Report("", blocks, mt5_error)
    lines.append(summary_line(report))
    report.markdown = "\n".join(lines).rstrip() + "\n"
    return report


def summary_line(report: Report) -> str:
    total = len(report.blocks)
    if report.mt5_error is not None:
        return f"**Підсумок:** {total} угод з журналу; порівняння з MT5 не виконано."
    if total == 0:
        return "**Підсумок:** немає угод для порівняння."
    bad = [b for b in report.blocks if b.mt5 is None or b.mismatches]
    if not bad:
        return f"**Підсумок: {total}/{total} trades match** {OK}"
    details = "; ".join(
        f"позиція {b.trade.position_id}: "
        + (", ".join(b.mismatches) if b.mt5 is not None else "немає в MT5")
        for b in bad
    )
    return f"**Підсумок: {total - len(bad)}/{total} trades match** {BAD} — розбіжності: {details}"


# --- CLI ---------------------------------------------------------------------------------


def _env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value is None and ENV_FILE.is_file():
        values = {k.upper(): v for k, v in dotenv_values(ENV_FILE, encoding="utf-8").items()}
        value = values.get(key)
    return value


def make_source(spec: str | None) -> Mt5Source | None:
    """``real`` | ``fixture:<path>`` (relative to the repo root) | ``none``."""
    spec = (spec or _env_value("MT5_SOURCE") or "real").strip()
    if spec.lower() == "real":
        return RealMt5Source()
    if spec.lower() == "none":
        return None
    if spec.lower().startswith("fixture:"):
        path = Path(spec[len("fixture:") :].strip())
        path = path if path.is_absolute() else REPO_ROOT / path
        if not path.is_file():
            raise TradeCheckError(f"fixture not found: {path}")
        return FixtureMt5Source.from_file(path)
    raise TradeCheckError(f"--source must be real, none or fixture:<path>, got {spec!r}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare the last N closed trades with MT5.")
    parser.add_argument("--account", required=True, help="account id or name")
    parser.add_argument("--last", type=int, default=5)
    parser.add_argument("--out", type=Path, help="also write the Markdown to this file")
    parser.add_argument("--source", help="real | fixture:<path> | none (default: MT5_SOURCE)")
    args = parser.parse_args(argv)
    if args.last < 1:
        parser.error("--last must be at least 1")

    from app.db import get_session_factory  # lazy: tests build their own session

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # Ukrainian + ✓ on a cp1252 console
    try:
        source = make_source(args.source)
        with get_session_factory()() as session:
            report = build_report(session, args.account, args.last, source)
    except TradeCheckError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(report.markdown)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report.markdown, encoding="utf-8", newline="\n")
        print(f"Written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
