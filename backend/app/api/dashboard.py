"""GET /api/dashboard: home-page summary (docs/api.md "Dashboard API (PRD 6.10)")."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import get_db
from app.schemas import dashboard as schemas
from app.services import dashboard as service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.Dashboard)
def get_dashboard(
    db: Session = Depends(get_db), now: datetime = Depends(utc_now)
) -> schemas.Dashboard:
    return service.build_dashboard(db, now)
