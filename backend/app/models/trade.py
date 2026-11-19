"""Trades (PRD 6.4), their exit deals (PRD 6.2) and rule violations (PRD 6.9)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    MONEY,
    PRICE,
    RATIO,
    Base,
    TimestampMixin,
    copy_of,
    enum_check,
    jsonb_default,
)
from app.models.enums import (
    BiasAlignment,
    Direction,
    ExcursionSource,
    ExcursionStatus,
    ExitReasonSource,
    InitialSlSource,
    StatsExclusionAction,
    TradeStatus,
    TradingSession,
    ViolationSource,
)

if TYPE_CHECKING:
    from app.models.media import AudioNote, ChartLink

# Journal option fields (h1_context, entry_model, ...) hold option keys from
# config/journal_fields.yaml. No CHECK on purpose: options change, old values must survive.
JOURNAL_OPTION = String(50)
# multi_enum journal fields with storage: column (M8-04..08).
JOURNAL_OPTIONS = ARRAY(JOURNAL_OPTION)
EXCURSION_POINTS = Numeric(14, 1)  # MAE/MFE distance in symbol points (M8-16)


class Trade(TimestampMixin, Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("account_id", "position_id"),
        Index("ix_trades_account_id_close_time", "account_id", "close_time"),
        enum_check("direction", Direction, "direction_valid"),
        enum_check("status", TradeStatus, "status_valid"),
        enum_check("session", TradingSession, "session_valid"),
        enum_check("initial_sl_source", InitialSlSource, "initial_sl_source_valid"),
        enum_check("bias_alignment", BiasAlignment, "bias_alignment_valid"),
        enum_check("bias_alignment_weekly", BiasAlignment, "bias_alignment_weekly_valid"),
        enum_check("bias_alignment_monthly", BiasAlignment, "bias_alignment_monthly_valid"),
        enum_check("bias_alignment_override", BiasAlignment, "bias_alignment_override_valid"),
        enum_check("exit_reason_source", ExitReasonSource, "exit_reason_source_valid"),
        enum_check("excursion_status", ExcursionStatus, "excursion_status_valid"),
        enum_check("excursion_source", ExcursionSource, "excursion_source_valid"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="hour_range"),
        CheckConstraint("quality_rating BETWEEN 1 AND 5", name="quality_rating_range"),
        CheckConstraint("duration_seconds >= 0", name="duration_non_negative"),
        # Open positions (and only they) have no close_time.
        CheckConstraint("(close_time IS NULL) = (status = 'open')", name="open_iff_no_close_time"),
        CheckConstraint("jsonb_typeof(extra) = 'object'", name="extra_is_object"),
        CheckConstraint(
            "jsonb_typeof(ai_filled_fields) = 'array'", name="ai_filled_fields_is_array"
        ),
        # M8-01: an excluded trade always has its reason and time, a counted one neither.
        CheckConstraint(
            "excluded_from_stats = (excluded_reason IS NOT NULL)"
            " AND excluded_from_stats = (excluded_at IS NOT NULL)"
            " AND (excluded_reason IS NULL OR length(btrim(excluded_reason)) > 0)",
            name="stats_exclusion_consistent",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- Auto fields (MT5 sync, PRD 6.4) ---
    # RESTRICT: trade history must never vanish with an account; archive accounts instead.
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    position_id: Mapped[int] = mapped_column(BigInteger)
    # Canonical name (config/symbols.yaml, M5-08); the broker's own name for MT5 calls.
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    broker_symbol: Mapped[str] = mapped_column(String(50), default=copy_of("symbol"))
    direction: Mapped[str] = mapped_column(String(4))
    open_time: Mapped[datetime]
    close_time: Mapped[datetime | None] = mapped_column(index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    entry_price: Mapped[Decimal] = mapped_column(PRICE)
    exit_price: Mapped[Decimal | None] = mapped_column(PRICE)  # volume-weighted over exit deals
    volume: Mapped[Decimal] = mapped_column(PRICE)
    initial_sl: Mapped[Decimal | None] = mapped_column(PRICE)
    # deal | order | position | user; NULL while initial_sl is unknown.
    initial_sl_source: Mapped[str | None] = mapped_column(String(20))
    # Last SL seen on the open position; SL moved to entry = breakeven violation (PRD 6.9).
    last_sl: Mapped[Decimal | None] = mapped_column(PRICE)
    tp: Mapped[Decimal | None] = mapped_column(PRICE)
    commission: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    swap: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    gross_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    net_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    pnl_pct: Mapped[Decimal | None] = mapped_column(RATIO)
    balance_at_open: Mapped[Decimal | None] = mapped_column(MONEY)
    risk_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    risk_pct: Mapped[Decimal | None] = mapped_column(RATIO)
    r_multiple: Mapped[Decimal | None] = mapped_column(RATIO)
    planned_rr: Mapped[Decimal | None] = mapped_column(RATIO)
    session: Mapped[str | None] = mapped_column(String(20))
    weekday: Mapped[int | None] = mapped_column(SmallInteger)  # Brussels, 0 = Monday
    hour: Mapped[int | None] = mapped_column(SmallInteger)  # Brussels hour of open_time
    is_reentry: Mapped[bool] = mapped_column(Boolean, server_default=false())

    # --- Journal fields (PRD 6.4; options in config/journal_fields.yaml) ---
    # M8-04..08 taxonomy: H1/H4 context, POI and FVG types (multi: VARCHAR(50)[], NULL when
    # empty, never '{}'), each with its «Інше» text.
    h1_context: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    h1_context_other: Mapped[str | None] = mapped_column(Text)
    h4_context: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    h4_context_other: Mapped[str | None] = mapped_column(Text)
    poi_types: Mapped[list[str] | None] = mapped_column(JOURNAL_OPTIONS)
    poi_types_other: Mapped[str | None] = mapped_column(Text)
    fvg_types_h1: Mapped[list[str] | None] = mapped_column(JOURNAL_OPTIONS)
    fvg_types_h1_other: Mapped[str | None] = mapped_column(Text)
    fvg_types_h4: Mapped[list[str] | None] = mapped_column(JOURNAL_OPTIONS)
    fvg_types_h4_other: Mapped[str | None] = mapped_column(Text)
    # Old fields (M8-04..08): setup_context / fvg_kind hold the values the migration could
    # not map exactly (legacy, read-only); poi_type / poi_type_other are always emptied.
    # Never dropped.
    setup_context: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    poi_type: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    poi_type_other: Mapped[str | None] = mapped_column(Text)
    fvg_kind: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    entry_model: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    entry_model_other: Mapped[str | None] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    # Who set exit_reason (M8-09): mt5_reason / price_match = prefilled by the sync (UI marks
    # it), owner = entered/changed/cleared by the owner (sync never touches it); NULL = set
    # before M8-09 or empty.
    exit_reason_source: Mapped[str | None] = mapped_column(String(20))
    # Auto-computed daily alignment (PRD 6.6); the effective value is override ?? auto.
    bias_alignment: Mapped[str | None] = mapped_column(String(20))
    bias_alignment_weekly: Mapped[str | None] = mapped_column(String(20))
    bias_alignment_monthly: Mapped[str | None] = mapped_column(String(20))
    bias_alignment_override: Mapped[str | None] = mapped_column(String(20))
    bias_alignment_override_reason: Mapped[str | None] = mapped_column(Text)
    followed_plan: Mapped[bool | None] = mapped_column(Boolean)
    emotion_before: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    emotion_before_text: Mapped[str | None] = mapped_column(Text)
    emotion_after: Mapped[str | None] = mapped_column(JOURNAL_OPTION)
    emotion_after_text: Mapped[str | None] = mapped_column(Text)
    mistakes: Mapped[str | None] = mapped_column(Text)
    lesson: Mapped[str | None] = mapped_column(Text)
    quality_rating: Mapped[int | None] = mapped_column(SmallInteger)
    raw_text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    # Keys of journal fields last filled by AI (UI marks them).
    ai_filled_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=jsonb_default("[]"))
    # Experimental journal fields not yet promoted to real columns.
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=jsonb_default("{}"))
    status: Mapped[str] = mapped_column(
        String(30), index=True, server_default=TradeStatus.NEEDS_DESCRIPTION.value
    )
    described_at: Mapped[datetime | None]

    # --- M8-01: left out of strategy statistics, still counted in money and risk ---
    # Owner-only columns: the MT5 sync never writes them, so they survive every re-sync.
    excluded_from_stats: Mapped[bool] = mapped_column(Boolean, server_default=false())
    excluded_reason: Mapped[str | None] = mapped_column(Text)
    excluded_at: Mapped[datetime | None]

    # --- M8-16: MAE / MFE (computed from MT5 price history; long = bid, short = ask) ---
    mfe_price: Mapped[Decimal | None] = mapped_column(PRICE)
    mfe_time: Mapped[datetime | None]
    mfe_points: Mapped[Decimal | None] = mapped_column(EXCURSION_POINTS)
    mfe_r: Mapped[Decimal | None] = mapped_column(RATIO)
    mae_price: Mapped[Decimal | None] = mapped_column(PRICE)
    mae_time: Mapped[datetime | None]
    mae_points: Mapped[Decimal | None] = mapped_column(EXCURSION_POINTS)
    mae_r: Mapped[Decimal | None] = mapped_column(RATIO)
    # final | running (open trade, «поточні») | unavailable (no MT5 history); NULL = not yet.
    excursion_status: Mapped[str | None] = mapped_column(String(20))
    excursion_source: Mapped[str | None] = mapped_column(String(10))
    excursion_at: Mapped[datetime | None]

    exit_deals: Mapped[list[TradeExitDeal]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TradeExitDeal.time",
    )
    rule_violations: Mapped[list[RuleViolation]] = relationship(
        back_populates="trade", cascade="all, delete-orphan", passive_deletes=True
    )
    chart_links: Mapped[list[ChartLink]] = relationship(
        back_populates="trade", cascade="all, delete-orphan", passive_deletes=True
    )
    audio_notes: Mapped[list[AudioNote]] = relationship(
        back_populates="trade", cascade="all, delete-orphan", passive_deletes=True
    )
    stats_exclusions: Mapped[list[TradeStatsExclusion]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TradeStatsExclusion.id",
    )


class TradeExitDeal(TimestampMixin, Base):
    """One closing deal of a position; several per trade on partial closes."""

    __tablename__ = "trade_exit_deals"
    __table_args__ = (UniqueConstraint("account_id", "ticket"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    ticket: Mapped[int] = mapped_column(BigInteger)  # MT5 deal ticket
    time: Mapped[datetime]
    price: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[Decimal] = mapped_column(PRICE)
    profit: Mapped[Decimal] = mapped_column(MONEY)
    commission: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    swap: Mapped[Decimal] = mapped_column(MONEY, server_default="0")
    # MT5 DEAL_REASON as lowercase key (client, mobile, web, expert, sl, tp, so, rollover,
    # vmargin, split). No CHECK: an unexpected broker value must not break the sync.
    reason: Mapped[str | None] = mapped_column(String(20))
    # Raw MT5 DEAL_REASON code (M8-09); NULL when MT5 reported none or the deal was
    # stored before M8-09.
    reason_code: Mapped[int | None] = mapped_column(Integer)

    trade: Mapped[Trade] = relationship(back_populates="exit_deals")


class RuleViolation(TimestampMixin, Base):
    __tablename__ = "rule_violations"
    __table_args__ = (
        UniqueConstraint("trade_id", "rule_key"),
        enum_check("source", ViolationSource, "source_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"))
    rule_key: Mapped[str] = mapped_column(String(50))  # key from config/rules.yaml
    source: Mapped[str] = mapped_column(String(10))
    details: Mapped[str | None] = mapped_column(Text)

    trade: Mapped[Trade] = relationship(back_populates="rule_violations")


class TradeStatsExclusion(TimestampMixin, Base):
    """History of M8-01 exclude / include actions; ``created_at`` is when it happened."""

    __tablename__ = "trade_stats_exclusions"
    __table_args__ = (
        enum_check("action", StatsExclusionAction, "action_valid"),
        CheckConstraint(
            "action <> 'exclude' OR length(btrim(reason)) > 0", name="exclude_has_reason"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(Text)

    trade: Mapped[Trade] = relationship(back_populates="stats_exclusions")
