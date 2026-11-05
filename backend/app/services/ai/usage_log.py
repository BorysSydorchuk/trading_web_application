"""`logs/ai_usage.jsonl`: one JSON line per AI attempt, and the month-to-date summary.

Plain append (never the rotating log handler, never rotated): the monthly cost in
Settings is read from this file. Lines hold counts and costs only, never the input text,
the extracted values or the API key (docs/api.md "AI usage").
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.config import Settings
from app.config_files import ConfigError, ModelPrice, get_ai_pricing
from app.domain.sessions import DEFAULT_TZ
from app.services.ai.client import AiErrorKind, TokenUsage

logger = logging.getLogger(__name__)

USAGE_LOG_FILE = "ai_usage.jsonl"
COST_QUANTUM = Decimal("0.0001")
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)

_append_lock = threading.Lock()


def usage_log_path(settings: Settings) -> Path:
    return settings.log_dir_path / USAGE_LOG_FILE


def utc_ts(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- cost ---


def compute_cost(price: ModelPrice, usage: TokenUsage) -> Decimal:
    """USD for one call, 4 decimals (prices are per million tokens)."""
    total = (
        price.input * usage.input_tokens
        + price.output * usage.output_tokens
        + price.cache_write * usage.cache_creation_input_tokens
        + price.cache_read * usage.cache_read_input_tokens
    ) / TOKENS_PER_PRICE_UNIT
    return total.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)


def find_price(models: dict[str, ModelPrice], model: str) -> ModelPrice | None:
    """Exact model id, else a dated snapshot of a listed id (`<id>-<suffix>`)."""
    if model in models:
        return models[model]
    matches = [key for key in models if model.startswith(key + "-")]
    return models[max(matches, key=len)] if matches else None


def cost_for(model: str | None, usage: TokenUsage) -> Decimal | None:
    """Cost of one attempt, or None (unknown model / broken pricing file, logged).
    An attempt without billed tokens costs 0 whatever the model."""
    if usage.is_zero:
        return Decimal("0").quantize(COST_QUANTUM)
    if model is None:
        return None
    try:
        models = get_ai_pricing().models
    except ConfigError as exc:
        logger.error("AI cost not computed, config/ai_pricing.yaml is invalid: %s", exc)
        return None
    price = find_price(models, model)
    if price is None:
        logger.warning("AI cost not computed: model %r is not in config/ai_pricing.yaml", model)
        return None
    return compute_cost(price, usage)


# --- append ---


@dataclass(frozen=True)
class UsageRecord:
    ts: str
    purpose: str
    trade_id: int | None
    requested_model: str
    model: str | None
    fallback_used: bool
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: str | None
    ok: bool
    error_kind: AiErrorKind | None
    duration_ms: int


class UsageLog:
    """Append-only JSONL file. Thread-safe within the process."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: UsageRecord) -> None:
        line = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        try:
            with _append_lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            # The call result still reaches the user; the missing line is visible in api.log.
            logger.error("Cannot append to %s: %s", self.path, exc)


# --- month summary ---


class _Line(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ts: AwareDatetime
    ok: StrictBool
    cost_usd: Decimal | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


@dataclass(frozen=True)
class MonthUsage:
    month: str
    cost_usd: Decimal
    calls: int
    failed_calls: int
    unpriced_calls: int
    input_tokens: int
    output_tokens: int


def _parse_line(raw: str) -> _Line | None:
    try:
        data: Any = json.loads(raw)
        return _Line.model_validate(data)
    except (ValueError, ValidationError, RecursionError):
        return None


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.error("Cannot read %s: %s", path, exc)
        return []


def summarise_month(path: Path, now: datetime, tz: str = DEFAULT_TZ) -> MonthUsage:
    """Totals of the calendar month of `now` in `tz` (Europe/Brussels), by line `ts`.
    Broken lines are skipped (one WARNING with the count)."""
    zone = ZoneInfo(tz)
    month = now.astimezone(zone).strftime("%Y-%m")
    cost, calls, failed, unpriced, tokens_in, tokens_out = Decimal(0), 0, 0, 0, 0, 0
    broken: list[int] = []
    for number, raw in enumerate(_read_lines(path), start=1):
        if not raw.strip():
            continue
        line = _parse_line(raw)
        if line is None:
            broken.append(number)
            continue
        if line.ts.astimezone(zone).strftime("%Y-%m") != month:
            continue
        calls += 1
        failed += 0 if line.ok else 1
        tokens_in += line.input_tokens
        tokens_out += line.output_tokens
        if line.cost_usd is None:
            unpriced += 1
        else:
            cost += line.cost_usd
    if broken:
        logger.warning(
            "%s: skipped %d broken line(s), first at line %d", path, len(broken), broken[0]
        )
    return MonthUsage(
        month, cost.quantize(COST_QUANTUM), calls, failed, unpriced, tokens_in, tokens_out
    )


# --- last success ---


class _OutcomeLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ts: AwareDatetime
    ok: StrictBool
    error_kind: str | None = None


def last_success_at(path: Path) -> datetime | None:
    """Latest `ts` of a successful attempt (ok, no error_kind), any purpose; None when
    there is none. Broken lines are skipped (summarise_month reports them)."""
    latest: datetime | None = None
    for raw in _read_lines(path):
        if not raw.strip():
            continue
        try:
            line = _OutcomeLine.model_validate(json.loads(raw))
        except (ValueError, ValidationError, RecursionError):
            continue
        if line.ok and line.error_kind is None and (latest is None or line.ts > latest):
            latest = line.ts
    return latest
