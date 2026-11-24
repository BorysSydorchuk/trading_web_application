"""Browser boundary for the unauthenticated loopback application (not user auth)."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_response

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# cTrader's consent page sends the browser back here: a cross-site top-level navigation.
_OAUTH_CALLBACK_PATH = "/api/ctrader/callback"
SECURITY_HEADERS = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
)


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        if any(c.isspace() or ord(c) < 32 for c in value):
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in LOCAL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            return None
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None


def _is_oauth_return(scope: Scope, headers: Headers) -> bool:
    """Only a top-level GET of the callback (never a frame, fetch or other method). The
    endpoint itself rejects anything without the single-use OAuth state."""
    return (
        scope["method"] == "GET"
        and scope["path"] == _OAUTH_CALLBACK_PATH
        and headers.getlist("sec-fetch-mode") == ["navigate"]
        and headers.getlist("sec-fetch-dest") == ["document"]
    )


def _allowed(scope: Scope) -> bool:
    headers = Headers(scope=scope)
    hosts = headers.getlist("host")
    origins = headers.getlist("origin")
    sites = headers.getlist("sec-fetch-site")
    if len(hosts) != 1 or len(origins) > 1 or len(sites) > 1:
        return False
    # Vite preserves the browser Host through its relative /api proxy. Do not use
    # untrusted X-Forwarded-Host/For to decide whether a browser is local.
    target = _origin(f"{scope['scheme']}://{hosts[0]}")
    if target is None or (origins and _origin(origins[0]) != target):
        return False
    if not sites or sites[0] in {"same-origin", "same-site", "none"}:
        return True
    return _is_oauth_return(scope, headers)


class LocalBoundaryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def guarded_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in {key for key, _ in SECURITY_HEADERS}
                ]
                message = {**message, "headers": [*existing, *SECURITY_HEADERS]}
            await send(message)

        if not _allowed(scope):
            # Never reflect attacker-controlled Host/Origin or credential-like input.
            response = error_response(403, "forbidden", "Local same-origin requests only")
            await response(scope, receive, guarded_send)
            return
        await self.app(scope, receive, guarded_send)
