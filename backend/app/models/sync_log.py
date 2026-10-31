"""One row per worker sync attempt of one account (PRD 6.2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SyncLog(TimestampMixin, Base):
    __tablename__ = "sync_log"
    __table_args__ = (Index("ix_sync_log_account_id_started_at", "account_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    ok: Mapped[bool | None] = mapped_column(Boolean)  # NULL while the sync is running
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    deals_fetched: Mapped[int] = mapped_column(Integer, server_default="0")
    trades_created: Mapped[int] = mapped_column(Integer, server_default="0")
    trades_updated: Mapped[int] = mapped_column(Integer, server_default="0")
    open_positions: Mapped[int] = mapped_column(Integer, server_default="0")
    symbols_synced: Mapped[int] = mapped_column(Integer, server_default="0")
    server_offset_hours: Mapped[int | None] = mapped_column(SmallInteger)
