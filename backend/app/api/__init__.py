"""HTTP API routers, mounted under `/api` in `app.main`."""

from fastapi import APIRouter

from app.api import (
    accounts,
    ai,
    audio,
    backups,
    bias,
    calculator,
    config_files,
    ctrader,
    dashboard,
    digests,
    health,
    journal_options,
    sync_status,
    system,
    trades,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(backups.router)
api_router.include_router(accounts.router)
api_router.include_router(ctrader.router)
api_router.include_router(config_files.router)
api_router.include_router(journal_options.router)
api_router.include_router(sync_status.router)
api_router.include_router(trades.router)
api_router.include_router(ai.router)
api_router.include_router(audio.router)
api_router.include_router(bias.router)
api_router.include_router(calculator.router)
api_router.include_router(dashboard.router)
api_router.include_router(digests.router)
api_router.include_router(system.router)

__all__ = ["api_router"]
