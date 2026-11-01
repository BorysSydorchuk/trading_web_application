"""FastAPI application. Run: `uv run uvicorn app.main:app` from `backend/`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import api_router
from app.api.health import app_version
from app.config import Settings, get_settings
from app.config_files import check_config_files
from app.db import dispose_engine
from app.errors import install_error_handlers
from app.logging_setup import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("API starting, version %s", app_version())
    check_config_files()  # broken YAML is logged loudly; endpoints return config_error
    yield
    dispose_engine()
    logger.info("API stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    log_path = setup_logging("api.log", settings)
    logger.debug("Logging to %s", log_path)

    app = FastAPI(
        title="Trading Journal API",
        version=app_version(),
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
