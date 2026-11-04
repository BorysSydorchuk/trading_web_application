"""AI warm-up (docs/api.md M3 "AI warm-up"): hide the ~25 s first extraction call.

The API compiles the extraction JSON schema into a grammar on its first use and caches it
(Anthropic docs: 24 h from last use). The worker keeps `<DATA_DIR>/ai_warmup.json` with the
hash of the schema + model it last warmed; when the hash changes (journal_fields.yaml or
ANTHROPIC_MODEL_EXTRACTION changed) it runs one extraction on a short fixed text through
the normal extraction service (same schema, prompt and deadline, no fallback), logged in
ai_usage.jsonl as purpose `warmup` with no trade. A failed warm-up is retried at most once
an hour. Nothing here raises out of `WarmupJob.__call__`.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.config_files import ConfigError, get_journal_fields
from app.domain.extraction import build_extraction_schema
from app.services.ai.client import AnthropicModelClient, ModelClient
from app.services.ai.extraction import ExtractionFailed, ExtractionSettings, extract_trade_fields
from app.services.ai.prompt import PromptError
from app.services.ai.usage_log import UsageLog, usage_log_path, utc_ts

logger = logging.getLogger(__name__)

WARMUP_JOB_ID = "ai_warmup"
WARMUP_JOB_INTERVAL_S = 60
WARMUP_PURPOSE = "warmup"
WARMUP_STATE_FILE = "ai_warmup.json"
RETRY_AFTER_FAILURE_S = 3600.0
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
    """Worker job: one warm-up call when the schema hash differs from the stored one."""

    settings: Settings
    client_factory: Callable[[Settings], ModelClient] = default_client_factory
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = _utc_now
    _client: ModelClient | None = field(default=None, init=False)
    _failed_at: float | None = field(default=None, init=False)  # monotonic, last failure

    def __call__(self) -> None:
        try:
            self.run_once()
        except Exception:  # last resort: a warm-up bug must never stop the worker
            logger.exception("AI warm-up: unexpected error")
            self._failed_at = self.clock()

    def run_once(self) -> bool:
        """True when a warm-up call ran and succeeded (state written)."""
        if not self.settings.ai_configured:
            return False
        try:
            config = get_journal_fields()
        except ConfigError:
            # Already logged loudly by the API and at worker start; retried next cycle.
            logger.debug("AI warm-up skipped: journal_fields.yaml is invalid")
            return False
        model = self.settings.anthropic_model_extraction
        digest = schema_hash(build_extraction_schema(config), model)
        path = warmup_state_path(self.settings)
        stored = read_state(path)
        if stored is not None and stored.schema_hash == digest:
            return False
        if self._in_backoff():
            return False
        logger.info("AI warm-up: extraction schema changed (model %s), warming up", model)
        try:
            extract_trade_fields(
                WARMUP_TEXT,
                trade_id=None,
                config=config,
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
        try:
            write_state(path, WarmupState(schema_hash=digest, model=model, at=self.now()))
        except OSError as exc:
            logger.error("AI warm-up done, but cannot write %s: %s", path, exc)
            self._failed_at = self.clock()  # don't pay for a warm-up every minute
            return False
        logger.info("AI warm-up done (model %s)", model)
        return True

    def _in_backoff(self) -> bool:
        return (
            self._failed_at is not None and self.clock() - self._failed_at < RETRY_AFTER_FAILURE_S
        )

    def _model_client(self) -> ModelClient:
        if self._client is None:
            self._client = self.client_factory(self.settings)
        return self._client
