"""Prop-firm / MT5 accounts (PRD 6.1) and their symbol specifications (PRD 6.2, 6.8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import MONEY, PRICE, RATIO, Base, TimestampMixin, copy_of, enum_check
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
    # Account size (UI «Розмір рахунку», PRD 6.8/6.9): the base of every percentage
    # (risk %, P&L %, rules, calculator). Defaults to starting_balance on insert (M5-10).
    reference_balance: Mapped[Decimal] = mapped_column(MONEY, default=copy_of("starting_balance"))
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
    __table_args__ = (
        UniqueConstraint("account_id", "symbol"),
        CheckConstraint(
            "(mt5_loss_per_tick IS NULL) = (mt5_loss_per_tick_at IS NULL)",
            name="mt5_loss_per_tick_pair",
        ),
        CheckConstraint(
            "mt5_loss_per_tick IS NULL OR (mt5_loss_per_tick > 0 "
            "AND mt5_loss_per_tick::text NOT IN ('NaN', 'Infinity', '-Infinity'))",
            name="mt5_loss_per_tick_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    # Broker name (MT5 calls); the app shows `canonical_symbol` (config/symbols.yaml, M5-08).
    symbol: Mapped[str] = mapped_column(String(50))
    canonical_symbol: Mapped[str] = mapped_column(String(50), default=copy_of("symbol"))
    contract_size: Mapped[Decimal] = mapped_column(PRICE)
    tick_size: Mapped[Decimal] = mapped_column(PRICE)
    tick_value: Mapped[Decimal] = mapped_column(PRICE)
    # Nullable until explicitly supplied by a broker sync; never inferred.
    point: Mapped[Decimal | None] = mapped_column(PRICE)
    tick_value_loss: Mapped[Decimal | None] = mapped_column(PRICE)
    # M5-09 order_calc_profit check (account currency per tick per lot) and when it ran (UTC);
    # cross-currency specs only, both NULL or both set.
    mt5_loss_per_tick: Mapped[Decimal | None] = mapped_column(PRICE)
    mt5_loss_per_tick_at: Mapped[datetime | None]
    volume_min: Mapped[Decimal] = mapped_column(PRICE)
    volume_step: Mapped[Decimal] = mapped_column(PRICE)
    volume_max: Mapped[Decimal] = mapped_column(PRICE)
    digits: Mapped[int] = mapped_column(SmallInteger)
    currency_profit: Mapped[str] = mapped_column(String(10))
    currency_margin: Mapped[str] = mapped_column(String(10))
    synced_at: Mapped[datetime]

    account: Mapped[Account] = relationship(back_populates="symbol_specs")
