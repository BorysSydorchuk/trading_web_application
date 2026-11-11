"""Latest profit -> account currency rate per account (docs/api.md M5-09).

Written by the worker every sync cycle from the conversion pair's latest tick: direct pair
``<P><A>`` uses the ask, inverse ``<A><P>`` uses 1 / bid (``inverted``). ``rate_at`` is the
tick time converted from broker time to UTC (PRD 6.3); ``synced_at`` is when it was stored.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import PRICE, Base


def _positive_finite(column: str) -> str:
    return f"{column} > 0 AND {column}::text NOT IN ('NaN', 'Infinity', '-Infinity')"


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("account_id", "from_currency", "to_currency"),
        CheckConstraint(
            "btrim(from_currency) <> '' AND btrim(to_currency) <> '' "
            "AND upper(from_currency) <> upper(to_currency)",
            name="currencies_valid",
        ),
        CheckConstraint("btrim(pair) <> ''", name="pair_not_empty"),
        CheckConstraint(_positive_finite("bid"), name="bid_valid"),
        CheckConstraint(_positive_finite("ask"), name="ask_valid"),
        CheckConstraint(_positive_finite("rate"), name="rate_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    from_currency: Mapped[str] = mapped_column(String(10))
    to_currency: Mapped[str] = mapped_column(String(10))
    # Broker symbol of the conversion pair (e.g. EURUSD.r).
    pair: Mapped[str] = mapped_column(String(50))
    inverted: Mapped[bool] = mapped_column(Boolean)
    bid: Mapped[Decimal] = mapped_column(PRICE)
    ask: Mapped[Decimal] = mapped_column(PRICE)
    rate: Mapped[Decimal] = mapped_column(PRICE)
    rate_at: Mapped[datetime]
    synced_at: Mapped[datetime]
