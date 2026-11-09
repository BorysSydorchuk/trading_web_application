"""Position-size calculator (docs/api.md M5-04c, PRD 6.8). Read-only: no MT5, no orders."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import calculator as schemas
from app.services import calculator as service

router = APIRouter(tags=["calculator"])


@router.get("/accounts/{account_id}/symbol-specs", response_model=schemas.SymbolSpecList)
def list_symbol_specs(account_id: int, db: Session = Depends(get_db)) -> schemas.SymbolSpecList:
    return service.list_symbol_specs(db, account_id)


@router.post("/calculator/calculate", response_model=schemas.CalculateResult)
def calculate(
    body: schemas.CalculateInput, db: Session = Depends(get_db)
) -> schemas.CalculateResult:
    return service.calculate(db, body)
