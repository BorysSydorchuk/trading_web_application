"""cTrader connection endpoints (docs/api.md "cTrader"). Logic: `app.services.ctrader`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.accounts import commit_account, to_schema
from app.config import Settings, get_settings
from app.ctrader.errors import CtraderError
from app.db import get_db
from app.schemas import accounts as account_schemas
from app.schemas import ctrader as schemas
from app.services import ctrader as service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ctrader", tags=["ctrader"])

# The callback URL held a one-time code: never cache it or pass it on as a referrer.
_CALLBACK_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def get_deps(settings: Settings = Depends(get_settings)) -> service.CtraderDeps:
    """Dependency so tests can inject fakes (no network)."""
    return service.default_deps(settings)


@router.get("/status", response_model=schemas.CtraderStatus)
def status(
    deps: service.CtraderDeps = Depends(get_deps), db: Session = Depends(get_db)
) -> schemas.CtraderStatus:
    return service.get_status(deps, db, datetime.now(UTC))


@router.post("/connect", response_model=schemas.CtraderConnect)
def connect(deps: service.CtraderDeps = Depends(get_deps)) -> schemas.CtraderConnect:
    try:
        return schemas.CtraderConnect(authorize_url=service.start_connect(deps))
    except CtraderError as exc:
        raise service.to_api_error(exc) from None


@router.get("/callback", include_in_schema=False)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    deps: service.CtraderDeps = Depends(get_deps),
) -> RedirectResponse:
    target = service.finish_callback(deps, code, state, error)
    return RedirectResponse(target, status_code=302, headers=_CALLBACK_HEADERS)


@router.get("/accounts", response_model=schemas.CtraderAccountList)
def list_accounts(
    deps: service.CtraderDeps = Depends(get_deps), db: Session = Depends(get_db)
) -> schemas.CtraderAccountList:
    try:
        return schemas.CtraderAccountList(items=service.list_accounts(deps, db))
    except CtraderError as exc:
        raise service.to_api_error(exc) from None


@router.post("/accounts", status_code=201, response_model=account_schemas.Account)
def add_account(
    body: schemas.CtraderAccountInput,
    deps: service.CtraderDeps = Depends(get_deps),
    db: Session = Depends(get_db),
) -> account_schemas.Account:
    try:
        account = service.build_account(deps, body)
    except CtraderError as exc:
        raise service.to_api_error(exc) from None
    db.add(account)
    commit_account(db)
    db.refresh(account)
    logger.info("cTrader account %s created", account.id)
    return to_schema(account)


@router.delete("/connection", status_code=204)
def forget_connection(deps: service.CtraderDeps = Depends(get_deps)) -> Response:
    try:
        service.forget_connection(deps)
    except CtraderError as exc:
        raise service.to_api_error(exc) from None
    return Response(status_code=204)
