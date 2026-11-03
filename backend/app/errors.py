"""Uniform JSON error envelope: `{"error": {"code", "message", "details"}}` (docs/api.md)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.domain.terminal_path import PROGRAM_FILES_CODE

logger = logging.getLogger(__name__)

_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    503: "service_unavailable",
}

_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}

# Validation error types the UI may map to its own text (422 `details.field_codes`).
# Other (pydantic) types are not part of the contract and are not exposed.
FIELD_ERROR_CODES: frozenset[str] = frozenset({PROGRAM_FILES_CODE})


class ApiError(Exception):
    """Raise from endpoints/services for a specific error code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content=error_body(code, message, details), headers=headers
    )


def _field_key(loc: tuple[int | str, ...]) -> str:
    parts = list(loc)
    if len(parts) > 1 and parts[0] in _LOCATION_PREFIXES:
        parts = parts[1:]
    return ".".join(str(p) for p in parts)


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # registered for ApiError only
        raise exc
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    fields: dict[str, str] = {}
    field_codes: dict[str, str] = {}
    for err in exc.errors():
        key = _field_key(tuple(err.get("loc", ())))
        if key in fields:
            continue
        fields[key] = str(err.get("msg", "invalid"))
        if err.get("type") in FIELD_ERROR_CODES:
            field_codes[key] = str(err["type"])
    details: dict[str, Any] = {"fields": fields}
    if field_codes:
        details["field_codes"] = field_codes
    return error_response(422, "validation_error", "Request validation failed", details)


async def _db_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    orig = getattr(exc, "orig", None)
    logger.error(
        "DB unavailable on %s %s: %s",
        request.method,
        request.url.path,
        type(orig).__name__ if orig is not None else type(exc).__name__,
    )
    return error_response(503, "db_unavailable", "Database is not reachable")


class UnhandledErrorMiddleware:
    """Turns any uncaught exception into a logged 500 `internal_error` JSON response.

    Pure ASGI middleware placed inside Starlette's ServerErrorMiddleware, so the
    traceback is logged once by us and no HTML error page is ever returned.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "Unhandled error on %s %s", scope.get("method", "?"), scope.get("path", "?")
            )
            if response_started:
                raise
            response = error_response(500, "internal_error", "Internal server error")
            await response(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(OperationalError, _db_unavailable_handler)
    app.add_middleware(UnhandledErrorMiddleware)
