"""Accounts CRUD (docs/api.md "Accounts", PRD 6.1). Investor passwords never pass through here."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import mt5_password_for, mt5_password_key
from app.db import get_db
from app.errors import ApiError
from app.models import Account, Trade
from app.models.enums import AccountPhase, AccountStatus
from app.schemas import accounts as schemas

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["accounts"])

# Unique constraint name (models/base.py naming convention) -> (field, message).
_CONFLICTS: dict[str, tuple[str, str]] = {
    "uq_accounts_name": ("name", "An account with this name already exists"),
    "uq_accounts_login_server": (
        "login",
        "An account with this login and server already exists",
    ),
}


def to_schema(account: Account) -> schemas.Account:
    return schemas.Account(
        id=account.id,
        name=account.name,
        firm=account.firm,
        program=account.program,
        phase=AccountPhase(account.phase),
        login=account.login,
        server=account.server,
        terminal_path=account.terminal_path,
        starting_balance=account.starting_balance,
        currency=account.currency,
        status=AccountStatus(account.status),
        reference_balance=account.reference_balance,
        daily_loss_pct=account.daily_loss_pct,
        max_drawdown_pct=account.max_drawdown_pct,
        profit_target_pct=account.profit_target_pct,
        password_env_key=mt5_password_key(account.login),
        password_configured=mt5_password_for(account.login) is not None,
        balance=account.balance,
        equity=account.equity,
        balance_synced_at=account.balance_synced_at,
        server_offset_hours=account.server_offset_hours,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _get_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise ApiError(404, "not_found", "Account not found", {"id": account_id})
    return account


def _commit(db: Session) -> None:
    """Commit; a duplicate name or login+server becomes a 409 with `details.field`."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        diag = getattr(exc.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        if constraint in _CONFLICTS:
            field, message = _CONFLICTS[constraint]
            raise ApiError(409, "conflict", message, {"field": field}) from None
        raise


@router.get("", response_model=schemas.AccountList)
def list_accounts(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> schemas.AccountList:
    query = select(Account).order_by(func.lower(Account.name), Account.id)
    if not include_archived:
        query = query.where(Account.status != AccountStatus.ARCHIVED.value)
    return schemas.AccountList(items=[to_schema(a) for a in db.scalars(query)])


@router.post("", status_code=201, response_model=schemas.Account)
def create_account(body: schemas.AccountInput, db: Session = Depends(get_db)) -> schemas.Account:
    data: dict[str, Any] = body.model_dump()
    data["phase"] = body.phase.value
    data["status"] = body.status.value
    account = Account(**data)
    db.add(account)
    _commit(db)
    db.refresh(account)
    logger.info(
        "Account %s created (login %s, server %s)", account.id, account.login, account.server
    )
    return to_schema(account)


@router.get("/{account_id}", response_model=schemas.Account)
def get_account(account_id: int, db: Session = Depends(get_db)) -> schemas.Account:
    return to_schema(_get_or_404(db, account_id))


@router.patch("/{account_id}", response_model=schemas.Account)
def update_account(
    account_id: int, body: schemas.AccountPatch, db: Session = Depends(get_db)
) -> schemas.Account:
    account = _get_or_404(db, account_id)
    changes = body.changes()
    for key, value in changes.items():
        setattr(account, key, value)
    _commit(db)
    db.refresh(account)
    logger.info("Account %s updated: %s", account.id, ", ".join(sorted(changes)) or "no fields")
    return to_schema(account)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> Response:
    """Accounts with trades are archived (trade history must survive), others deleted."""
    account = _get_or_404(db, account_id)
    has_trades = db.scalar(select(exists().where(Trade.account_id == account.id)))
    if has_trades:
        account.status = AccountStatus.ARCHIVED.value
        logger.info("Account %s archived (has trades)", account.id)
    else:
        db.delete(account)
        logger.info("Account %s deleted", account.id)
    db.commit()
    return Response(status_code=204)
