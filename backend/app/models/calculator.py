"""Worker-owned margin request snapshots (no execution).

The latest done request for an account/exact symbol/direction is the offline margin sample.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import PRICE, Base, enum_check

# Raw broker margin must survive storage without account-display cent rounding.
MARGIN = Numeric(28, 8)


class CalculatorMarginRequest(Base):
    __tablename__ = "calculator_margin_requests"
    __table_args__ = (
        enum_check("direction", ("buy", "sell"), "direction_valid"),
        enum_check(
            "status", ("pending", "processing", "done", "failed", "expired"), "status_valid"
        ),
        CheckConstraint("btrim(symbol) <> ''", name="symbol_not_empty"),
        CheckConstraint("length(btrim(currency)) = 3", name="currency_valid"),
        CheckConstraint("error_code IS NULL OR btrim(error_code) <> ''", name="error_not_empty"),
        CheckConstraint(
            "volume > 0 AND volume::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name="volume_valid",
        ),
        CheckConstraint(
            "entry > 0 AND entry::text NOT IN ('NaN', 'Infinity', '-Infinity')",
            name="entry_valid",
        ),
        CheckConstraint(
            "margin IS NULL OR (margin >= 0 "
            "AND margin::text NOT IN ('NaN', 'Infinity', '-Infinity'))",
            name="margin_valid",
        ),
        CheckConstraint(
            "expires_at > created_at "
            "AND (started_at IS NULL OR started_at >= created_at) "
            "AND (finished_at IS NULL OR finished_at >= created_at) "
            "AND (started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at)",
            name="timestamps_valid",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL "
            "AND margin IS NULL AND error_code IS NULL) OR "
            "(status = 'processing' AND started_at IS NOT NULL AND finished_at IS NULL "
            "AND margin IS NULL AND error_code IS NULL) OR "
            "(status = 'done' AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND margin IS NOT NULL AND error_code IS NULL) OR "
            "(status IN ('failed', 'expired') AND finished_at IS NOT NULL "
            "AND margin IS NULL AND error_code IS NOT NULL)",
            name="result_matches_status",
        ),
        Index("ix_calculator_margin_requests_queue", "status", "created_at", "id"),
        Index("ix_calculator_margin_requests_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(50))
    direction: Mapped[str] = mapped_column(String(4))
    volume: Mapped[Decimal] = mapped_column(PRICE)
    entry: Mapped[Decimal] = mapped_column(PRICE)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    margin: Mapped[Decimal | None] = mapped_column(MARGIN)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime]
