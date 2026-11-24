"""System enums, stored as VARCHAR + CHECK (see `enum_check`).

Journal option fields (h1_context, poi_types, entry_model, emotions, ...) are NOT here:
their options live in config/journal_fields.yaml and change over time (PRD 6.4).
"""

from __future__ import annotations

import enum


class AccountPhase(enum.StrEnum):
    PHASE_1 = "phase_1"
    PHASE_2 = "phase_2"
    FUNDED = "funded"


class AccountPlatform(enum.StrEnum):
    MT5 = "mt5"
    CTRADER = "ctrader"


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


class ExitReasonSource(enum.StrEnum):
    """Who set trades.exit_reason (M8-09); NULL = set before M8-09 or never set."""

    MT5_REASON = "mt5_reason"  # prefilled from the final closing deal's DEAL_REASON
    PRICE_MATCH = "price_match"  # prefilled: no deal reason, exit within 1 tick of SL/TP
    OWNER = "owner"  # entered, changed or cleared by the owner: the sync never touches it


class ExcursionStatus(enum.StrEnum):
    """trades.excursion_status (M8-16): MAE/MFE of the trade."""

    FINAL = "final"  # closed trade, computed over open..close
    RUNNING = "running"  # open trade, computed so far («поточні»)
    UNAVAILABLE = "unavailable"  # MT5 had no price history for the range


class ExcursionSource(enum.StrEnum):
    TICKS = "ticks"  # ticks only (trade shorter than 2 h)
    M1_TICKS = "m1_ticks"  # M1 bars in the middle, ticks for the entry and exit minutes


class StatsExclusionAction(enum.StrEnum):
    """History rows of M8-01: exclude from / return to strategy statistics."""

    EXCLUDE = "exclude"
    INCLUDE = "include"
