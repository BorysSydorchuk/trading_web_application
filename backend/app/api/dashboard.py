"""GET /api/dashboard: home-page summary (docs/api.md "Dashboard API (PRD 6.10)"), its charts
(M8-14) and GET /api/home (M8-10b «Головна» rebuild)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import dashboard as schemas
from app.schemas import home as home_schemas
from app.schemas import home_charts as chart_schemas
from app.services import dashboard as service
from app.services import home, home_charts

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


@router.get("/home", response_model=home_schemas.Home)
def get_home(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
    settings: Settings = Depends(get_settings),
) -> home_schemas.Home:
    """M8-10b «Головна»: session, bias, limits, KPIs, live open positions."""
    return home.build_home(db, now, account_id, settings.data_dir)
