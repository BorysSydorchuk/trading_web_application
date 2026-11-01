"""HTTP API routers, mounted under `/api` in `app.main`."""

from fastapi import APIRouter

from app.api import accounts, health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(accounts.router)

__all__ = ["api_router"]
