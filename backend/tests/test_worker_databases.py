"""pytest-xdist: each worker gets its own `<name>_<worker>_test` database (tests/conftest.py)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import make_url

from tests.conftest import SAFE_DB_NAME, run_stamp, stale_worker_databases, worker_database_url

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


NOW = datetime(2026, 11, 19, 22, 0, tzinfo=UTC)


def test_run_stamp_of_one_off_and_fixed_names() -> None:
    assert run_stamp("tj_m705_20261115194506_33f314_gw3_test") == datetime(
        2026, 11, 15, 19, 45, 6, tzinfo=UTC
    )
    assert run_stamp("trading_journal_gw3_test") is None
    assert run_stamp("tj_x_20261399999999_ab_gw0_test") is None  # not a real time


def test_stale_worker_databases_only_old_one_off_worker_copies() -> None:
    names = [
        "tj_m705_20261115194506_33f314_gw3_test",  # 4 days old worker copy -> stale
        "tj_m705_20261119210000_aaaaaa_gw0_test",  # 1 h old, maybe a running QA run -> kept
        "tj_m705_20261115194506_33f314_test",  # the one-off base itself -> kept
        "trading_journal_gw3_test",  # fixed gate name -> kept
        "trading_journal_test",
        "trading_journal",
        "trading_journal_qa_m3",
        "tj_backup_restore_20261114203923_test",  # not a worker copy -> kept
    ]
    assert stale_worker_databases(names, NOW) == ["tj_m705_20261115194506_33f314_gw3_test"]


def test_stale_after_is_24_hours() -> None:
    just_under = "tj_q_20261118220100_ab_gw1_test"
    just_over = "tj_q_20261118215900_ab_gw1_test"
    assert stale_worker_databases([just_under, just_over], NOW) == [just_over]
