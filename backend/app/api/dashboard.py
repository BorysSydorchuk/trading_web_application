"""GET /api/dashboard: home-page summary (docs/api.md "Dashboard API (PRD 6.10)")."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import get_db
from app.schemas import dashboard as schemas
from app.schemas import home_charts as chart_schemas
from app.services import dashboard as service
from app.services import home_charts

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.Dashboard)
def get_dashboard(
    db: Session = Depends(get_db), now: datetime = Depends(utc_now)
) -> schemas.Dashboard:
    return service.build_dashboard(db, now)


@router.get(
    "/dashboard/charts", response_model=chart_schemas.HomeCharts, response_model_by_alias=True
)
def get_home_charts(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> chart_schemas.HomeCharts:
    """M8-14 Home charts for Brussels dates from..to (docs/api.md "M8-14")."""
    return home_charts.build(db, date_from, date_to, account_id)
