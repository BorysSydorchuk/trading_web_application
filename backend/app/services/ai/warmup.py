"""AI warm-up (docs/api.md M3 "AI warm-up"): hide the ~25 s first extraction call.

The API compiles the extraction JSON schema into a grammar on its first use and caches it
(Anthropic docs: 24 h from last use). The worker keeps `<DATA_DIR>/ai_warmup.json` with the
hash of the schema + model it last warmed; when the hash changes (journal_fields.yaml or
ANTHROPIC_MODEL_EXTRACTION changed) it runs one extraction on a short fixed text through
the normal extraction service (same schema, prompt and deadline, no fallback), logged in
ai_usage.jsonl as purpose `warmup` with no trade.

The grammar cache also expires after a quiet day, so the same call also runs (M4-02, PM):
at worker start when the last successful AI call (ai_usage.jsonl, any purpose, or the state
file) is more than 20 h ago, and Mon-Fri at 07:30 Europe/Brussels (the worker's cron job
`ai_warmup_daily` only flags the request, this job makes the call). Several reasons at
once still make one call. A failed warm-up is retried at most once an hour. Nothing here
raises out of `WarmupJob.__call__`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.config_files import ConfigError, get_journal_fields, get_number_words
from app.domain.extraction import build_extraction_schema
from app.services.ai.client import AnthropicModelClient, ModelClient
from app.services.ai.extraction import ExtractionFailed, ExtractionSettings, extract_trade_fields
from app.services.ai.prompt import PromptError
from app.services.ai.usage_log import UsageLog, last_success_at, usage_log_path, utc_ts

logger = logging.getLogger(__name__)

WARMUP_JOB_ID = "ai_warmup"
WARMUP_JOB_INTERVAL_S = 60
WARMUP_PURPOSE = "warmup"
WARMUP_STATE_FILE = "ai_warmup.json"
RETRY_AFTER_FAILURE_S = 3600.0
# Time-based warm-up (PM 2026-11-05). The server keeps a compiled grammar 24 h from last use.
STALE_AFTER = timedelta(hours=20)  # at start: warm up when the last success is older
WARMUP_DAILY_JOB_ID = "ai_warmup_daily"
DAILY_DAYS = "mon-fri"
DAILY_HOUR = 7
DAILY_MINUTE = 30  # 07:30 Europe/Brussels, before the London session
DAILY_GRACE_S = 1800  # asleep/stopped at 07:30 for longer: skip that day, never fire late
# Fixed short Ukrainian description; only the call matters, the answer is thrown away.
WARMUP_TEXT = "Вхід по IFVG M5 після зняття ліквідності, закрив по тейку. Урок: терпіння."


def schema_hash(schema: dict[str, Any], model: str) -> str:
    """sha256 of the canonical JSON of the output schema plus the model id.

    The system prompt is not part of it: only the schema is compiled into the grammar.
    """
    canonical = json.dumps(
        {"model": model, "schema": schema},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- state file ---


class WarmupState(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    schema_hash: str
    model: str
    at: AwareDatetime


def warmup_state_path(settings: Settings) -> Path:
    return settings.data_dir / WARMUP_STATE_FILE


def read_state(path: Path) -> WarmupState | None:
    """The stored state, or None when the file is missing or broken (then we warm up)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("AI warm-up: cannot read %s (%s), treating as not warmed", path, exc)
        return None
    try:
        return WarmupState.model_validate_json(raw)
    except ValidationError:
        logger.warning("AI warm-up: %s is broken, treating as not warmed", path)
        return None


def write_state(path: Path, state: WarmupState) -> None:
    """Atomic write: temp file in the same folder, then replace. Raises OSError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"schema_hash": state.schema_hash, "model": state.model, "at": utc_ts(state.at)},
        indent=2,
    )
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body + "\n")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


# --- job ---


def _utc_now() -> datetime:
    return datetime.now(UTC)


def default_client_factory(settings: Settings) -> ModelClient:
    return AnthropicModelClient(settings.anthropic_api_key)


@dataclass
class WarmupJob:
    """Worker job: one warm-up call when the schema hash differs from the stored one, when
    the last success is stale at worker start, or after `request_daily` (07:30 cron)."""

    settings: Settings
    client_factory: Callable[[Settings], ModelClient] = default_client_factory
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = _utc_now
    _client: ModelClient | None = field(default=None, init=False)
    _failed_at: float | None = field(default=None, init=False)  # monotonic, last failure
    _start_check_pending: bool = field(default=True, init=False)
    _daily_requested_at: datetime | None = field(default=None, init=False)

    def __call__(self) -> None:
        try:
            self.run_once()
        except Exception:  # last resort: a warm-up bug must never stop the worker
            logger.exception("AI warm-up: unexpected error")
            self._failed_at = self.clock()

    def request_daily(self) -> None:
        """Called by the Mon-Fri 07:30 Brussels cron job: the next run makes one call."""
        self._daily_requested_at = self.now()

    def run_once(self) -> bool:
        """True when a warm-up call ran and succeeded (state written)."""
        if not self.settings.ai_configured or self._in_backoff():
            return False
        try:
            config = get_journal_fields()
            number_words = get_number_words()
        except ConfigError as exc:
            # Already logged loudly by the API and at worker start; retried next cycle.
            logger.debug("AI warm-up skipped: %s is invalid", exc.path.name)
            return False
        model = self.settings.anthropic_model_extraction
        digest = schema_hash(build_extraction_schema(config), model)
        path = warmup_state_path(self.settings)
        reasons = self._reasons(digest, read_state(path))
        if not reasons:
            return False
        logger.info("AI warm-up (%s), model %s", "; ".join(reasons), model)
        try:
            extract_trade_fields(
                WARMUP_TEXT,
                trade_id=None,
                config=config,
                number_words=number_words,
                client=self._model_client(),
                settings=ExtractionSettings(model, None, self.settings.anthropic_effort),
                usage_log=UsageLog(usage_log_path(self.settings)),
                purpose=WARMUP_PURPOSE,
                clock=self.clock,
                now=self.now,
            )
        except (ExtractionFailed, PromptError) as exc:
            self._failed_at = self.clock()
            logger.warning(
                "AI warm-up failed (%s); the next extraction may take ~25 s. Retrying in %d min.",
                exc.kind if isinstance(exc, ExtractionFailed) else str(exc),
                round(RETRY_AFTER_FAILURE_S / 60),
            )
            return False
        self._failed_at = None
        self._start_check_pending = False
        self._daily_requested_at = None
        return self._store(path, WarmupState(schema_hash=digest, model=model, at=self.now()))

    def _reasons(self, digest: str, stored: WarmupState | None) -> list[str]:
        """Why a call is due now; empty = no call. Clears the start check once not stale."""
        reasons: list[str] = []
        if stored is None or stored.schema_hash != digest:
            reasons.append("extraction schema changed")
        if self._start_check_pending:
            if self._stale(stored):
                reasons.append(f"no successful AI call in the last {_hours(STALE_AFTER)} h")
            else:
                self._start_check_pending = False
        if self._daily_due():
            reasons.append("weekday 07:30 Brussels")
        return reasons

    def _stale(self, stored: WarmupState | None) -> bool:
        moments = [last_success_at(usage_log_path(self.settings))]
        moments.append(stored.at if stored is not None else None)
        known = [m for m in moments if m is not None]
        return not known or self.now() - max(known) > STALE_AFTER

    def _daily_due(self) -> bool:
        requested = self._daily_requested_at
        if requested is None:
            return False
        if (self.now() - requested).total_seconds() > DAILY_GRACE_S:
            logger.info(
                "AI warm-up: the 07:30 warm-up is skipped (not run within %d min)",
                DAILY_GRACE_S // 60,
            )
            self._daily_requested_at = None
            return False
        return True

    def _store(self, path: Path, state: WarmupState) -> bool:
        try:
            write_state(path, state)
        except OSError as exc:
            logger.error("AI warm-up done, but cannot write %s: %s", path, exc)
            self._failed_at = self.clock()  # don't pay for a warm-up every minute
            return False
        logger.info("AI warm-up done (model %s)", state.model)
        return True

    def _in_backoff(self) -> bool:
        return (
            self._failed_at is not None and self.clock() - self._failed_at < RETRY_AFTER_FAILURE_S
        )

    def _model_client(self) -> ModelClient:
        if self._client is None:
            self._client = self.client_factory(self.settings)
        return self._client


def _hours(delta: timedelta) -> int:
    return round(delta.total_seconds() / 3600)
