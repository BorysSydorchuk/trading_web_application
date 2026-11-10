"""Position-size calculator (docs/api.md M5-04c/d, PRD 6.8). The API never touches MT5."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import calculator as schemas
from app.services import calculator as service
from app.services import margin_requests

router = APIRouter(tags=["calculator"])


@router.get("/accounts/{account_id}/symbol-specs", response_model=schemas.SymbolSpecList)
def list_symbol_specs(account_id: int, db: Session = Depends(get_db)) -> schemas.SymbolSpecList:
    return service.list_symbol_specs(db, account_id)


@router.post("/calculator/calculate", response_model=schemas.CalculateResult)
def calculate(
    body: schemas.CalculateInput, db: Session = Depends(get_db)
) -> schemas.CalculateResult:
    return service.calculate(db, body)


@router.post(
    "/calculator/margin-requests",
    response_model=schemas.MarginRequestItem,
    status_code=202,
)
def create_margin_request(
    body: schemas.CalculateInput, db: Session = Depends(get_db)
) -> schemas.MarginRequestItem:
    """Queue a live MT5 margin lookup for the worker (same input and sizing as calculate)."""
    return margin_requests.create(db, body)


@router.get("/calculator/margin-requests/{request_id}", response_model=schemas.MarginRequestItem)
def get_margin_request(request_id: int, db: Session = Depends(get_db)) -> schemas.MarginRequestItem:
    return margin_requests.get(db, request_id)
