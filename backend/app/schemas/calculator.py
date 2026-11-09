"""Calculator API schemas (docs/api.md M5, "M5-04c exact shapes", PRD 6.8)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from app.domain.position_size import check_positive_decimal
from app.schemas.common import DecimalIn, UtcDatetime

MAX_SYMBOL_LENGTH = 50  # symbol_specs.symbol is VARCHAR(50)
MAX_ID = 2**31 - 1  # accounts.id is INTEGER

Direction = Literal["buy", "sell"]
AccountId = Annotated[int, Field(gt=0, le=MAX_ID)]
NUL = 0
SURROGATES = range(0xD800, 0xE000)  # UTF-16 surrogate code points


def _storable_symbol(value: str) -> str:
    """NUL and lone UTF-16 surrogates cannot be stored or bound by Postgres/psycopg."""
    if any(ord(char) == NUL or ord(char) in SURROGATES for char in value):
        raise ValueError("symbol must not contain NUL or surrogate characters")
    return value


# Exact broker symbol: not stripped or case-folded (never prefix/fuzzy matched).
Symbol = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_SYMBOL_LENGTH),
    AfterValidator(_storable_symbol),
]


def plain_decimal(value: Decimal) -> str:
    """Plain notation, never an exponent (`1E-7` -> `0.0000001`), all digits kept."""
    return format(value, "f")


# Output decimal: JSON string in plain notation, full precision (the UI rounds).
PlainDecimal = Annotated[Decimal, PlainSerializer(plain_decimal, return_type=str)]

_DECIMAL_FIELDS = ("entry", "sl_price", "sl_points", "risk_percent", "risk_amount")


class CalculateInput(BaseModel):
    """POST /api/calculator/calculate. Decimal strings or JSON integers only; unknown keys,
    floats, bools, NaN/Infinity and explicit nulls are 422. Optional fields may be omitted,
    never nulled. SL/risk combinations are checked by the service (they span fields)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    account_id: AccountId
    symbol: Symbol
    direction: Direction
    entry: DecimalIn
    sl_price: DecimalIn | None = None
    sl_points: DecimalIn | None = None
    risk_percent: DecimalIn | None = None
    risk_amount: DecimalIn | None = None

    # Runs only for fields present in the body (defaults are not validated), so an
    # explicit null is rejected while an omitted field stays None.
    @field_validator(*_DECIMAL_FIELDS)
    @classmethod
    def _positive_within_core_limits(cls, value: Decimal | None, info: ValidationInfo) -> Decimal:
        if value is None:
            raise ValueError("cannot be null")
        # Same positivity and representation limits as the pure core (PositionSizeError
        # is a ValueError, so pydantic reports it on this field).
        return check_positive_decimal(value, info.field_name or "value")


class SymbolSpecItem(BaseModel):
    symbol: str
    contract_size: PlainDecimal
    point: PlainDecimal | None
    tick_size: PlainDecimal
    tick_value_loss: PlainDecimal | None
    volume_min: PlainDecimal
    volume_step: PlainDecimal
    volume_max: PlainDecimal
    digits: int
    currency_profit: str
    currency_margin: str
    synced_at: UtcDatetime


class SymbolSpecList(BaseModel):
    items: list[SymbolSpecItem]


class MarginInfo(BaseModel):
    model_config = ConfigDict(frozen=True)  # NO_CACHED_MARGIN is shared across responses

    source: Literal["cached_estimate", "unavailable"]
    amount: PlainDecimal | None
    currency: str | None
    calculated_at: UtcDatetime | None
    sample_price: PlainDecimal | None
    sample_volume: PlainDecimal | None
    reason: Literal["no_cached_margin"] | None


class CalculateResult(BaseModel):
    account_id: int
    symbol: str
    direction: Direction
    entry: PlainDecimal
    sl_price: PlainDecimal
    sl_distance: PlainDecimal
    sl_points: PlainDecimal
    balance: PlainDecimal
    balance_source: Literal["reference", "synced"]
    balance_synced_at: UtcDatetime | None
    currency: str
    risk_percent: PlainDecimal | None
    risk_amount: PlainDecimal | None
    risk_budget: PlainDecimal
    volume: PlainDecimal
    actual_risk: PlainDecimal
    actual_risk_percent: PlainDecimal
    tp_1_5: PlainDecimal
    tp_2: PlainDecimal
    tp_3: PlainDecimal
    specs_at: UtcDatetime
    margin: MarginInfo
