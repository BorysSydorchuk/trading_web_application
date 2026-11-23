"""The real token HTTP call, with the opener replaced: no request leaves the test."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest

from app.ctrader import oauth
from app.ctrader.errors import CtraderError, CtraderErrorCode
from tests.ctrader_fakes import CLIENT_SECRET

PARAMS = {"grant_type": "refresh_token", "client_secret": CLIENT_SECRET}


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    url = f"{oauth.TOKEN_URL}?client_secret={CLIENT_SECRET}"
    return urllib.error.HTTPError(url, status, "error", Message(), io.BytesIO(body))


def _patch_open(monkeypatch: pytest.MonkeyPatch, outcome: bytes | Exception) -> list[Any]:
    requests: list[Any] = []

    def fake_open(request: Any, timeout: float) -> io.BytesIO:
        requests.append((request, timeout))
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)

    monkeypatch.setattr(oauth, "_open_url", fake_open)
    return requests


def test_call_uses_method_query_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _patch_open(monkeypatch, json.dumps({"accessToken": "a"}).encode("utf-8"))
    assert oauth.call_token_endpoint("POST", oauth.TOKEN_URL, PARAMS) == {"accessToken": "a"}
    request, timeout = requests[0]
    assert request.get_method() == "POST"
    assert request.full_url.startswith(f"{oauth.TOKEN_URL}?grant_type=refresh_token")
    assert timeout == oauth.HTTP_TIMEOUT_S


def test_json_error_body_reaches_the_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"errorCode": "INVALID", "description": "no"}).encode("utf-8")
    _patch_open(monkeypatch, _http_error(400, body))
    assert oauth.call_token_endpoint("GET", oauth.TOKEN_URL, PARAMS)["errorCode"] == "INVALID"


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (_http_error(500, b"<html>"), CtraderErrorCode.CONNECTION_FAILED),
        (_http_error(401, b"<html>"), CtraderErrorCode.TOKEN_INVALID),
        (urllib.error.URLError("no route"), CtraderErrorCode.CONNECTION_FAILED),
        (urllib.error.URLError(TimeoutError()), CtraderErrorCode.TIMEOUT),
        (TimeoutError(), CtraderErrorCode.TIMEOUT),
        (b"not json", CtraderErrorCode.BAD_RESPONSE),
        (b"[]", CtraderErrorCode.BAD_RESPONSE),
    ],
)
def test_failures_are_typed_and_hold_no_secret(
    monkeypatch: pytest.MonkeyPatch, outcome: bytes | Exception, expected: CtraderErrorCode
) -> None:
    _patch_open(monkeypatch, outcome)
    with pytest.raises(CtraderError) as caught:
        oauth.call_token_endpoint("GET", oauth.TOKEN_URL, PARAMS)
    assert caught.value.code is expected
    assert CLIENT_SECRET not in str(caught.value)
    assert caught.value.__cause__ is None
    # Nothing chained may carry the URL, which holds the client secret.
    assert caught.value.__context__ is None or caught.value.__suppress_context__


def test_redirects_are_refused() -> None:
    """A redirect would resend the client secret in the query to another host."""
    handler: Any = oauth._NoRedirect()
    request = urllib.request.Request(oauth.TOKEN_URL)  # noqa: S310 - never opened
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://x") is None
