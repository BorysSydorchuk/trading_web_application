"""Accounts API schemas (docs/api.md "Accounts", PRD 6.1)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError

from app.domain.terminal_path import (
    PROGRAM_FILES_CODE,
    PROGRAM_FILES_MESSAGE,
    TERMINAL_EXE,
    is_in_program_files,
)
from app.models.enums import AccountPhase, AccountStatus
from app.schemas.common import DecimalIn, UtcDatetime

MAX_LOGIN = 2**63 - 1  # accounts.login is BIGINT

Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Login = Annotated[int, Field(strict=True, gt=0, le=MAX_LOGIN)]
# NUMERIC(18,2) and NUMERIC(10,4) (models/base.py): reject extra decimals instead of rounding.
PositiveMoney = Annotated[DecimalIn, Field(gt=0, max_digits=18, decimal_places=2)]
Percent = Annotated[DecimalIn, Field(ge=0, le=100, max_digits=10, decimal_places=4)]
TerminalPath = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


def _check_terminal_path(value: str | None) -> str | None:
    """Blank means "not set". Existence is not checked: the API may run before the terminal
    is installed, and the worker reports `terminal_not_found` anyway. A path under
    Program Files fails with the stable type `terminal_in_program_files` (API
    `details.field_codes`); it is checked first, as it is the more useful hint."""
    if value is None or value == "":
        return None
    if is_in_program_files(value):
        raise PydanticCustomError(PROGRAM_FILES_CODE, PROGRAM_FILES_MESSAGE)
    name = value.replace("/", "\\").rsplit("\\", 1)[-1]
    if name.lower() != TERMINAL_EXE:
        raise ValueError(f"must be the full path to {TERMINAL_EXE}")
    return value


class AccountInput(BaseModel):
    """POST body. Unknown keys (e.g. a password) are rejected with 422."""

    model_config = ConfigDict(extra="forbid")

    name: Name100
    firm: Name100
    program: Name100
    phase: AccountPhase
    login: Login
    server: Name100
    terminal_path: TerminalPath | None = None
    starting_balance: PositiveMoney
    currency: Currency
    status: AccountStatus = AccountStatus.ACTIVE
    reference_balance: PositiveMoney | None = None
    daily_loss_pct: Percent | None = None
    max_drawdown_pct: Percent | None = None
    profit_target_pct: Percent | None = None

    @field_validator("terminal_path")
    @classmethod
    def _terminal_path(cls, value: str | None) -> str | None:
        return _check_terminal_path(value)


_NOT_NULLABLE = (
    "name",
    "firm",
    "program",
    "phase",
    "login",
    "server",
    "starting_balance",
    "currency",
    "status",
)


class AccountPatch(BaseModel):
    """PATCH body: any subset of AccountInput. Required fields may be omitted, not nulled."""

    model_config = ConfigDict(extra="forbid")

    name: Name100 | None = None
    firm: Name100 | None = None
    program: Name100 | None = None
    phase: AccountPhase | None = None
    login: Login | None = None
    server: Name100 | None = None
    terminal_path: TerminalPath | None = None
    starting_balance: PositiveMoney | None = None
    currency: Currency | None = None
    status: AccountStatus | None = None
    reference_balance: PositiveMoney | None = None
    daily_loss_pct: Percent | None = None
    max_drawdown_pct: Percent | None = None
    profit_target_pct: Percent | None = None

    @field_validator("terminal_path")
    @classmethod
    def _terminal_path(cls, value: str | None) -> str | None:
        return _check_terminal_path(value)

    # Runs only for fields present in the body (defaults are not validated).
    @field_validator(*_NOT_NULLABLE)
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("cannot be null")
        return value

    def changes(self) -> dict[str, Any]:
        """Only the fields sent by the client, as plain values for the ORM."""
        return {
            key: getattr(self, key).value if key in {"phase", "status"} else getattr(self, key)
            for key in self.model_fields_set
        }


class Account(BaseModel):
    """Response: AccountInput fields + read-only sync/password info. Never the password."""

    id: int
    name: str
    firm: str
    program: str
    phase: AccountPhase
    login: int
    server: str
    terminal_path: str | None
    starting_balance: Decimal
    currency: str
    status: AccountStatus
    reference_balance: Decimal | None
    daily_loss_pct: Decimal | None
    max_drawdown_pct: Decimal | None
    profit_target_pct: Decimal | None
    password_env_key: str
    password_configured: bool
    balance: Decimal | None
    equity: Decimal | None
    balance_synced_at: UtcDatetime | None
    server_offset_hours: int | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class AccountList(BaseModel):
    items: list[Account]
