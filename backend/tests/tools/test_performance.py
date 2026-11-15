"""Deterministic benchmark safety/statistics tests, never timing assertions."""
from __future__ import annotations

import pytest

from app.tools.performance import summarize, validate_target


def test_nearest_rank_percentile_and_median() -> None:
    result = summarize(list(range(1, 21)))
    assert result["median_ms"] == 10.5
    assert result["p95_ms"] == 19
    assert result["n"] == 20


@pytest.mark.parametrize("name", ["trading_journal", "trading_journal_qa_m6", "trading_journal_test", "tj_m705_bad_test"])
def test_benchmark_refuses_existing_names_and_non_generated_targets(name: str) -> None:
    with pytest.raises(ValueError, match="synthetic"):
        validate_target(f"postgresql+psycopg://u:synthetic@localhost/{name}")


def test_benchmark_refuses_remote_generated_target() -> None:
    with pytest.raises(ValueError, match="synthetic"):
        validate_target("postgresql+psycopg://u:synthetic@remote/tj_m705_20261115120000_abcdef_test")


def test_generated_local_target_allowed() -> None:
    validate_target("postgresql+psycopg://u:synthetic@127.0.0.1/tj_m705_20261115120000_abcdef_test")
