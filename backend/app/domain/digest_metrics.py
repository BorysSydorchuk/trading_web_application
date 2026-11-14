"""Digest and dashboard metrics (PRD 6.7, 6.9, 6.10; docs/api.md "M6 - Dashboard and digests").

Pure: no DB, no I/O. Decimal only, no explicit rounding (default 28-digit Decimal context);
the API edge quantizes. Every result is a frozen dataclass (mappings are read-only), inputs
are never mutated or reordered.

Conventions (DECISIONS 2026-11-12):
- Periods are Brussels calendar dates: week = Monday..Sunday, month = calendar month; a trade
  belongs to the period of its Brussels close date.
- Outcome (Borys/PM 2026-11-14): a trade with R and |R| < ``breakeven_r_threshold`` is
  breakeven; otherwise net_pnl > 0 win, < 0 loss, 0 breakeven. Win rate = wins / all trades
  x 100. Profit factor stays money-based (net_pnl sign).
- R metrics only over trades with ``r_multiple``; ``r_n`` = trades used.
- Percent base = sum of the sizes of the accounts that have a trade; None when any of them has
  no positive size.
- Max drawdown = largest peak-to-trough fall of the running net P&L from 0 in
  (close_time, id) order.
- Norm = mean and population SD of the per-period values; < 3 periods -> no norm.
- Norm availability: >= 20 weekdays (Mon-Fri) from the Brussels date of the first trade of
  the scope to the period start (DECISIONS 2026-11-13).
- Journal breakdowns read ``DigestTrade.journal`` (keys from journal_fields.yaml); a missing
  key and None both mean "not filled".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType
from typing import Literal, get_args
from zoneinfo import ZoneInfo

from app.domain.sessions import DEFAULT_TZ, to_local

ZERO = Decimal(0)
HUNDRED = Decimal(100)
R_BUCKET = Decimal("0.5")
R_CLAMP = Decimal(3)
MIN_NORM_PERIODS = 3
NORM_WINDOW_WEEKDAYS = 60
SATURDAY = 5
NORM_MIN_TRADING_DAYS = 20
type PeriodKind = Literal["weekly", "monthly"]
PERIOD_KINDS: tuple[str, ...] = get_args(PeriodKind.__value__)

type GroupKey = str | int | bool | None
type JournalValue = str | int | bool | None
type Deviation = Literal["worse", "better"]
type BiasScope = Literal["daily", "weekly", "monthly"]

TRADE_BREAKDOWN_FIELDS: tuple[str, ...] = ("symbol", "session", "hour", "weekday", "bias_alignment")
BIAS_SCOPES: tuple[str, ...] = get_args(BiasScope.__value__)
# Trade attribute that holds the alignment of each bias scope.
_BIAS_ATTRS: Mapping[str, str] = MappingProxyType(
    {
        "daily": "bias_alignment",
        "weekly": "bias_alignment_weekly",
        "monthly": "bias_alignment_monthly",
    }
)

HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {
        "net_pnl",
        "net_pnl_pct",
        "total_r",
        "win_rate",
        "avg_win_r",
        "avg_loss_r",
        "expectancy_r",
        "profit_factor",
    }
)
LOWER_IS_BETTER: frozenset[str] = frozenset({"max_drawdown", "max_drawdown_pct", "violations"})
NORM_METRICS: frozenset[str] = HIGHER_IS_BETTER | LOWER_IS_BETTER | {"trades"}


# --- input -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class DigestTrade:
    """One closed trade as the digest sees it. ``close_time`` is aware UTC."""

    id: int
    account_id: int
    symbol: str
    close_time: datetime
    net_pnl: Decimal
    r_multiple: Decimal | None
    session: str | None = None
    hour: int | None = None
    weekday: int | None = None
    bias_alignment: str | None = None  # effective daily value (override ?? auto)
    bias_alignment_weekly: str | None = None
    bias_alignment_monthly: str | None = None
    journal: Mapping[str, JournalValue] = field(default_factory=lambda: MappingProxyType({}))
    violations: tuple[str, ...] = ()
    # |R| below this is breakeven (rules.yaml breakeven_r_threshold); 0 = P&L sign only.
    breakeven_r_threshold: Decimal = ZERO


# --- results ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class DigestMetrics:
    trades: int
    wins: int
    losses: int
    breakeven: int
    violations: int
    net_pnl: Decimal
    net_pnl_pct: Decimal | None
    total_r: Decimal
    r_n: int
    win_rate: Decimal | None
    avg_win_r: Decimal | None
    avg_loss_r: Decimal | None
    expectancy_r: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal
    max_drawdown_pct: Decimal | None
    best_trade: DigestTrade | None
    worst_trade: DigestTrade | None


@dataclass(frozen=True)
class BreakdownGroup:
    key: GroupKey
    trades: int
    net_pnl: Decimal
    total_r: Decimal
    win_rate: Decimal | None


@dataclass(frozen=True)
class Breakdown:
    field: str
    groups: tuple[BreakdownGroup, ...]
    filled: int
    total: int


@dataclass(frozen=True)
class RuleLine:
    rule_key: str
    violations: int
    trades: int
    pnl: Decimal


@dataclass(frozen=True)
class RuleSection:
    rules: tuple[RuleLine, ...]
    violated_trades: int
    violated_pnl: Decimal


@dataclass(frozen=True)
class SideStats:
    trades: int
    net_pnl: Decimal
    total_r: Decimal


@dataclass(frozen=True)
class BiasSection:
    accuracy: Decimal | None
    marked: int
    total: int
    aligned: SideStats
    counter: SideStats


@dataclass(frozen=True)
class NormResult:
    value: Decimal | None
    norm_mean: Decimal | None
    norm_sd: Decimal | None
    deviation: Deviation | None


@dataclass(frozen=True)
class EquityPoint:
    time: datetime
    cum_pnl: Decimal


@dataclass(frozen=True)
class EquityCurves:
    combined: tuple[EquityPoint, ...]
    by_account: Mapping[int, tuple[EquityPoint, ...]]


@dataclass(frozen=True)
class RBucket:
    lower: Decimal
    upper: Decimal
    count: int


@dataclass(frozen=True)
class HeatCell:
    weekday: int
    hour: int
    trades: int
    net_pnl: Decimal


# --- periods ---------------------------------------------------------------------------------


def _check_kind(kind: str) -> None:
    if kind not in PERIOD_KINDS:
        raise ValueError(f"unknown period kind: {kind!r}")


def brussels_date(dt: datetime) -> date:
    return to_local(dt).date()


def period_start(kind: PeriodKind, day: date) -> date:
    _check_kind(kind)
    if kind == "weekly":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def period_end(kind: PeriodKind, start: date) -> date:
    """Last day (inclusive) of the period that starts on ``start``."""
    _check_kind(kind)
    if kind == "weekly":
        return start + timedelta(days=6)
    first_next = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_next - timedelta(days=1)


def trades_in_period(
    trades: Iterable[DigestTrade], kind: PeriodKind, start: date
) -> list[DigestTrade]:
    end = period_end(kind, start)
    return [t for t in trades if start <= brussels_date(t.close_time) <= end]


def _chronological(trades: Iterable[DigestTrade]) -> list[DigestTrade]:
    return sorted(trades, key=lambda t: (t.close_time, t.id))


# --- metrics ---------------------------------------------------------------------------------


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / len(values) if values else None


type Outcome = Literal["win", "loss", "breakeven"]


def outcome(t: DigestTrade) -> Outcome:
    """Breakeven when |R| < the trade's threshold, else the sign of net P&L."""
    if t.r_multiple is not None and abs(t.r_multiple) < t.breakeven_r_threshold:
        return "breakeven"
    if t.net_pnl > 0:
        return "win"
    return "loss" if t.net_pnl < 0 else "breakeven"


def _count(trades: Iterable[DigestTrade], kind: Outcome) -> int:
    return sum(1 for t in trades if outcome(t) == kind)


def _win_rate(trades: Sequence[DigestTrade]) -> Decimal | None:
    if not trades:
        return None
    wins = _count(trades, "win")
    return Decimal(wins) * HUNDRED / len(trades)


def _total_r(trades: Iterable[DigestTrade]) -> Decimal:
    return sum((t.r_multiple for t in trades if t.r_multiple is not None), ZERO)


def _percent_base(trades: Sequence[DigestTrade], sizes: Mapping[int, Decimal]) -> Decimal | None:
    """Sum of sizes of the accounts with a trade; None when empty or any size is unusable."""
    if not trades:
        return None
    base = ZERO
    for account_id in {t.account_id for t in trades}:
        size = sizes.get(account_id)
        if size is None or size <= 0:
            return None
        base += size
    return base


def _pct(value: Decimal, base: Decimal | None) -> Decimal | None:
    return None if base is None else value * HUNDRED / base


def _max_drawdown(trades: Sequence[DigestTrade]) -> Decimal:
    running = peak = worst = ZERO
    for t in _chronological(trades):
        running += t.net_pnl
        peak = max(peak, running)
        worst = max(worst, peak - running)
    return worst


def _profit_factor(trades: Sequence[DigestTrade]) -> Decimal | None:
    gains = sum((t.net_pnl for t in trades if t.net_pnl > 0), ZERO)
    losses = sum((t.net_pnl for t in trades if t.net_pnl < 0), ZERO)
    if losses == 0:
        return None
    return gains / abs(losses)


def _best(trades: Sequence[DigestTrade]) -> DigestTrade | None:
    return min(trades, key=lambda t: (-t.net_pnl, t.close_time, t.id), default=None)


def _worst(trades: Sequence[DigestTrade]) -> DigestTrade | None:
    return min(trades, key=lambda t: (t.net_pnl, t.close_time, t.id), default=None)


def compute_metrics(
    trades: Iterable[DigestTrade], account_sizes: Mapping[int, Decimal]
) -> DigestMetrics:
    items = tuple(trades)
    with_r = [t for t in items if t.r_multiple is not None]
    win_rs = [t.r_multiple for t in with_r if t.r_multiple is not None and outcome(t) == "win"]
    loss_rs = [t.r_multiple for t in with_r if t.r_multiple is not None and outcome(t) == "loss"]
    total_r = _total_r(with_r)
    net_pnl = sum((t.net_pnl for t in items), ZERO)
    base = _percent_base(items, account_sizes)
    max_dd = _max_drawdown(items)
    return DigestMetrics(
        trades=len(items),
        wins=_count(items, "win"),
        losses=_count(items, "loss"),
        breakeven=_count(items, "breakeven"),
        violations=sum(1 for t in items if t.violations),
        net_pnl=net_pnl,
        net_pnl_pct=_pct(net_pnl, base),
        total_r=total_r,
        r_n=len(with_r),
        win_rate=_win_rate(items),
        avg_win_r=_mean(win_rs),
        avg_loss_r=_mean(loss_rs),
        expectancy_r=total_r / len(with_r) if with_r else None,
        profit_factor=_profit_factor(items),
        max_drawdown=max_dd,
        max_drawdown_pct=_pct(max_dd, base),
        best_trade=_best(items),
        worst_trade=_worst(items),
    )


# --- breakdowns ------------------------------------------------------------------------------


def _field_value(t: DigestTrade, name: str, journal: bool) -> GroupKey:
    if journal:
        return t.journal.get(name)
    value: GroupKey = getattr(t, name)
    return value


def _key_order(key: str | int | bool) -> tuple[int, int, str]:
    """Numbers (int, bool) numerically, then strings; one field has one type in practice."""
    if isinstance(key, int):  # bool is an int: False < True
        return (0, int(key), "")
    return (1, 0, key)


def _sorted_keys(keys: Sequence[GroupKey]) -> list[GroupKey]:
    present: list[str | int | bool] = [k for k in keys if k is not None]
    ordered = sorted(present, key=_key_order)
    tail: list[GroupKey] = [None] if None in keys else []
    return [*ordered, *tail]


def _group(key: GroupKey, members: Sequence[DigestTrade]) -> BreakdownGroup:
    return BreakdownGroup(
        key=key,
        trades=len(members),
        net_pnl=sum((t.net_pnl for t in members), ZERO),
        total_r=_total_r(members),
        win_rate=_win_rate(members),
    )


def breakdown(trades: Iterable[DigestTrade], field: str, *, journal: bool = False) -> Breakdown:
    """Group by a trade field, or with ``journal=True`` by any key of ``trade.journal``."""
    if not journal and field not in TRADE_BREAKDOWN_FIELDS:
        raise ValueError(f"unknown breakdown field: {field!r}")
    items = tuple(trades)
    by_key: dict[GroupKey, list[DigestTrade]] = {}
    for t in items:
        by_key.setdefault(_field_value(t, field, journal), []).append(t)
    groups = tuple(_group(k, by_key[k]) for k in _sorted_keys(list(by_key)))
    filled = sum(1 for t in items if _field_value(t, field, journal) is not None)
    return Breakdown(field=field, groups=groups, filled=filled, total=len(items))


def breakdowns(
    trades: Iterable[DigestTrade], journal_fields: Sequence[str] = ()
) -> Mapping[str, Breakdown]:
    """Trade fields first, then ``journal_fields`` in order (a trade-field key is skipped)."""
    items = tuple(trades)
    result = {f: breakdown(items, f) for f in TRADE_BREAKDOWN_FIELDS}
    for key in journal_fields:
        if key not in result:
            result[key] = breakdown(items, key, journal=True)
    return MappingProxyType(result)


# --- rules and bias --------------------------------------------------------------------------


def rule_section(trades: Iterable[DigestTrade]) -> RuleSection:
    items = tuple(trades)
    occurrences: Counter[str] = Counter(k for t in items for k in t.violations)
    lines = []
    for key in sorted(occurrences):
        having = [t for t in items if key in t.violations]
        lines.append(
            RuleLine(
                rule_key=key,
                violations=occurrences[key],
                trades=len(having),
                pnl=sum((t.net_pnl for t in having), ZERO),
            )
        )
    violated = [t for t in items if t.violations]
    return RuleSection(
        rules=tuple(lines),
        violated_trades=len(violated),
        violated_pnl=sum((t.net_pnl for t in violated), ZERO),
    )


def _side(trades: Sequence[DigestTrade], attr: str, alignment: str) -> SideStats:
    members = [t for t in trades if getattr(t, attr) == alignment]
    return SideStats(
        trades=len(members),
        net_pnl=sum((t.net_pnl for t in members), ZERO),
        total_r=_total_r(members),
    )


def bias_section(
    trades: Iterable[DigestTrade], was_correct: Iterable[bool | None], scope: str = "daily"
) -> BiasSection:
    """Accuracy of the scope's entries; aligned/counter by the scope's trade alignment."""
    attr = _BIAS_ATTRS.get(scope)
    if attr is None:
        raise ValueError(f"unknown bias scope: {scope!r}")
    items = tuple(trades)
    marks = tuple(was_correct)
    marked = [m for m in marks if m is not None]
    correct = sum(1 for m in marked if m)
    return BiasSection(
        accuracy=Decimal(correct) * HUNDRED / len(marked) if marked else None,
        marked=len(marked),
        total=len(marks),
        aligned=_side(items, attr, "aligned"),
        counter=_side(items, attr, "counter"),
    )


def bias_sections(
    trades: Iterable[DigestTrade], marks: Mapping[str, Iterable[bool | None]]
) -> Mapping[str, BiasSection]:
    """All three scopes; a scope missing from ``marks`` has no entries."""
    items = tuple(trades)
    return MappingProxyType(
        {scope: bias_section(items, marks.get(scope, ()), scope) for scope in BIAS_SCOPES}
    )


# --- norm and deviation ----------------------------------------------------------------------


def _check_metric(metric: str) -> None:
    if metric not in NORM_METRICS:
        raise ValueError(f"unknown metric: {metric!r}")


def _population_sd(values: Sequence[Decimal], mean: Decimal) -> Decimal:
    variance = sum(((v - mean) ** 2 for v in values), ZERO) / len(values)
    return variance.sqrt()


def _deviation(
    metric: str, value: Decimal, mean: Decimal, sd: Decimal, k: Decimal
) -> Deviation | None:
    if sd == 0:
        return None
    if value < mean - k * sd:
        side: Deviation = "worse"
    elif value > mean + k * sd:
        side = "better"
    else:
        return None
    if metric in HIGHER_IS_BETTER:
        return side
    if metric in LOWER_IS_BETTER:
        return "better" if side == "worse" else "worse"
    return None


def norm_deviation(
    metric: str, value: Decimal | None, history: Sequence[Decimal], k: Decimal = Decimal(1)
) -> NormResult:
    _check_metric(metric)
    values = tuple(history)
    if len(values) < MIN_NORM_PERIODS:
        return NormResult(value=value, norm_mean=None, norm_sd=None, deviation=None)
    mean = sum(values, ZERO) / len(values)
    sd = _population_sd(values, mean)
    deviation = None if value is None else _deviation(metric, value, mean, sd, k)
    return NormResult(value=value, norm_mean=mean, norm_sd=sd, deviation=deviation)


def _metric_value(metrics: DigestMetrics, metric: str) -> Decimal | None:
    raw: Decimal | int | None = getattr(metrics, metric)
    return Decimal(raw) if isinstance(raw, int) else raw


def metric_series(
    trades: Iterable[DigestTrade],
    kind: PeriodKind,
    account_sizes: Mapping[int, Decimal],
    metric: str,
) -> tuple[Decimal, ...]:
    """``metric`` per period of ``kind`` that has >= 1 trade, oldest first, None dropped."""
    _check_kind(kind)
    _check_metric(metric)
    by_period: dict[date, list[DigestTrade]] = {}
    for t in trades:
        by_period.setdefault(period_start(kind, brussels_date(t.close_time)), []).append(t)
    values = (
        _metric_value(compute_metrics(by_period[start], account_sizes), metric)
        for start in sorted(by_period)
    )
    return tuple(v for v in values if v is not None)


def norm_window_start(kind: PeriodKind, start: date) -> date:
    """Start of the norm window for the period of ``kind`` beginning on ``start``.

    Counts the 60 weekdays (Mon-Fri) immediately before ``start``, then aligns that day to
    the start of its own period (Monday / 1st), so the window holds no partial first period.
    """
    _check_kind(kind)
    day = start
    counted = 0
    while counted < NORM_WINDOW_WEEKDAYS:
        day -= timedelta(days=1)
        if day.weekday() < SATURDAY:
            counted += 1
    return period_start(kind, day)


def weekdays_between(first: date, start: date) -> int:
    """Weekdays (Mon-Fri) from ``first`` (inclusive) to ``start`` (exclusive); 0 if not before."""
    if first >= start:
        return 0
    full_weeks, rest = divmod((start - first).days, 7)
    tail = sum(1 for i in range(rest) if (first + timedelta(days=i)).weekday() < SATURDAY)
    return full_weeks * 5 + tail


def trading_days_of_history(trades: Iterable[DigestTrade], start: date) -> int:
    """Weekdays from the Brussels date of the first trade to ``start``; 0 without trades."""
    first = min((brussels_date(t.close_time) for t in trades), default=None)
    return 0 if first is None else weekdays_between(first, start)


def norm_available(trades: Iterable[DigestTrade], start: date) -> bool:
    return trading_days_of_history(trades, start) >= NORM_MIN_TRADING_DAYS


def norm_window_trades(
    trades: Iterable[DigestTrade], kind: PeriodKind, start: date
) -> list[DigestTrade]:
    window_start = norm_window_start(kind, start)
    return [t for t in trades if window_start <= brussels_date(t.close_time) < start]


# --- charts ----------------------------------------------------------------------------------


def _origin(start: date) -> datetime:
    local_midnight = datetime.combine(start, time(0), tzinfo=ZoneInfo(DEFAULT_TZ))
    return local_midnight.astimezone(UTC)


def _curve(origin: datetime, trades: Sequence[DigestTrade]) -> tuple[EquityPoint, ...]:
    points = [EquityPoint(time=origin, cum_pnl=ZERO)]
    running = ZERO
    for t in trades:
        running += t.net_pnl
        points.append(EquityPoint(time=t.close_time, cum_pnl=running))
    return tuple(points)


def equity_curves(trades: Iterable[DigestTrade], start: date) -> EquityCurves:
    ordered = _chronological(trades)
    origin = _origin(start)
    accounts = sorted({t.account_id for t in ordered})
    by_account = {a: _curve(origin, [t for t in ordered if t.account_id == a]) for a in accounts}
    return EquityCurves(combined=_curve(origin, ordered), by_account=MappingProxyType(by_account))


def _bucket_index(r: Decimal) -> int:
    clamped = min(max(r, -R_CLAMP), R_CLAMP)
    return int((clamped / R_BUCKET).to_integral_value(rounding=ROUND_FLOOR))


def r_distribution(trades: Iterable[DigestTrade]) -> tuple[RBucket, ...]:
    indices = Counter(_bucket_index(t.r_multiple) for t in trades if t.r_multiple is not None)
    if not indices:
        return ()
    return tuple(
        RBucket(lower=i * R_BUCKET, upper=(i + 1) * R_BUCKET, count=indices[i])
        for i in range(min(indices), max(indices) + 1)
    )


def hour_heatmap(trades: Iterable[DigestTrade]) -> tuple[HeatCell, ...]:
    cells: dict[tuple[int, int], list[Decimal]] = {}
    for t in trades:
        if t.weekday is None or t.hour is None:
            continue
        cells.setdefault((t.weekday, t.hour), []).append(t.net_pnl)
    return tuple(
        HeatCell(weekday=wd, hour=h, trades=len(pnls), net_pnl=sum(pnls, ZERO))
        for (wd, h), pnls in sorted(cells.items())
    )
