"""Prop-firm / MT5 accounts (PRD 6.1) and their symbol specifications (PRD 6.2, 6.8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MONEY, PRICE, RATIO, Base, TimestampMixin, enum_check
from app.models.enums import AccountPhase, AccountStatus


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("name"),
        UniqueConstraint("login", "server"),
        enum_check("phase", AccountPhase, "phase_valid"),
        enum_check("status", AccountStatus, "status_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    firm: Mapped[str] = mapped_column(String(100))
    program: Mapped[str] = mapped_column(String(100))
    phase: Mapped[str] = mapped_column(String(20))
    # The investor password is not stored here: it lives in .env as MT5_PASSWORD_<login>.
    login: Mapped[int] = mapped_column(BigInteger)
    server: Mapped[str] = mapped_column(String(100))
    # Portable terminal folder / terminal64.exe path; nullable so archived accounts need none.
    terminal_path: Mapped[str | None] = mapped_column(String(500))
    starting_balance: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), server_default=AccountStatus.ACTIVE.value)
    # Firm's reference balance for risk sizing (PRD 6.8); NULL = use current balance.
    reference_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    daily_loss_pct: Mapped[Decimal | None] = mapped_column(RATIO)
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(RATIO)
    profit_target_pct: Mapped[Decimal | None] = mapped_column(RATIO)
    # Broker server time minus UTC in whole hours, detected by the worker (PRD 6.3).
    server_offset_hours: Mapped[int | None] = mapped_column(SmallInteger)
    server_offset_detected_at: Mapped[datetime | None]
    # Last MT5 account info seen by the worker (PRD 6.2, 6.8, 6.9).
    balance: Mapped[Decimal | None] = mapped_column(MONEY)
    equity: Mapped[Decimal | None] = mapped_column(MONEY)
    balance_synced_at: Mapped[datetime | None]

    symbol_specs: Mapped[list[SymbolSpec]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class SymbolSpec(TimestampMixin, Base):
    __tablename__ = "symbol_specs"
    __table_args__ = (UniqueConstraint("account_id", "symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(50))
    contract_size: Mapped[Decimal] = mapped_column(PRICE)
    tick_size: Mapped[Decimal] = mapped_column(PRICE)
    tick_value: Mapped[Decimal] = mapped_column(PRICE)
    # Nullable until explicitly supplied by a broker sync; never inferred.
    point: Mapped[Decimal | None] = mapped_column(PRICE)
    tick_value_loss: Mapped[Decimal | None] = mapped_column(PRICE)
    volume_min: Mapped[Decimal] = mapped_column(PRICE)
    volume_step: Mapped[Decimal] = mapped_column(PRICE)
    volume_max: Mapped[Decimal] = mapped_column(PRICE)
    digits: Mapped[int] = mapped_column(SmallInteger)
    currency_profit: Mapped[str] = mapped_column(String(10))
    currency_margin: Mapped[str] = mapped_column(String(10))
    synced_at: Mapped[datetime]

    account: Mapped[Account] = relationship(back_populates="symbol_specs")
