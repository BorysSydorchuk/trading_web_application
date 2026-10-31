"""Declarative base, shared column types and mixins for all ORM models."""

from __future__ import annotations

import enum
from collections.abc import Iterable
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import CheckConstraint, DateTime, MetaData, Numeric, TextClause, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Numeric precisions (DECISIONS.md). Python side is always Decimal.
MONEY = Numeric(18, 2)  # account-currency amounts: balance, P&L, commission, swap, risk amount
PRICE = Numeric(20, 8)  # prices, volumes, contract size, tick size/value
RATIO = Numeric(10, 4)  # percentages and R values (risk %, P&L %, R multiple, planned RR)

TZ_DATETIME = DateTime(timezone=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Any `Mapped[datetime]` without an explicit type becomes TIMESTAMPTZ (UTC only).
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: TZ_DATETIME}


class TimestampMixin:
    """`created_at` / `updated_at` set by the DB; `updated_at` bumped on ORM updates."""

    created_at: Mapped[datetime] = mapped_column(
        TZ_DATETIME, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZ_DATETIME, nullable=False, server_default=func.now(), onupdate=func.now()
    )


def enum_check(
    column: str, values: type[enum.StrEnum] | Iterable[str], name: str
) -> CheckConstraint:
    """VARCHAR + CHECK instead of a PG ENUM type: adding a value is a one-line migration.

    `name` is the short constraint name; the naming convention prefixes `ck_<table>_`.
    """
    options = [v.value for v in values] if isinstance(values, type) else list(values)
    quoted = ", ".join(f"'{v}'" for v in options)
    return CheckConstraint(f"{column} IN ({quoted})", name=name)


def jsonb_default(value: str) -> TextClause:
    """Server default for JSONB columns, e.g. `jsonb_default("{}")` -> `'{}'::jsonb`."""
    return text(f"'{value}'::jsonb")
