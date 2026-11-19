"""Deterministic SYNTHETIC one-year history; caller owns a newly created empty DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, BiasEntry, BiasNote, ChartLink, RuleViolation, SymbolSpec, Trade
from app.services.digests import generate

NOW = datetime(2026, 11, 13, 17, tzinfo=UTC)
SYMBOLS = ("EURUSD", "GBPUSD", "XAUUSD", "GER40")
D = Decimal


def seed(db: Session) -> dict[str, Any]:
    if db.scalar(select(func.count()).select_from(Account)):
        raise ValueError("refused: synthetic dataset requires an empty new database")
    days: list[date] = []
    day = NOW.date()
    while len(days) < 260:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    accounts = [
        Account(
            name=f"SYNTHETIC {n + 1}",
            firm="Synthetic",
            program="Benchmark",
            phase="phase_1",
            login=99000001 + n,
            server="Synthetic-Offline",
            starting_balance=D("10000"),
            reference_balance=D("10000"),
            balance=D("10000"),
            equity=D("10000"),
            currency="USD",
            status="active",
            balance_synced_at=NOW,
        )
        for n in range(2)
    ]
    db.add_all(accounts)
    db.flush()
    for account in accounts:
        for symbol in SYMBOLS:
            fx = symbol in {"EURUSD", "GBPUSD"}
            db.add(
                SymbolSpec(
                    account_id=account.id,
                    symbol=symbol,
                    canonical_symbol=symbol,
                    contract_size=D("100000") if fx else D("100") if symbol == "XAUUSD" else D("1"),
                    tick_size=D("0.00001") if fx else D("0.01"),
                    point=D("0.00001") if fx else D("0.01"),
                    tick_value=D("1"),
                    tick_value_loss=D("1"),
                    volume_min=D("0.01"),
                    volume_step=D("0.01"),
                    volume_max=D("100"),
                    digits=5 if fx else 2,
                    currency_profit="USD",
                    currency_margin="USD",
                    synced_at=NOW,
                )
            )
    weeks = sorted({day - timedelta(days=day.weekday()) for day in days})
    months = sorted({day.replace(day=1) for day in days})
    periods = [(kind, day) for day in days for kind in ("pre_london", "pre_ny")]
    periods += [("weekly", day) for day in weeks] + [("monthly", day) for day in months]
    for index, (kind, day) in enumerate(periods):
        note = BiasNote(
            kind=kind, period_date=day, raw_text="SYNTHETIC: очікування, не ринкові дані."
        )
        note.entries = [
            BiasEntry(
                symbol=s,
                direction="bullish" if index % 2 else "bearish",
                confidence=2,
                key_levels="SYNTHETIC POI",
                narrative="Синтетичний план",
                was_correct=bool(index % 2),
                was_correct_source="manual",
            )
            for s in SYMBOLS
        ]
        db.add(note)
    outcomes = (("150", "1.5"), ("-100", "-1"), ("50", "0.5"), ("-100", "-1"), ("200", "2"))
    number = 0
    for day in days:
        for account in accounts:
            for hour in (9, 14):
                symbol = SYMBOLS[number % 4]
                instant = datetime(
                    day.year, day.month, day.day, hour, tzinfo=ZoneInfo("Europe/Brussels")
                ).astimezone(UTC)
                pnl, r = outcomes[number % len(outcomes)]
                trade = Trade(
                    account_id=account.id,
                    position_id=number + 1,
                    symbol=symbol,
                    broker_symbol=symbol,
                    direction="buy" if number % 2 else "sell",
                    open_time=instant,
                    close_time=instant + timedelta(minutes=30),
                    duration_seconds=1800,
                    entry_price=D("1.10000")
                    if symbol.endswith("USD") and symbol != "XAUUSD"
                    else D("2500"),
                    exit_price=D("1.10100")
                    if symbol.endswith("USD") and symbol != "XAUUSD"
                    else D("2501"),
                    initial_sl=D("1.09900") if symbol in {"EURUSD", "GBPUSD"} else D("2499"),
                    initial_sl_source="order",
                    volume=D("1"),
                    gross_pnl=D(pnl),
                    net_pnl=D(pnl),
                    balance_at_open=D("10000"),
                    risk_amount=D("100"),
                    risk_pct=D("1"),
                    pnl_pct=D(pnl) / D("100"),
                    r_multiple=None if number % 31 == 0 else D(r),
                    planned_rr=D("2"),
                    session="london" if hour == 9 else "ny",
                    weekday=day.weekday(),
                    hour=hour,
                    h1_context="flow",
                    h4_context="flow",
                    poi_types=["fvg_h4"],
                    fvg_types_h4=["fractal_updating"],
                    entry_model="ifvg_m5",
                    exit_reason="tp",
                    bias_alignment="counter" if number % 4 == 0 else "aligned",
                    bias_alignment_weekly="aligned",
                    bias_alignment_monthly="aligned",
                    followed_plan=bool(number % 5),
                    emotion_before="calm",
                    emotion_after="calm",
                    quality_rating=3,
                    raw_text="SYNTHETIC. " + "Опис сетапу, рівнів та результату. " * 8,
                    lesson="Синтетичний опис для benchmark",
                    extra={"benchmark": True},
                    status="needs_description" if number % 20 == 0 else "complete",
                    described_at=None if number % 20 == 0 else instant + timedelta(hours=1),
                )
                trade.chart_links = [
                    ChartLink(kind="before", url="https://www.tradingview.com/x/SyntheticA/")
                ]
                if number % 10 == 0:
                    trade.rule_violations = [
                        RuleViolation(rule_key="max_risk_pct", source="user", details="SYNTHETIC")
                    ]
                db.add(trade)
                number += 1
    for account in accounts:
        db.add(
            Trade(
                account_id=account.id,
                position_id=999000,
                symbol="EURUSD",
                broker_symbol="EURUSD",
                direction="buy",
                open_time=NOW - timedelta(hours=2),
                close_time=None,
                status="open",
                entry_price=D("1.1"),
                volume=D("1"),
                initial_sl=D("1.099"),
                initial_sl_source="order",
                risk_amount=D("100"),
                risk_pct=D("1"),
            )
        )
    db.commit()
    # Real existing digest generation, synthetic data only; no financial code changed.
    for kind, periods_for_kind in (("weekly", weeks), ("monthly", months)):
        for period in periods_for_kind:
            generate(db, kind, period, NOW)  # type: ignore[arg-type]
    return {
        "label": "SYNTHETIC/1",
        "accounts": 2,
        "symbols": list(SYMBOLS),
        "weekdays": 260,
        "closed_trades": number,
        "open_positions": 2,
        "bias_notes": len(periods),
        "bias_entries": len(periods) * 4,
        "weekly_digests": len(weeks),
        "monthly_digests": len(months),
        "from": str(days[0]),
        "through": str(days[-1]),
        "clock_utc": NOW.isoformat(),
        "journal": "95% complete; 5% inbox; Unicode texts/links; every 31st lacks R; "
        "every 10th has a violation",
        "prices": "synthetic literals, not broker specifications or calculator "
        "correctness evidence",
    }
