"""System enums, stored as VARCHAR + CHECK (see `enum_check`).

Journal option fields (setup_context, poi_type, entry_model, emotions, ...) are NOT here:
their options live in config/journal_fields.yaml and change over time (PRD 6.4).
"""

from __future__ import annotations

import enum


class AccountPhase(enum.StrEnum):
    PHASE_1 = "phase_1"
    PHASE_2 = "phase_2"
    FUNDED = "funded"


class AccountStatus(enum.StrEnum):
    ACTIVE = "active"
    PASSED = "passed"
    FAILED = "failed"
    ARCHIVED = "archived"


class Direction(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradeStatus(enum.StrEnum):
    OPEN = "open"  # position still open (close_time NULL); never shown in the inbox
    NEEDS_SL = "needs_sl"
    NEEDS_DESCRIPTION = "needs_description"
    DRAFT = "draft"
    COMPLETE = "complete"


class InitialSlSource(enum.StrEnum):
    """Where trades.initial_sl came from, in lookup order (DECISIONS.md 2026-11-01)."""

    DEAL = "deal"  # opening deal's sl
    ORDER = "order"  # opening order's sl
    POSITION = "position"  # first SL the worker saw on the open position
    USER = "user"  # entered by the user (needs_sl)


class TradingSession(enum.StrEnum):
    LONDON = "london"
    PREMARKET = "premarket"
    NY = "ny"
    OUTSIDE = "outside"


class BiasAlignment(enum.StrEnum):
    ALIGNED = "aligned"
    COUNTER = "counter"
    NEUTRAL_BIAS = "neutral_bias"
    NO_BIAS = "no_bias"


class BiasKind(enum.StrEnum):
    PRE_LONDON = "pre_london"
    PRE_NY = "pre_ny"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BiasDirection(enum.StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    NO_TRADE = "no_trade"


class BiasCorrectSource(enum.StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class ChartLinkKind(enum.StrEnum):
    BEFORE = "before"
    AFTER = "after"
    BIAS = "bias"


class TranscriptionStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class TranscriptionErrorCode(enum.StrEnum):
    """Why a voice note failed (docs/api.md M3); the UI maps it to Ukrainian text."""

    AUDIO_UNREADABLE = "audio_unreadable"  # file can't be decoded
    AUDIO_MISSING = "audio_missing"  # file gone from disk
    NO_SPEECH = "no_speech"  # nothing recognised
    MODEL_UNAVAILABLE = "model_unavailable"  # model can't be loaded/downloaded
    TIMEOUT = "timeout"  # > 600 s of work
    TRANSCRIPTION_FAILED = "transcription_failed"  # anything else


class DigestKind(enum.StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ViolationSource(enum.StrEnum):
    AUTO = "auto"
    USER = "user"
