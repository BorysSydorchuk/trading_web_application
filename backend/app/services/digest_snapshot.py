"""Digest snapshot: domain results -> the plain JSON stored in ``digests.metrics``.

Pure (no DB). Money is a 2 dp string, percents / R / ratios are 4 dp strings, counts are ints,
ROUND_HALF_UP via ``app.schemas.dashboard`` (the API edge); Decimal everywhere before that.
Shape: docs/api.md "M6 - Dashboard and digests" and tests/test_digests_api.py.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.domain import digest_metrics as dm
from app.domain import equal_weight as ew
from app.domain.digest_breakdowns import JournalSpec, journal_breakdowns
from app.domain.period_base import period_base
from app.schemas.dashboard import money_str, pct_str

type Json = dict[str, Any]

# M8-04..08 merge B: the multi fields also broken down by combination, and the field pairs
# shown as a matrix (skipped when a field is not an analytics field in journal_fields.yaml).
COMBINATION_FIELDS: tuple[str, ...] = ("poi_types",)
MATRIX_FIELDS: tuple[tuple[str, str], ...] = (("h1_context", "h4_context"),)

COUNT_METRICS: frozenset[str] = frozenset({"trades", "wins", "losses", "breakeven", "violations"})
MONEY_METRICS: frozenset[str] = frozenset({"net_pnl", "max_drawdown"})
METRIC_ORDER: tuple[str, ...] = (
    "trades",
    "wins",
    "losses",
    "breakeven",
    "violations",
    "net_pnl",
    "net_pnl_pct",
    "total_r",
    "win_rate",
    "avg_win_r",
    "avg_loss_r",
    "expectancy_r",
    "profit_factor",
    "max_drawdown",
    "max_drawdown_pct",
)
_NO_NORM = dm.NormResult(value=None, norm_mean=None, norm_sd=None, deviation=None)


@dataclass(frozen=True)
class Scope:
    """One metric block: the period's trades, the norm window trades and availability.

    ``excluded`` / ``window_excluded``: the M8-01 excluded trades of the same accounts in the
    period / norm window; they only widen the percent base (app.domain.period_base)."""

    period: Sequence[dm.DigestTrade]
    window: Sequence[dm.DigestTrade]
    norm_available: bool
    excluded: Sequence[dm.DigestTrade] = ()
    window_excluded: Sequence[dm.DigestTrade] = ()


@dataclass(frozen=True)
class ExcludedTrade:
    """M8-01: a period trade left out of the strategy numbers, with the owner's reason."""

    trade: dm.DigestTrade
    reason: str


@dataclass(frozen=True)
class SnapshotInput:
    kind: dm.PeriodKind
    start: date
    currency: str | None
    sigma: Decimal
    sizes: Mapping[int, Decimal]
    account_names: Mapping[int, str]
    combined: Scope
    by_account: Mapping[int, Scope]  # only accounts with a trade in the period
    journal_fields: Sequence[JournalSpec]
    bias_marks: Mapping[str, Sequence[bool | None]]
    excluded: Sequence[ExcludedTrade] = ()


def _utc(value: datetime) -> str:
    """ISO 8601 UTC with ``Z``, the same format as ``app.schemas.common.UtcDatetime``."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _money(value: Decimal) -> str:
    return money_str(value)


def _ratio(value: Decimal | None) -> str | None:
    return None if value is None else pct_str(value)


def _value(name: str, raw: Decimal | int | None) -> str | int | None:
    if name in COUNT_METRICS:
        return None if raw is None else int(raw)
    if name in MONEY_METRICS:
        return None if raw is None else _money(Decimal(raw))
    return _ratio(None if raw is None else Decimal(raw))


def _norm_number(name: str, raw: Decimal | None) -> str | None:
    if raw is None:
        return None
    return _money(raw) if name in MONEY_METRICS else pct_str(raw)


def _norm(name: str, value: Decimal | int | None, scope: Scope, inp: SnapshotInput) -> Json:
    result = _NO_NORM
    if scope.norm_available and name in dm.NORM_METRICS:
        series = dm.metric_series(scope.window, inp.kind, inp.sizes, name, scope.window_excluded)
        current = None if value is None else Decimal(value)
        result = dm.norm_deviation(name, current, series, inp.sigma)
    return {
        "value": _value(name, value),
        "norm_mean": _norm_number(name, result.norm_mean),
        "norm_sd": _norm_number(name, result.norm_sd),
        "deviation": result.deviation,
    }


def _trade_ref(trade: dm.DigestTrade | None) -> Json | None:
    if trade is None:
        return None
    return {
        "trade_id": trade.id,
        "symbol": trade.symbol,
        "net_pnl": _money(trade.net_pnl),
        "r_multiple": _ratio(trade.r_multiple),
        "close_time": _utc(trade.close_time),
    }


def metric_block(scope: Scope, inp: SnapshotInput) -> Json:
    metrics = dm.compute_metrics(scope.period, inp.sizes, scope.excluded)
    values: Json = {}
    for name in METRIC_ORDER:
        raw: Decimal | int | None = getattr(metrics, name)
        values[name] = _norm(name, raw, scope, inp)
    values["total_r"]["n"] = metrics.r_n
    return {
        "norm_available": scope.norm_available,
        "metrics": values,
        "best_trade": _trade_ref(metrics.best_trade),
        "worst_trade": _trade_ref(metrics.worst_trade),
    }


def _breakdown_json(b: dm.Breakdown) -> Json:
    return {
        "kind": b.kind,
        "groups": [
            {
                # a matrix key (row, column) is stored as a JSON list
                "key": list(g.key) if isinstance(g.key, tuple) else g.key,
                "trades": g.trades,
                "net_pnl": _money(g.net_pnl),
                "total_r": pct_str(g.total_r),
                "win_rate": _ratio(g.win_rate),
            }
            for g in b.groups
        ],
        "coverage": {"filled": b.filled, "total": b.total},
    }


def _breakdowns(trades: Sequence[dm.DigestTrade], journal_fields: Sequence[JournalSpec]) -> Json:
    """Trade fields first, then the journal fields in file order (a journal key that is also
    a trade field, bias_alignment, is the trade field)."""
    result = {name: _breakdown_json(b) for name, b in dm.breakdowns(trades).items()}
    specs = [s for s in journal_fields if s.key not in result]
    journal = journal_breakdowns(trades, specs, COMBINATION_FIELDS, MATRIX_FIELDS)
    return result | {name: _breakdown_json(b) for name, b in journal.items()}


def _rules(trades: Sequence[dm.DigestTrade]) -> Json:
    section = dm.rule_section(trades)
    return {
        "rules": [
            {
                "rule_key": line.rule_key,
                "violations": line.violations,
                "trades": line.trades,
                "pnl": _money(line.pnl),
            }
            for line in section.rules
        ],
        "violated_trades": section.violated_trades,
        "violated_pnl": _money(section.violated_pnl),
    }


def _side(side: dm.SideStats) -> Json:
    return {
        "trades": side.trades,
        "net_pnl": _money(side.net_pnl),
        "total_r": pct_str(side.total_r),
    }


def _bias(trades: Sequence[dm.DigestTrade], marks: Mapping[str, Sequence[bool | None]]) -> Json:
    return {
        scope: {
            "accuracy": {"value": _ratio(s.accuracy), "marked": s.marked, "total": s.total},
            "aligned": _side(s.aligned),
            "counter": _side(s.counter),
        }
        for scope, s in dm.bias_sections(trades, marks).items()
    }


def _points(points: Sequence[dm.EquityPoint]) -> list[Json]:
    return [{"time": _utc(p.time), "cum_pnl": _money(p.cum_pnl)} for p in points]


def _charts(trades: Sequence[dm.DigestTrade], start: date) -> Json:
    curves = dm.equity_curves(trades, start)
    return {
        "equity": {
            "combined": _points(curves.combined),
            "by_account": [
                {"account_id": account_id, "points": _points(points)}
                for account_id, points in curves.by_account.items()
            ],
        },
        "r_distribution": [
            {"lower": pct_str(b.lower), "upper": pct_str(b.upper), "count": b.count}
            for b in dm.r_distribution(trades)
        ],
        "r_exactly_minus_one": dm.r_exactly_minus_one(trades),
        "hour_heatmap": [
            {"weekday": c.weekday, "hour": c.hour, "trades": c.trades, "net_pnl": _money(c.net_pnl)}
            for c in dm.hour_heatmap(trades)
        ],
    }


def _excluded(inp: SnapshotInput) -> Json:
    """«Виключені угоди»: strategy net P&L + excluded net P&L = the accounts' real P&L; its
    percent uses the same base as the strategy percent and «Головна» (PM 2026-11-20)."""
    strategy = sum((t.net_pnl for t in inp.combined.period), Decimal(0))
    excluded = sum((e.trade.net_pnl for e in inp.excluded), Decimal(0))
    traded = {t.account_id for t in inp.combined.period} | {
        e.trade.account_id for e in inp.excluded
    }
    base = period_base(inp.sizes, traded)
    account_net_pnl = strategy + excluded
    return {
        "trades": len(inp.excluded),
        "net_pnl": _money(excluded),
        "account_net_pnl": _money(account_net_pnl),
        "account_net_pnl_pct": None if base is None else pct_str(account_net_pnl * HUNDRED / base),
        "items": [
            {
                "trade_id": e.trade.id,
                "account_id": e.trade.account_id,
                "account_name": inp.account_names.get(e.trade.account_id),
                "symbol": e.trade.symbol,
                "close_time": _utc(e.trade.close_time),
                "net_pnl": _money(e.trade.net_pnl),
                "reason": e.reason,
            }
            for e in sorted(inp.excluded, key=lambda e: (e.trade.close_time, e.trade.id))
        ],
    }


def _account_pct(inp: SnapshotInput) -> Json:
    """All accounts (PM 2026-11-27): the accounts' real P&L (excluded trades included) in two
    percents: of the sum of the sizes (``period_base``, as the metric blocks) and the average
    of the per-account percents (``equal_weight``, as Home). One line always matches Home;
    with one account both are equal (the UI shows the line only for two or more)."""
    pnl: dict[int, Decimal | None] = {}
    for t in (*inp.combined.period, *(e.trade for e in inp.excluded)):
        pnl[t.account_id] = (pnl.get(t.account_id) or Decimal(0)) + t.net_pnl
    base = period_base(inp.sizes, pnl)
    total = sum((v for v in pnl.values() if v is not None), Decimal(0))
    equal = ew.average(pnl, dict(inp.sizes))
    return {
        "accounts": len(pnl),
        "size_weighted": None if base is None or not pnl else pct_str(total * HUNDRED / base),
        "equal_weighted": None if equal is None else pct_str(equal),
    }


ONE_R = Decimal(1)
HUNDRED = Decimal(100)


def _average(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / len(values) if values else None


def _excursions(trades: Sequence[dm.DigestTrade]) -> Json:
    """M8-16: how far winners and losers went in our favour (trades with a final MFE R)."""
    measured = [t for t in trades if t.mfe_r is not None]
    winners = [t.mfe_r for t in measured if dm.outcome(t) == "win" and t.mfe_r is not None]
    losers = [t.mfe_r for t in measured if dm.outcome(t) == "loss" and t.mfe_r is not None]
    reached = sum(1 for r in losers if r >= ONE_R)
    return {
        "n_winners": len(winners),
        "n_losers": len(losers),
        "winners_avg_mfe_r": _ratio(_average(winners)),
        "losers_avg_mfe_r": _ratio(_average(losers)),
        "losers_reached_1r": reached,
        "losers_reached_1r_share": _ratio(HUNDRED * reached / len(losers)) if losers else None,
    }


def build_snapshot(inp: SnapshotInput) -> Json:
    trades = inp.combined.period
    by_account = [
        {"account_id": account_id, "account_name": inp.account_names[account_id]}
        | metric_block(inp.by_account[account_id], inp)
        for account_id in sorted(inp.by_account)
    ]
    return {
        "currency": inp.currency,
        "combined": metric_block(inp.combined, inp),
        "by_account": by_account,
        "breakdowns": _breakdowns(trades, inp.journal_fields),
        "rules": _rules(trades),
        "bias": _bias(trades, inp.bias_marks),
        "charts": _charts(trades, inp.start),
        "trade_ids": sorted(t.id for t in trades),
        "excluded": _excluded(inp),
        "account_pct": _account_pct(inp),
        "excursions": _excursions(trades),
    }
