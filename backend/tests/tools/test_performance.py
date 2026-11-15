"""Deterministic benchmark safety/statistics tests, never timing assertions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.tools.performance import summarize, validate_target


def test_threshold_records_every_breach_not_just_percentile() -> None:
    from app.tools.performance import threshold_summary

    result = threshold_summary([100.0] * 19 + [301.0], 300)
    assert result["p95_ms"] == 100
    assert result["breaches"] == 1
    assert result["target_ms"] == 300


def test_nearest_rank_percentile_and_median() -> None:
    result = summarize(list(range(1, 21)))
    assert result["median_ms"] == 10.5
    assert result["p95_ms"] == 19
    assert result["n"] == 20


@pytest.mark.parametrize(
    "name", ["trading_journal", "trading_journal_qa_m6", "trading_journal_test", "tj_m705_bad_test"]
)
def test_benchmark_refuses_existing_names_and_non_generated_targets(name: str) -> None:
    with pytest.raises(ValueError, match="synthetic"):
        validate_target(f"postgresql+psycopg://u:synthetic@localhost/{name}")


def test_benchmark_refuses_remote_generated_target() -> None:
    with pytest.raises(ValueError, match="synthetic"):
        validate_target(
            "postgresql+psycopg://u:synthetic@remote/tj_m705_20261115120000_abcdef_test"
        )


def test_generated_local_target_allowed() -> None:
    validate_target("postgresql+psycopg://u:synthetic@127.0.0.1/tj_m705_20261115120000_abcdef_test")


def test_existing_generated_database_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.performance import create_dataset

    monkeypatch.setattr(
        "app.tools.performance.get_settings",
        Mock(
            return_value=SimpleNamespace(
                test_database_url="postgresql+psycopg://u:synthetic@localhost/trading_journal_test"
            )
        ),
    )
    engine = MagicMock()
    conn = engine.connect.return_value.__enter__.return_value
    conn.scalar.side_effect = ["trading_journal_test", 1]
    monkeypatch.setattr("app.tools.performance.create_engine", Mock(return_value=engine))
    with pytest.raises(ValueError, match="existing database"):
        create_dataset(tmp_path)
    conn.execute.assert_not_called()
    engine.dispose.assert_called_once()
