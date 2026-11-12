"""pytest-xdist: each worker gets its own `<name>_<worker>_test` database (tests/conftest.py)."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from tests.conftest import SAFE_DB_NAME, worker_database_url

BASE = "postgresql+psycopg://journal:s3cret@127.0.0.1:5432/trading_journal_test"


def test_no_worker_keeps_the_base_url() -> None:
    assert worker_database_url(BASE, None) == BASE
    assert worker_database_url(BASE, "") == BASE


def test_worker_database_keeps_the_test_suffix_and_password() -> None:
    url = make_url(worker_database_url(BASE, "gw3"))
    assert url.database == "trading_journal_gw3_test"
    assert url.password == make_url(BASE).password
    assert (url.host, url.port, url.username) == ("127.0.0.1", 5432, "journal")


def test_base_without_test_suffix_still_ends_in_test() -> None:
    base = BASE.replace("trading_journal_test", "trading_journal")
    assert make_url(worker_database_url(base, "gw0")).database == "trading_journal_gw0_test"


@pytest.mark.parametrize(
    ("name", "safe"),
    [("trading_journal_gw0_test", True), ('bad"name', False), ("a;drop", False), ("", False)],
)
def test_safe_database_name(name: str, safe: bool) -> None:
    assert (SAFE_DB_NAME.fullmatch(name) is not None) is safe
