"""cTrader OAuth over HTTPS (standard library: httpx is only a dev dependency here).

Neither the code exchange nor the refresh is retried: both credentials are single use.
Redirects are refused, because these URLs carry the client secret in the query string.
"""

from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlencode

from pydantic import SecretStr

from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.tokens import TokenPair
from app.mt5.errors import mask_secrets

logger = logging.getLogger(__name__)

AUTHORIZE_URL: Final = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL: Final = "https://openapi.ctrader.com/apps/token"  # noqa: S105 - URL
REDIRECT_URI: Final = "http://localhost:8000/api/ctrader/callback"
# Read-only consent. The other documented scope is never requested.
SCOPE: Final = "accounts"
PRODUCT: Final = "web"
HTTP_TIMEOUT_S: Final = 15.0
_MAX_BODY: Final = 64 * 1024
_MAX_DESCRIPTION: Final = 200

TokenHttp = Callable[[str, str, dict[str, str]], dict[str, Any]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_open_url: Final = urllib.request.build_opener(_NoRedirect).open


def build_authorize_url(client_id: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "product": PRODUCT,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _json_body(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except ValueError:
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "token answer is not JSON") from None
    if not isinstance(data, dict):
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "token answer is not an object")
    return data


def _from_http_error(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """A JSON error body goes to the normal parsing; otherwise a code from the status."""
    status = exc.code
    try:
        with exc:
            raw = exc.read(_MAX_BODY)
    except (OSError, http.client.HTTPException):
        raw = b""
    try:
        return _json_body(raw)
    except CtraderError:
        kind = (
            CtraderErrorCode.CONNECTION_FAILED if status >= 500 else CtraderErrorCode.TOKEN_INVALID
        )
        raise CtraderError(kind, f"token endpoint answered HTTP {status}") from None


def call_token_endpoint(method: str, url: str, params: dict[str, str]) -> dict[str, Any]:
    """The real HTTP call. Exceptions never carry the URL: it holds the client secret."""
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        f"{url}?{urlencode(params)}",
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with _open_url(request, timeout=HTTP_TIMEOUT_S) as response:
            return _json_body(response.read(_MAX_BODY))
    except urllib.error.HTTPError as exc:
        return _from_http_error(exc)
    except TimeoutError:
        raise CtraderError(CtraderErrorCode.TIMEOUT, "token endpoint timed out") from None
    except OSError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise CtraderError(CtraderErrorCode.TIMEOUT, "token endpoint timed out") from None
        raise CtraderError(
            CtraderErrorCode.CONNECTION_FAILED,
            f"token endpoint unreachable: {type(exc).__name__}",
        ) from None
    except http.client.HTTPException as exc:  # e.g. a truncated answer
        raise CtraderError(
            CtraderErrorCode.CONNECTION_FAILED,
            f"token endpoint broke the answer: {type(exc).__name__}",
        ) from None


def _parse_tokens(body: dict[str, Any], now: datetime, secrets: Iterable[str]) -> TokenPair:
    error = body.get("errorCode")
    if error:
        described = str(body.get("description") or "no description")
        text = mask_secrets(described, secrets)[:_MAX_DESCRIPTION]
        raise CtraderError(
            CtraderErrorCode.TOKEN_INVALID, f"cTrader refused: {error}: {text}", secrets=secrets
        )
    access, refresh, expires = (
        body.get("accessToken"),
        body.get("refreshToken"),
        body.get("expiresIn"),
    )
    valid_tokens = isinstance(access, str) and access and isinstance(refresh, str) and refresh
    if not valid_tokens or type(expires) is not int or expires <= 0:
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "token answer is incomplete")
    return TokenPair(
        SecretStr(str(access)), SecretStr(str(refresh)), now + timedelta(seconds=expires), now
    )


def exchange_code(
    code: str,
    client_id: str,
    client_secret: SecretStr,
    *,
    http: TokenHttp = call_token_endpoint,
    now: datetime | None = None,
) -> TokenPair:
    """Authorization code -> tokens. The code lives one minute: call this at once."""
    secret = client_secret.get_secret_value()
    body = http(
        "GET",
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": secret,
        },
    )
    return _parse_tokens(body, now or datetime.now(UTC), (secret, code))


def refresh_tokens(
    refresh_token: SecretStr,
    client_id: str,
    client_secret: SecretStr,
    *,
    http: TokenHttp = call_token_endpoint,
    now: datetime | None = None,
) -> TokenPair:
    """POST per the docs' example. The old pair dies at once: persist the result first."""
    secret, old = client_secret.get_secret_value(), refresh_token.get_secret_value()
    body = http(
        "POST",
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": old,
            "client_id": client_id,
            "client_secret": secret,
        },
    )
    return _parse_tokens(body, now or datetime.now(UTC), (secret, old))
