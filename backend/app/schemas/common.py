"""Shared API field types: Decimal-as-string and UTC datetimes with a `Z` suffix."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


def _decimal_input(value: Any) -> Any:
    """Accept JSON strings and integers only. Floats are rejected: they lose precision."""
    if isinstance(value, bool):
        raise ValueError('must be a decimal string, e.g. "100.00"')
    if isinstance(value, float):
        raise ValueError('must be a decimal string, e.g. "100.00", not a JSON float')
    if isinstance(value, int | Decimal):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            raise ValueError('must be a decimal string, e.g. "100.00"') from None
        if not parsed.is_finite():
            raise ValueError("must be a finite number")
        return parsed
    return value  # None and anything else: let the field type decide


def _serialize_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Use as `Annotated[DecimalIn, Field(gt=0, max_digits=..., decimal_places=...)]`.
# Output: pydantic serializes Decimal to a JSON string by default.
DecimalIn = Annotated[Decimal, BeforeValidator(_decimal_input)]

# Aware datetime rendered as ISO 8601 UTC with `Z`, whatever the DB session time zone is.
UtcDatetime = Annotated[datetime, PlainSerializer(_serialize_utc, return_type=str)]
