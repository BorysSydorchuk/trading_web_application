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
from app.schemas.dashboard import money_str, pct_str

type Json = dict[str, Any]

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
    """One metric block: the period's trades, the norm window trades and availability."""

    period: Sequence[dm.DigestTrade]
    window: Sequence[dm.DigestTrade]
    norm_available: bool


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
    journal_fields: Sequence[str]
    bias_marks: Mapping[str, Sequence[bool | None]]


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
        series = dm.metric_series(scope.window, inp.kind, inp.sizes, name)
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
    metrics = dm.compute_metrics(scope.period, inp.sizes)
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


def _breakdowns(trades: Sequence[dm.DigestTrade], journal_fields: Sequence[str]) -> Json:
    return {
        name: {
            "groups": [
                {
                    "key": g.key,
                    "trades": g.trades,
                    "net_pnl": _money(g.net_pnl),
                    "total_r": pct_str(g.total_r),
                    "win_rate": _ratio(g.win_rate),
                }
                for g in b.groups
            ],
            "coverage": {"filled": b.filled, "total": b.total},
        }
        for name, b in dm.breakdowns(trades, journal_fields).items()
    }


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
        "hour_heatmap": [
            {"weekday": c.weekday, "hour": c.hour, "trades": c.trades, "net_pnl": _money(c.net_pnl)}
            for c in dm.hour_heatmap(trades)
        ],
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
    }
