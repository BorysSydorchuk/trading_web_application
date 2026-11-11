"""FX step of the MT5 sync (docs/api.md "M5-09 Cross-currency loss value").

For every cross-currency spec (profit currency != account currency) of one sync cycle:

- read phase (`fetch_fx`, connected): find the conversion pair among the broker symbols
  (direct ``<P><A>`` -> ask, inverse ``<A><P>`` -> 1 / bid), read its quote, and run the MT5
  ``order_calc_profit`` check (BUY, 1 lot, the symbol's own ask p, close p - N * tick_size,
  N = `check_tick_count`). Read-only calls only.
- write phase (`write_fx`, no commit): upsert ``fx_rates`` per (account, from, to), store or
  clear ``symbol_specs.mt5_loss_per_tick``/``_at`` and return the loss per tick per lot the
  trade risk uses (`choose_loss_per_tick`; None without any rate row).

A missing pair or quote, or an `Mt5Error` from quote/calc_profit, is a WARNING and never fails
the cycle; the previous rate row is then left untouched. So is unusable data: a blank account
or profit currency, a non-positive/non-finite tick_size or contract_size (spec skipped for FX,
no risk fallback), an arithmetic error, or a positive check result for the losing BUY (sign
anomaly, check not used). A conversion pair found by prefix match is logged at INFO, several
qualifying candidates at WARNING (the first sorted is used).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.broker_time import Conversion, server_to_utc
from app.domain.fx import (
    ConversionPair,
    check_loss_per_tick,
    check_tick_count,
    conversion_rate,
    is_cross_currency,
    pick_conversion_pair,
)
from app.models import FxRate, SymbolSpec
from app.mt5.errors import Mt5Error
from app.mt5.source import Mt5Source
from app.mt5.types import RawQuote, RawSymbolSpec
from app.services.fx_values import cross_loss_per_tick

logger = logging.getLogger(__name__)

# fx_rates.rate and symbol_specs.mt5_loss_per_tick are NUMERIC(20,8): round explicitly
# (half-up, as Postgres would) so the value used in this cycle equals the stored one.
STORED_Q = Decimal("0.00000001")
CHECK_VOLUME = Decimal(1)


@dataclass(frozen=True)
class FetchedRate:
    from_currency: str  # upper-case
    to_currency: str  # upper-case
    pair: ConversionPair
    quote: RawQuote


@dataclass(frozen=True)
class FxFetched:
    account_currency: str  # upper-case
    rates: dict[str, FetchedRate]  # by from_currency (upper-case)
    checks: dict[str, Decimal | None]  # broker symbol -> check value (None = failed)


def stored(value: Decimal) -> Decimal:
    return value.quantize(STORED_Q, rounding=ROUND_HALF_UP)


def _fx_problem(spec: RawSymbolSpec) -> str | None:
    """Why ``spec`` cannot get an FX loss value, or None."""
    if not spec.currency_profit.strip():
        return "blank profit currency"
    for name in ("tick_size", "contract_size"):
        value: Decimal = getattr(spec, name)
        if not value.is_finite() or value <= 0:
            return f"{name} {value} is not a positive finite number"
    return None


def cross_specs(specs: Iterable[RawSymbolSpec], account_currency: str) -> list[RawSymbolSpec]:
    """Cross-currency specs usable for FX; unusable ones are skipped with a WARNING."""
    usable: list[RawSymbolSpec] = []
    for spec in specs:
        problem = _fx_problem(spec)
        if problem is not None:
            logger.warning("%s: %s; skipped for the FX rate and MT5 check", spec.name, problem)
        elif is_cross_currency(spec.currency_profit, account_currency):
            usable.append(spec)
    return usable


def _matching(source: Mt5Source, prefixes: list[str]) -> set[str]:
    try:
        return {s.name for s in source.symbols_matching(prefixes)}
    except Mt5Error as exc:
        logger.warning("Conversion pair lookup (%s) failed: %s", ", ".join(prefixes), exc.message)
        return set()


def _pairs(
    source: Mt5Source, currencies: list[str], account_currency: str, known: set[str]
) -> dict[str, ConversionPair]:
    """Pair per profit currency; one extra symbol lookup only when a direct pair is missing."""
    found = {c: pick_conversion_pair(c, account_currency, known) for c in currencies}
    # Look further when there is no direct exact pair (missing, inverse, or a prefix match
    # that may have competing suffixed candidates at the broker).
    lacking = [c for c, p in found.items() if p is None or p.inverted or p.candidates]
    if lacking:
        prefixes = [p for c in lacking for p in (c + account_currency, account_currency + c)]
        names = known | _matching(source, prefixes)
        found |= {c: pick_conversion_pair(c, account_currency, names) for c in lacking}
    pairs: dict[str, ConversionPair] = {}
    for currency, pair in found.items():
        if pair is None:
            logger.warning(
                "No %s->%s conversion pair (%s%s or %s%s) at the broker; no rate stored",
                currency, account_currency, currency, account_currency, account_currency, currency,
            )  # fmt: skip
        else:
            _log_prefix_match(currency, account_currency, pair)
            pairs[currency] = pair
    return pairs


def _log_prefix_match(currency: str, account_currency: str, pair: ConversionPair) -> None:
    if len(pair.candidates) > 1:
        logger.warning(
            "Several %s->%s conversion pair candidates at the broker (%s); using %s "
            "(first sorted)",
            currency, account_currency, ", ".join(pair.candidates), pair.pair,
        )  # fmt: skip
    elif pair.candidates:
        logger.info(
            "%s->%s conversion pair %s found by prefix match", currency, account_currency, pair.pair
        )


def _quote(source: Mt5Source, symbol: str, purpose: str) -> RawQuote | None:
    try:
        quote = source.quote(symbol)
    except Mt5Error as exc:
        logger.warning("Quote of %s for the %s failed: %s", symbol, purpose, exc.message)
        return None
    if quote is None:
        logger.warning("No quote for %s (%s); skipped", symbol, purpose)
    return quote


def _check(source: Mt5Source, spec: RawSymbolSpec) -> Decimal | None:
    """MT5 loss per tick per lot from order_calc_profit over a 1 % move; None on failure."""
    quote = _quote(source, spec.name, "MT5 loss value check")
    if quote is None:
        return None
    try:
        ticks = check_tick_count(quote.ask, spec.tick_size)
        close = quote.ask - ticks * spec.tick_size
        result = source.calc_profit("buy", spec.name, CHECK_VOLUME, quote.ask, close)
        if result > 0:
            logger.warning(
                "MT5 loss value check of %s: order_calc_profit gave %s (> 0) for a BUY closed "
                "lower (sign anomaly); ignored",
                spec.name, result,
            )  # fmt: skip
            return None
        value = stored(check_loss_per_tick(result, ticks))
    except (Mt5Error, ValueError, ArithmeticError) as exc:
        message = exc.message if isinstance(exc, Mt5Error) else f"{type(exc).__name__}: {exc}"
        logger.warning("MT5 loss value check (calc_profit) of %s failed: %s", spec.name, message)
        return None
    if not value.is_finite() or value <= 0:
        logger.warning("MT5 loss value check of %s gave %s; ignored", spec.name, value)
        return None
    return value


def fetch_fx(source: Mt5Source, specs: Iterable[RawSymbolSpec], account_currency: str) -> FxFetched:
    """Quotes of the conversion pairs and the MT5 checks (call while connected)."""
    target = account_currency.strip().upper()
    all_specs = list(specs)
    if not target:
        logger.warning("Blank account currency from MT5; FX rates and MT5 checks skipped")
        return FxFetched(account_currency=target, rates={}, checks={})
    cross = cross_specs(all_specs, target)
    rates: dict[str, FetchedRate] = {}
    if cross:
        currencies = sorted({s.currency_profit.strip().upper() for s in cross})
        known = {s.name for s in all_specs}
        for currency, pair in _pairs(source, currencies, target, known).items():
            quote = _quote(source, pair.pair, f"{currency}->{target} rate")
            if quote is not None:
                rates[currency] = FetchedRate(currency, target, pair, quote)
    checks = {s.name: _check(source, s) for s in cross}
    return FxFetched(account_currency=target, rates=rates, checks=checks)


def _upsert_rates(
    session: Session, account_id: int, fetched: FxFetched, conversion: Conversion, now: datetime
) -> dict[str, FxRate]:
    """Upsert the fetched rates; returns every rate row of the account by from_currency."""
    rows = {
        (r.from_currency, r.to_currency): r
        for r in session.scalars(select(FxRate).where(FxRate.account_id == account_id))
    }
    for item in fetched.rates.values():
        values = {
            "pair": item.pair.pair,
            "inverted": item.pair.inverted,
            "bid": item.quote.bid,
            "ask": item.quote.ask,
            "rate": stored(conversion_rate(item.pair, bid=item.quote.bid, ask=item.quote.ask)),
            "rate_at": server_to_utc(item.quote.time, conversion),
            "synced_at": now,
        }
        key = (item.from_currency, item.to_currency)
        row = rows.get(key)
        if row is None:
            row = FxRate(account_id=account_id, from_currency=key[0], to_currency=key[1])
            session.add(row)
            rows[key] = row
        for name, value in values.items():
            setattr(row, name, value)
    target = fetched.account_currency
    return {f: row for (f, t), row in rows.items() if t == target}


def _store_checks(
    session: Session, account_id: int, fetched: FxFetched, synced: Iterable[str], now: datetime
) -> None:
    """Check value + time on cross specs; cleared on a failed check and on other synced specs."""
    names = set(synced)
    session.flush()  # sessions do not autoflush: new spec rows must be visible to the select
    for row in session.scalars(select(SymbolSpec).where(SymbolSpec.account_id == account_id)):
        if row.symbol not in names:
            continue
        value = fetched.checks.get(row.symbol)
        row.mt5_loss_per_tick = value
        row.mt5_loss_per_tick_at = now if value is not None else None


def write_fx(
    session: Session,
    account_id: int,
    fetched: FxFetched,
    specs: Mapping[str, RawSymbolSpec],
    conversion: Conversion,
    now: datetime,
) -> dict[str, Decimal | None]:
    """Persist rates and checks (no commit); loss per tick per lot by cross broker symbol.

    Call after the spec rows are upserted. A rate row not refreshed this cycle (no quote) is
    still used: it is the latest known rate. Only the usable cross specs of `fetch_fx` (the
    keys of ``fetched.checks``) get a value; any other cross spec has no FX risk fallback.
    """
    rates = _upsert_rates(session, account_id, fetched, conversion, now)
    _store_checks(session, account_id, fetched, specs, now)
    usable = [specs[name] for name in fetched.checks if name in specs]
    return {
        spec.name: cross_loss_per_tick(
            account_id,
            spec.name,
            spec.tick_size,
            spec.contract_size,
            rates.get(spec.currency_profit.strip().upper()),
            fetched.checks.get(spec.name),
        )
        for spec in usable
    }
