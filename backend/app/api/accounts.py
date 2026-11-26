"""Accounts CRUD (docs/api.md "Accounts", PRD 6.1). Investor passwords never pass through here."""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import exists, func, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings, mt5_password_for, mt5_password_key
from app.config_files import get_firms_config, get_rules
from app.config_files.firms import FirmsConfig
from app.config_files.loader import ConfigError
from app.config_files.rules import RulesConfig
from app.db import get_db
from app.errors import ApiError, config_error
from app.models import Account, Trade
from app.models.enums import AccountPhase, AccountPlatform, AccountStatus
from app.schemas import accounts as schemas
from app.services import starting_balance_suggestion as suggestion
from app.services.firm_day import account_firm_rules
from app.services.risk_base import recompute_account

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["accounts"])

# Unique constraint name (models/base.py naming convention) -> (field, message).
_CONFLICTS: dict[str, tuple[str, str]] = {
    "uq_accounts_name": ("name", "An account with this name already exists"),
    "uq_accounts_mt5_login_server": (
        "login",
        "An account with this login and server already exists",
    ),
    "uq_accounts_ctid_trader_account_id": (
        "ctid_trader_account_id",
        "This cTrader account is already added",
    ),
}

# What identifies a cTrader account comes from cTrader, never from the edit form.
_CTRADER_FIXED_FIELDS = ("login", "server", "terminal_path")

# Account fields the stored percents and auto rule violations depend on (size, firm rules).
_RULE_FIELDS = ("reference_balance", "firm", "daily_loss_pct")

# PATCH size whose recomputed risk % / P&L % overflow trades' NUMERIC(10,4) (M5-10).
_SIZE_TOO_SMALL = "Account size is too small: trade percentages would exceed 999999.9999 %"


def _suggestions(settings: Settings) -> dict[int, suggestion.Suggestion]:
    return suggestion.read_suggestions(suggestion.suggestions_path(settings.data_dir))


def _suggestion_schema(
    account: Account, suggestions: dict[int, suggestion.Suggestion]
) -> schemas.StartingBalanceSuggestion | None:
    entry = suggestion.suggestion_for(suggestions, account.id, account.starting_balance)
    if entry is None or entry.amount is None or entry.time is None:
        return None
    return schemas.StartingBalanceSuggestion(amount=entry.amount, time=entry.time)


class FirmContext(NamedTuple):
    """The configs firm rules are built from; None = the file is invalid (already logged)."""

    firms: FirmsConfig | None
    rules: RulesConfig | None


def firm_context() -> FirmContext:
    """Load firms.yaml and rules.yaml once per request. A broken file is logged here once
    (ERROR firms.yaml, WARNING rules.yaml: it only drops the `account_limits` fallback); the
    accounts pages keep working without firm rules."""
    firms: FirmsConfig | None = None
    rules: RulesConfig | None = None
    try:
        firms = get_firms_config()
    except ConfigError as exc:
        logger.error("firms.yaml is invalid, firm rules are not shown: %s", exc)
    try:
        rules = get_rules()
    except ConfigError as exc:
        logger.warning("rules.yaml is invalid, no account_limits fallback for firm rules: %s", exc)
    return FirmContext(firms, rules)


def require_firms() -> None:
    """Before writing an account: a broken firms.yaml is a 500 config_error and nothing is
    written (its rules would be recomputed from it)."""
    try:
        get_firms_config()
    except ConfigError as exc:
        raise config_error(exc) from None


def _firm_rules(account: Account, context: FirmContext) -> schemas.FirmRulesOut | None:
    """Effective firm rules (None when nothing applies or firms.yaml is invalid)."""
    if context.firms is None:
        return None
    effective = account_firm_rules(account, context.rules, context.firms)
    if effective.source == "none":
        return None
    return schemas.FirmRulesOut(
        firm=effective.firm or account.firm,
        source=effective.source,
        daily_loss_pct=effective.daily_loss_pct,
        max_loss_pct=effective.max_loss_pct,
        max_loss_type=effective.max_loss_type,
        profit_target_pct=effective.profit_target_pct,
        daily_basis=effective.daily_basis,
        daily_reset=effective.daily_reset,
        reset_timezone=effective.reset_timezone,
        to_verify=list(effective.to_verify),
    )


def to_schema(
    account: Account,
    suggestions: dict[int, suggestion.Suggestion] | None = None,
    context: FirmContext | None = None,
) -> schemas.Account:
    """``suggestions``: the starting balance suggestions file (None = no suggestion).
    ``context``: the firm configs of this request (None = load them for this account).

    A cTrader account has no investor password: the key is empty and nothing is missing.
    """
    is_mt5 = account.platform == AccountPlatform.MT5.value
    return schemas.Account(
        id=account.id,
        platform=AccountPlatform(account.platform),
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
        password_env_key=mt5_password_key(account.login) if is_mt5 else "",
        password_configured=mt5_password_for(account.login) is not None if is_mt5 else True,
        balance=account.balance,
        equity=account.equity,
        balance_synced_at=account.balance_synced_at,
        server_offset_hours=account.server_offset_hours,
        created_at=account.created_at,
        updated_at=account.updated_at,
        starting_balance_suggestion=_suggestion_schema(account, suggestions or {}),
        firm_rules=_firm_rules(account, context if context is not None else firm_context()),
    )


def _get_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise ApiError(404, "not_found", "Account not found", {"id": account_id})
    return account


def commit_account(db: Session) -> None:
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
    settings: Settings = Depends(get_settings),
) -> schemas.AccountList:
    query = select(Account).order_by(func.lower(Account.name), Account.id)
    if not include_archived:
        query = query.where(Account.status != AccountStatus.ARCHIVED.value)
    suggestions = _suggestions(settings)
    context = firm_context()  # once per request, not per account
    return schemas.AccountList(
        items=[to_schema(a, suggestions, context) for a in db.scalars(query)]
    )


@router.post("", status_code=201, response_model=schemas.Account)
def create_account(
    body: schemas.AccountInput,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> schemas.Account:
    require_firms()
    data: dict[str, Any] = body.model_dump()
    data["phase"] = body.phase.value
    data["status"] = body.status.value
    if data["reference_balance"] is None:  # account size defaults to starting balance (M5-10)
        data["reference_balance"] = body.starting_balance
    account = Account(**data)
    db.add(account)
    commit_account(db)
    db.refresh(account)
    logger.info(
        "Account %s created (login %s, server %s)", account.id, account.login, account.server
    )
    return to_schema(account, _suggestions(settings))


@router.get("/{account_id}", response_model=schemas.Account)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> schemas.Account:
    return to_schema(_get_or_404(db, account_id), _suggestions(settings))


def _recompute_size(db: Session, account_id: int) -> None:
    """Percents and rule violations follow the account size, in this transaction (M5-10).

    On failure the transaction is rolled back (the size is not changed): a broken rules.yaml or
    firms.yaml is
    500 config_error, percents overflowing NUMERIC(10,4) (a tiny size) are 422 on the field.
    """
    try:
        count = recompute_account(db, account_id)
    except ConfigError as exc:
        db.rollback()
        logger.error("Account %s: not changed, a config file is invalid: %s", account_id, exc)
        raise config_error(exc) from None
    except DataError:
        db.rollback()
        logger.error(
            "Account %s: size not changed, its trade percents would not fit NUMERIC(10,4)",
            account_id,
        )
        raise ApiError(
            422,
            "validation_error",
            "Request validation failed",
            {"fields": {"reference_balance": _SIZE_TOO_SMALL}},
        ) from None
    logger.info("Account %s: size changed, %s trades recomputed", account_id, count)


def _same_value(key: str, new: Any, current: Any) -> bool:
    """A blank terminal path and NULL both mean "not set"."""
    return (new or None) == (current or None) if key == "terminal_path" else new == current


def _refuse_ctrader_identity_change(account: Account, changes: dict[str, Any]) -> None:
    """The edit form may resend these unchanged; an actual change is a 422."""
    if account.platform == AccountPlatform.MT5.value:
        return
    fields = {
        key: "cannot be changed for a cTrader account"
        for key in _CTRADER_FIXED_FIELDS
        if key in changes and not _same_value(key, changes[key], getattr(account, key))
    }
    if fields:
        raise ApiError(422, "validation_error", "Request validation failed", {"fields": fields})


@router.patch("/{account_id}", response_model=schemas.Account)
def update_account(
    account_id: int,
    body: schemas.AccountPatch,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> schemas.Account:
    account = _get_or_404(db, account_id)
    changes = body.changes()
    _refuse_ctrader_identity_change(account, changes)
    require_firms()
    rules_changed = any(
        key in changes and not _same_value(key, changes[key], getattr(account, key))
        for key in _RULE_FIELDS
    )
    for key, value in changes.items():
        setattr(account, key, value)
    if rules_changed:
        _recompute_size(db, account_id)
    commit_account(db)
    db.refresh(account)
    logger.info("Account %s updated: %s", account.id, ", ".join(sorted(changes)) or "no fields")
    return to_schema(account, _suggestions(settings))


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
