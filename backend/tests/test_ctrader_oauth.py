"""cTrader OAuth: state, token file, code exchange, single-use refresh across threads."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from app.config import REPO_ROOT, Settings
from app.ctrader import oauth
from app.ctrader.errors import CtraderError, CtraderErrorCode
from app.ctrader.state import OAuthStateStore
from app.ctrader.token_manager import REFRESH_MARGIN, TokenManager
from app.ctrader.tokens import TokenPair, TokenStore, tokens_path
from tests.ctrader_fakes import ACCESS_TOKEN, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _pair(access: str = ACCESS_TOKEN, refresh: str = REFRESH_TOKEN, days: int = 30) -> TokenPair:
    return TokenPair(SecretStr(access), SecretStr(refresh), NOW + timedelta(days=days), NOW)


def _token_body(access: str = "new-access", refresh: str = "new-refresh") -> dict[str, Any]:
    return {
        "accessToken": access,
        "tokenType": "bearer",
        "expiresIn": 2628000,
        "refreshToken": refresh,
        "errorCode": None,
        "description": None,
    }


class FakeHttp:
    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, method: str, url: str, params: dict[str, str]) -> dict[str, Any]:
        self.calls.append((method, url, params))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def store(tmp_path: Path) -> TokenStore:
    return TokenStore(tmp_path / "ctrader_tokens.json")


def _manager(store: TokenStore, http: Any, now: datetime = NOW) -> TokenManager:
    return TokenManager(store, CLIENT_ID, SecretStr(CLIENT_SECRET), http=http, now=lambda: now)


# --- settings ---------------------------------------------------------------------------


def test_settings_default_to_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTRADER_CLIENT_ID", raising=False)
    monkeypatch.delenv("CTRADER_CLIENT_SECRET", raising=False)
    settings = Settings(_env_file=None, database_url="postgresql://unused")
    assert settings.ctrader_client_id == ""
    assert settings.ctrader_configured is False


def test_secret_is_not_in_settings_repr() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://unused",
        ctrader_client_id=CLIENT_ID,
        ctrader_client_secret=SecretStr(CLIENT_SECRET),
    )
    assert settings.ctrader_configured is True
    assert CLIENT_SECRET not in repr(settings)


# --- authorize URL and state ------------------------------------------------------------


def test_authorize_url_has_the_view_scope_only() -> None:
    url = oauth.build_authorize_url(CLIENT_ID, "state-1")
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
    )
    assert query == {
        "client_id": [CLIENT_ID],
        "redirect_uri": ["http://localhost:8000/api/ctrader/callback"],
        "scope": ["accounts"],
        "product": ["web"],
        "state": ["state-1"],
    }
    assert "trading" not in url


def test_state_is_random_and_single_use() -> None:
    states = OAuthStateStore()
    first, second = states.issue(), states.issue()
    assert first != second
    assert len(first) >= 32
    assert states.consume(first) is True
    assert states.consume(first) is False
    assert states.consume(second) is True


def test_state_expires_after_ten_minutes() -> None:
    clock = [NOW]
    states = OAuthStateStore(now=lambda: clock[0])
    value = states.issue()
    clock[0] = NOW + timedelta(minutes=10, seconds=1)
    assert states.consume(value) is False


def test_state_is_valid_just_before_expiry() -> None:
    clock = [NOW]
    states = OAuthStateStore(now=lambda: clock[0])
    value = states.issue()
    clock[0] = NOW + timedelta(minutes=9, seconds=59)
    assert states.consume(value) is True


@pytest.mark.parametrize("bad", ["", "wrong", "stätë", "x" * 5000])
def test_wrong_state_is_refused_and_keeps_the_real_one(bad: str) -> None:
    states = OAuthStateStore()
    value = states.issue()
    assert states.consume(bad) is False
    assert states.consume(value) is True


def test_state_store_is_bounded() -> None:
    states = OAuthStateStore(max_pending=2)
    oldest = states.issue()
    states.issue()
    newest = states.issue()
    assert states.consume(oldest) is False
    assert states.consume(newest) is True


def test_state_is_consumed_once_across_threads() -> None:
    states = OAuthStateStore()
    value = states.issue()
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        results.append(states.consume(value))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1


# --- token file -------------------------------------------------------------------------


def test_token_file_path_is_git_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "data/ctrader_tokens.json"],  # noqa: S607
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_tokens_path_is_in_the_data_dir(tmp_path: Path) -> None:
    assert tokens_path(tmp_path) == tmp_path / "ctrader_tokens.json"


def test_store_roundtrip(store: TokenStore) -> None:
    assert store.read() is None
    store.write(_pair())
    loaded = store.read()
    assert loaded is not None
    assert loaded.access_token.get_secret_value() == ACCESS_TOKEN
    assert loaded.refresh_token.get_secret_value() == REFRESH_TOKEN
    assert loaded.expires_at == NOW + timedelta(days=30)
    assert loaded.expires_at.utcoffset() == timedelta(0)


def test_pair_repr_hides_tokens() -> None:
    text = repr(_pair())
    assert ACCESS_TOKEN not in text
    assert REFRESH_TOKEN not in text


def test_failed_write_keeps_the_old_file(
    store: TokenStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write(_pair())

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("app.ctrader.tokens.os.replace", boom)
    with pytest.raises(CtraderError):
        store.write(_pair("other", "other"))
    monkeypatch.undo()
    loaded = store.read()
    assert loaded is not None
    assert loaded.access_token.get_secret_value() == ACCESS_TOKEN
    assert [p.name for p in store.path.parent.iterdir() if p.suffix == ".tmp"] == []


@pytest.mark.parametrize("content", ["not json", "[]", '{"accessToken": 1}'])
def test_corrupt_file_is_token_invalid_without_its_content(store: TokenStore, content: str) -> None:
    store.path.write_text(content, encoding="utf-8")
    with pytest.raises(CtraderError) as caught:
        store.read()
    assert caught.value.code is CtraderErrorCode.TOKEN_INVALID
    assert content not in str(caught.value) or content == "[]"


def test_delete_is_idempotent(store: TokenStore) -> None:
    store.write(_pair())
    store.delete()
    store.delete()
    assert store.read() is None


# --- exchange ---------------------------------------------------------------------------


def test_exchange_sends_the_documented_get() -> None:
    http = FakeHttp(_token_body())
    pair = oauth.exchange_code("the-code", CLIENT_ID, SecretStr(CLIENT_SECRET), http=http, now=NOW)
    method, url, params = http.calls[0]
    assert method == "GET"
    assert url == "https://openapi.ctrader.com/apps/token"
    assert params == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "http://localhost:8000/api/ctrader/callback",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    assert pair.access_token.get_secret_value() == "new-access"
    assert pair.expires_at == NOW + timedelta(seconds=2628000)


@pytest.mark.parametrize(
    "body",
    [
        {"errorCode": "ACCESS_DENIED", "description": "no"},
        {**_token_body(), "accessToken": ""},
        {**_token_body(), "refreshToken": None},
        {**_token_body(), "expiresIn": 0},
        {**_token_body(), "expiresIn": "soon"},
        {**_token_body(), "expiresIn": True},
    ],
)
def test_bad_token_response_is_refused(body: dict[str, Any]) -> None:
    with pytest.raises(CtraderError) as caught:
        oauth.exchange_code("c", CLIENT_ID, SecretStr(CLIENT_SECRET), http=FakeHttp(body), now=NOW)
    assert caught.value.code in {CtraderErrorCode.TOKEN_INVALID, CtraderErrorCode.BAD_RESPONSE}


def test_token_error_text_is_masked() -> None:
    body = {"errorCode": "X", "description": f"bad {CLIENT_SECRET} and the-code"}
    with pytest.raises(CtraderError) as caught:
        oauth.exchange_code(
            "the-code", CLIENT_ID, SecretStr(CLIENT_SECRET), http=FakeHttp(body), now=NOW
        )
    assert CLIENT_SECRET not in str(caught.value)
    assert "the-code" not in str(caught.value)


# --- refresh ----------------------------------------------------------------------------


def test_fresh_token_is_returned_without_a_call(store: TokenStore) -> None:
    store.write(_pair())
    http = FakeHttp()
    assert _manager(store, http).fresh_access_token().get_secret_value() == ACCESS_TOKEN
    assert http.calls == []


def test_refresh_is_a_documented_post_and_persists_first(store: TokenStore) -> None:
    store.write(_pair(days=1))
    http = FakeHttp(_token_body())
    token = _manager(store, http).fresh_access_token()
    method, url, params = http.calls[0]
    assert (method, url) == ("POST", "https://openapi.ctrader.com/apps/token")
    assert params == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    assert token.get_secret_value() == "new-access"
    saved = store.read()
    assert saved is not None
    assert saved.refresh_token.get_secret_value() == "new-refresh"


def test_refresh_happens_proactively_inside_the_margin(store: TokenStore) -> None:
    store.write(TokenPair(SecretStr("a"), SecretStr("r"), NOW + REFRESH_MARGIN, NOW))
    http = FakeHttp(_token_body())
    _manager(store, http).fresh_access_token()
    assert len(http.calls) == 1


def test_new_pair_is_on_disk_before_it_is_returned(
    store: TokenStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.write(_pair(days=1))

    def fail(_pair: TokenPair) -> None:
        raise CtraderError(CtraderErrorCode.BAD_RESPONSE, "disk full")

    monkeypatch.setattr(store, "write", fail)
    with pytest.raises(CtraderError):
        _manager(store, FakeHttp(_token_body())).fresh_access_token()


def test_network_failure_with_a_valid_token_keeps_working(store: TokenStore) -> None:
    store.write(_pair(days=1))
    failure = CtraderError(CtraderErrorCode.CONNECTION_FAILED, "down")
    token = _manager(store, FakeHttp(failure)).fresh_access_token()
    assert token.get_secret_value() == ACCESS_TOKEN


def test_network_failure_with_an_expired_token_raises(store: TokenStore) -> None:
    store.write(_pair(days=-1))
    failure = CtraderError(CtraderErrorCode.TIMEOUT, "slow")
    with pytest.raises(CtraderError) as caught:
        _manager(store, FakeHttp(failure)).fresh_access_token()
    assert caught.value.code is CtraderErrorCode.TIMEOUT


def test_rejected_refresh_raises_and_keeps_the_stored_pair(store: TokenStore) -> None:
    store.write(_pair(days=1))
    http = FakeHttp({"errorCode": "INVALID_GRANT", "description": "used"})
    with pytest.raises(CtraderError) as caught:
        _manager(store, http).fresh_access_token()
    assert caught.value.code is CtraderErrorCode.TOKEN_INVALID
    assert store.read() is not None


def test_no_tokens_is_token_invalid(store: TokenStore) -> None:
    with pytest.raises(CtraderError) as caught:
        _manager(store, FakeHttp()).fresh_access_token()
    assert caught.value.code is CtraderErrorCode.TOKEN_INVALID


def test_concurrent_refresh_uses_the_refresh_token_once(store: TokenStore) -> None:
    """Two managers on one file stand in for the API and worker processes."""
    store.write(_pair(days=1))
    used: list[str] = []
    guard = threading.Lock()

    def http(_method: str, _url: str, params: dict[str, str]) -> dict[str, Any]:
        with guard:
            used.append(params["refresh_token"])
            number = len(used)
        return _token_body(f"access-{number}", f"refresh-{number}")

    results: list[str] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        manager = _manager(TokenStore(store.path), http)
        barrier.wait()
        results.append(manager.fresh_access_token().get_secret_value())

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert used == [REFRESH_TOKEN]
    assert results == ["access-1"] * 6


def test_lock_timeout_is_a_readable_error(store: TokenStore) -> None:
    other = TokenStore(store.path, lock_timeout_s=0.05)
    with store.lock(), pytest.raises(CtraderError) as caught, other.lock():
        pass
    assert caught.value.code is CtraderErrorCode.TIMEOUT


def test_refresh_logs_no_secret(store: TokenStore, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    store.write(_pair(days=1))
    _manager(store, FakeHttp(_token_body())).fresh_access_token()
    for secret in (ACCESS_TOKEN, REFRESH_TOKEN, CLIENT_SECRET, "new-access", "new-refresh"):
        assert secret not in caplog.text


def test_file_holds_plain_utf8_json(store: TokenStore) -> None:
    store.write(_pair())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(data) == {"access_token", "refresh_token", "expires_at", "obtained_at"}
