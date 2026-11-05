"""HTTP API routers, mounted under `/api` in `app.main`."""

from fastapi import APIRouter

from app.api import accounts, ai, audio, bias, config_files, health, sync_status, trades

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(accounts.router)
api_router.include_router(config_files.router)
api_router.include_router(sync_status.router)
api_router.include_router(trades.router)
api_router.include_router(ai.router)
api_router.include_router(audio.router)
api_router.include_router(bias.router)

__all__ = ["api_router"]
