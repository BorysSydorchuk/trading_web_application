"""Prop-firm rules of one account and the firm day (docs/api.md "Firm rules from config:
KeyFunding"). Pure: no DB, no config access; the caller passes the parsed firms config.

Effective rules, per field: the account's own Settings value (> 0), else the firm config
value. Accounts without a firm entry keep the unchanged behaviour (Settings values, then the
rules.yaml `account_limits` fallback) and never get a firm daily floor.

Firm day: starts at `reset_at` (latest daily-reset wall time <= now in the reset zone; zone
`server` = a fixed offset of accounts.server_offset_hours, UTC when unknown). Start balance:
a fresh synced balance minus today's closed P&L and the cash today's open trades booked, else
size + closed P&L before the reset + cash booked by trades opened before it. The daily limit
is a share of the account SIZE; the floor is start balance minus that amount. Money is Decimal
throughout; rounding happens at the API edge only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import Final, Literal
from zoneinfo import ZoneInfo

from app.config_files.firms import SERVER_ZONE, FirmsConfig
from app.domain.home import closest_to_daily_stop, firm_limits

logger = logging.getLogger(__name__)

HUNDRED = Decimal(100)
MAX_OFFSET_HOURS = 23  # a UTC offset is strictly inside +-24 h
ZERO = Decimal(0)

FirmRulesSource = Literal["firm", "account", "fallback", "none"]


def _positive(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value.is_finite() and value > 0 else None


@dataclass(frozen=True)
class FirmRules:
    """Effective rules of one account. Percents are positive (a loss of 8 % is 8)."""

    firm: str | None  # the firms.yaml name when an entry matched
    source: FirmRulesSource
    daily_loss_pct: Decimal | None
    max_loss_pct: Decimal | None
    max_loss_type: str | None
    profit_target_pct: Decimal | None
    daily_basis: str | None
    daily_reset: str | None
    reset_timezone: str | None
    to_verify: tuple[str, ...]

    def limits(self) -> tuple[Decimal | None, Decimal | None]:
        """(max loss %, profit target %) signed like rules.yaml `account_limits` (loss < 0)."""
        return (
            -self.max_loss_pct if self.max_loss_pct is not None else None,
            self.profit_target_pct,
        )


def effective_rules(
    *,
    account_firm: str | None,
    phase: str,
    account_daily_loss_pct: Decimal | None,
    account_max_drawdown_pct: Decimal | None,
    account_profit_target_pct: Decimal | None,
    firms: FirmsConfig,
    fallback_max_loss_pct: Decimal | None,
    fallback_profit_target_pct: Decimal | None,
) -> FirmRules:
    """The effective firm rules of an account. ``fallback_*`` are the rules.yaml
    `account_limits` (max loss signed negative), used only without a firm entry."""
    daily = _positive(account_daily_loss_pct)
    drawdown = _positive(account_max_drawdown_pct)
    target = _positive(account_profit_target_pct)
    entry = firms.match(account_firm)
    if entry is None:
        return _without_entry(
            daily, drawdown, target, fallback_max_loss_pct, fallback_profit_target_pct
        )
    rule = entry.rule
    return FirmRules(
        firm=entry.name,
        source="firm",
        daily_loss_pct=daily if daily is not None else rule.daily_loss_pct,
        max_loss_pct=drawdown if drawdown is not None else rule.max_loss_pct,
        max_loss_type=rule.max_loss_type,
        profit_target_pct=target if target is not None else rule.profit_target_pct.for_phase(phase),
        daily_basis=rule.daily_basis,
        daily_reset=rule.daily_reset,
        reset_timezone=rule.reset_timezone,
        to_verify=tuple(rule.to_verify),
    )


def _without_entry(
    daily: Decimal | None,
    drawdown: Decimal | None,
    target: Decimal | None,
    fallback_max_loss: Decimal | None,
    fallback_target: Decimal | None,
) -> FirmRules:
    """Unchanged behaviour: Settings values first, else the rules.yaml fallback."""
    max_loss, profit = _legacy_limits(drawdown, target, fallback_max_loss, fallback_target)
    if drawdown is not None or target is not None:
        source: FirmRulesSource = "account"
    elif max_loss is not None or profit is not None:
        source = "fallback"
    else:
        source = "account" if daily is not None else "none"
    return FirmRules(
        firm=None,
        source=source,
        daily_loss_pct=daily,
        max_loss_pct=-max_loss if max_loss is not None else None,
        max_loss_type="static" if max_loss is not None else None,
        profit_target_pct=profit,
        daily_basis=None,
        daily_reset=None,
        reset_timezone=None,
        to_verify=(),
    )


def _legacy_limits(
    drawdown: Decimal | None,
    target: Decimal | None,
    fallback_max_loss: Decimal | None,
    fallback_target: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    limits = firm_limits(drawdown, target, fallback_max_loss, fallback_target)
    return limits.max_loss_pct, limits.profit_target_pct


# --- reset ------------------------------------------------------------------------------------


def _zone(reset_timezone: str, server_offset_hours: int | None) -> tzinfo:
    if reset_timezone == SERVER_ZONE:
        if server_offset_hours is not None and abs(server_offset_hours) > MAX_OFFSET_HOURS:
            logger.warning(
                "Invalid server offset %s h, using UTC for the firm day", server_offset_hours
            )
            return UTC
        return timezone(timedelta(hours=server_offset_hours or 0))
    return ZoneInfo(reset_timezone)


def reset_at(
    now: datetime, daily_reset: time, reset_timezone: str, server_offset_hours: int | None
) -> datetime:
    """Latest moment <= ``now`` at which ``daily_reset`` occurs in the reset zone (aware UTC)."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("expected a timezone-aware datetime")
    zone = _zone(reset_timezone, server_offset_hours)
    day = now.astimezone(zone).date()
    candidate = datetime.combine(day, daily_reset, tzinfo=zone).astimezone(UTC)
    if candidate > now:
        candidate = datetime.combine(day - timedelta(days=1), daily_reset, tzinfo=zone).astimezone(
            UTC
        )
    return candidate


@dataclass(frozen=True)
class FirmDayRule:
    """What the rules engine needs of a firm day: the limit and when the day resets."""

    daily_loss_pct: Decimal
    daily_reset: time
    reset_timezone: str
    server_offset_hours: int | None

    def reset_at(self, now: datetime) -> datetime:
        return reset_at(now, self.daily_reset, self.reset_timezone, self.server_offset_hours)


def day_rule(rules: FirmRules, server_offset_hours: int | None) -> FirmDayRule | None:
    """The firm day rule of an account with a firm entry, else None (no firm daily floor)."""
    if (
        rules.source != "firm"
        or rules.daily_loss_pct is None
        or rules.daily_reset is None
        or rules.reset_timezone is None
    ):
        return None
    return FirmDayRule(
        rules.daily_loss_pct,
        time.fromisoformat(rules.daily_reset),
        rules.reset_timezone,
        server_offset_hours,
    )


# --- firm day ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmDay:
    reset_at: datetime
    start_balance: Decimal
    floor: Decimal
    loss_pct: Decimal  # negative: -daily_loss_pct
    pnl_pct: Decimal | None  # None: floating P&L unknown
    room_pct: Decimal | None
    breached: bool  # also true when only the realized loss is already at the limit
    to_verify: tuple[str, ...]


def _sum_from(rows: Sequence[tuple[datetime, Decimal]], start: datetime, since: bool) -> Decimal:
    return sum((v for at, v in rows if (at >= start) == since), ZERO)


def firm_day(
    *,
    size: Decimal,
    daily_loss_pct: Decimal,
    reset_at: datetime,
    closed: Sequence[tuple[datetime, Decimal]],
    open_booked: Sequence[tuple[datetime, Decimal]],
    fresh_balance: Decimal | None,
    floating: Decimal | None,
    to_verify: tuple[str, ...] = (),
) -> FirmDay:
    """The firm day at ``reset_at``. ``closed``: (close_time, net P&L) of closed trades (all
    of them, or at least those closed since the reset when ``fresh_balance`` is given);
    ``open_booked``: (open_time, cash booked so far) of open trades; ``floating``: floating
    P&L of the open trades, None when unknown."""
    since = _sum_from(closed, reset_at, True) + _sum_from(open_booked, reset_at, True)
    if fresh_balance is not None:
        start = fresh_balance - since
    else:
        start = size + _sum_from(closed, reset_at, False) + _sum_from(open_booked, reset_at, False)
    floor = start - size * daily_loss_pct / HUNDRED
    pnl_pct = (since + floating) / size * HUNDRED if floating is not None else None
    room = daily_loss_pct + pnl_pct if pnl_pct is not None else None
    # Unknown floating P&L: the realized part alone can still prove the limit is reached.
    realized_room = daily_loss_pct + since / size * HUNDRED
    return FirmDay(
        reset_at=reset_at,
        start_balance=start,
        floor=floor,
        loss_pct=-daily_loss_pct,
        pnl_pct=pnl_pct,
        room_pct=room,
        breached=(room if room is not None else realized_room) <= 0,
        to_verify=to_verify,
    )


# --- static max loss --------------------------------------------------------------------------


def max_loss_floor(size: Decimal, max_loss_pct: Decimal) -> Decimal:
    """Static floor: size x (1 - max_loss_pct / 100); 10 000 at 8 % -> 9 200. Never moves."""
    return size * (1 - max_loss_pct / HUNDRED)


def at_max_loss(equity: Decimal, size: Decimal, max_loss_pct: Decimal) -> bool:
    """The account failed: equity at or below the static floor."""
    return equity <= max_loss_floor(size, max_loss_pct)


# --- firm alert and the «Ліміти» pick (PM 2026-11-26) ----------------------------------------

# An account this close (percent of the size) to a firm limit is shown first and in red.
FIRM_ALERT_ROOM_PCT: Final = Decimal(1)
_UNKNOWN_ROOM: Final = Decimal("-Infinity")  # breached with unknown room sorts first

FirmAlertKind = Literal["firm_day", "max_loss"]


@dataclass(frozen=True)
class FirmAlert:
    kind: FirmAlertKind
    room_pct: Decimal | None  # None: breached on the realized loss, floating unknown


def _alert_key(alert: FirmAlert) -> Decimal:
    return _UNKNOWN_ROOM if alert.room_pct is None else alert.room_pct


def firm_alert(day: FirmDay | None, max_loss_room: Decimal | None) -> FirmAlert | None:
    """The firm limit (daily floor or static max loss) within FIRM_ALERT_ROOM_PCT of the
    account, the closer one when both; None when neither is near."""
    alerts: list[FirmAlert] = []
    if day is not None:
        near = day.room_pct is not None and day.room_pct <= FIRM_ALERT_ROOM_PCT
        if near or day.breached:
            alerts.append(FirmAlert("firm_day", day.room_pct))
    if max_loss_room is not None and max_loss_room <= FIRM_ALERT_ROOM_PCT:
        alerts.append(FirmAlert("max_loss", max_loss_room))
    return min(alerts, key=_alert_key) if alerts else None


def pick_limits_item[T](
    items: Sequence[T],
    stop_room: Callable[[T], Decimal | None],
    alert: Callable[[T], FirmAlert | None],
) -> T | None:
    """An item near a firm limit first (smallest room; ties keep the input order), else the
    one closest to its personal daily stop."""
    alerted = [(a, item) for item in items if (a := alert(item)) is not None]
    if alerted:
        return min(alerted, key=lambda pair: _alert_key(pair[0]))[1]
    return closest_to_daily_stop(items, stop_room)
