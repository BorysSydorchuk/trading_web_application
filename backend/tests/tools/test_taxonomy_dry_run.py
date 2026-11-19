"""M8-04..M8-08 dry-run tool (app.tools.taxonomy_dry_run, docs/api.md "Migration" Dry run).

Pure functions only: the report over counts and the scratch-database guard. No test connects
to a database; the dev database `trading_journal` is never touched.

Assumed API (the contract names only the module and the `*_taxdry_test` scratch name):
- `report(counts) -> list[str]`: counts = {mapping: {counter: int}}, one line per mapping
- `scratch_database_name(source_db) -> str`
- `assert_safe_scratch(source_db, scratch_db) -> None`, raises ValueError
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import cast

import pytest

from app.config import Settings
from app.tools import taxonomy_dry_run as dry
from app.tools.taxonomy_dry_run import (
    after_counts,
    assert_safe_scratch,
    report,
    scratch_database_name,
)

COUNTS = {
    "setup_context": {"mapped": 8, "legacy": 3},
    "poi_type": {"mapped": 14, "legacy": 0},
    "fvg_kind": {"mapped": 6, "legacy": 5},
    "violations": {"remapped": 7, "merged": 2},
}


# --- report ---


def test_report_has_one_line_per_mapping_in_input_order() -> None:
    lines = report(COUNTS)

    assert len(lines) == 4
    assert [line.split()[0].rstrip(":") for line in lines] == list(COUNTS)


def test_report_lines_carry_the_numbers() -> None:
    lines = report(COUNTS)

    for line, counters in zip(lines, COUNTS.values(), strict=True):
        for name, number in counters.items():
            assert name in line
            assert str(number) in line


def test_report_shows_zero_counts() -> None:
    lines = report({"poi_type": {"mapped": 0, "legacy": 0}})

    assert len(lines) == 1
    assert "0" in lines[0]


def test_report_of_nothing_is_empty() -> None:
    assert report({}) == []


def test_report_does_not_change_its_input() -> None:
    before = {k: dict(v) for k, v in COUNTS.items()}

    report(COUNTS)

    assert before == COUNTS


def test_report_is_deterministic() -> None:
    assert report(COUNTS) == report(COUNTS)


# --- scratch database guard ---


def test_scratch_name_is_derived_from_the_source() -> None:
    name = scratch_database_name("trading_journal")

    assert name == "trading_journal_taxdry_test"
    assert_safe_scratch("trading_journal", name)


def test_scratch_name_always_ends_with_test_and_differs_from_the_source() -> None:
    for source in ("trading_journal", "other_db", "x"):
        name = scratch_database_name(source)
        assert name.endswith("_test")
        assert name != source


@pytest.mark.parametrize(
    ("source", "scratch"),
    [
        ("trading_journal", "trading_journal"),  # the dev DB itself
        ("trading_journal", "trading_journal_taxdry"),  # no _test suffix
        ("trading_journal_test", "trading_journal_test"),  # same as the source
        ("trading_journal", ""),
    ],
)
def test_guard_refuses_unsafe_scratch_names(source: str, scratch: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        assert_safe_scratch(source, scratch)


@pytest.mark.parametrize(
    "scratch", ['bad"; DROP DATABASE x; --_test', "with space_test", "semi;colon_test"]
)
def test_guard_refuses_names_that_are_not_plain_identifiers(scratch: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        assert_safe_scratch("trading_journal", scratch)


def test_guard_is_case_sensitive_about_the_suffix() -> None:
    with pytest.raises(ValueError, match=r".+"):
        assert_safe_scratch("trading_journal", "trading_journal_taxdry_TEST")


# --- counts from the before / after measurements (added in GREEN) ---


def test_counts_from_before_and_after() -> None:
    from app.tools.taxonomy_dry_run import counts_from

    before = {"setup_context": 11, "poi_type": 14, "fvg_kind": 11, "violations": 9}
    after = {"setup_context": 3, "poi_type": 0, "fvg_kind": 5, "violations": 7}

    assert counts_from(before, after) == {
        "setup_context": {"mapped": 8, "legacy": 3},
        "poi_type": {"mapped": 14, "legacy": 0},
        "fvg_kind": {"mapped": 6, "legacy": 5},
        "violations": {"remapped": 9, "merged": 2},
    }


def test_guard_requires_exactly_the_derived_scratch_name() -> None:
    with pytest.raises(ValueError, match="exactly"):
        assert_safe_scratch("trading_journal", "other_db_taxdry_test")
    with pytest.raises(ValueError, match="exactly"):
        assert_safe_scratch("trading_journal", "trading_journal_x_test")


# --- after-upgrade counts of the new columns (database-reviewer LOW 7) ---

NEW = {
    "h1_filled": 9,
    "h1_flow": 8,
    "h4_filled": 9,
    "h4_flow": 8,
    "poi_filled": 14,
    "fvg_h1_filled": 4,
    "fvg_h4_filled": 2,
    "entry_model_other": 1,
    "legacy_setup_context": 3,
    "legacy_fvg_kind": 5,
    "daily_risk": 6,
    "weekly_risk": 1,
}


def test_after_counts_report_lines() -> None:
    lines = report(after_counts(NEW, {2: 3, 1: 11}))

    assert lines == [
        "h1_context: filled=9, flow=8",
        "h4_context: filled=9, flow=8",
        "poi_types: filled=14, len_1=11, len_2=3",
        "fvg_types_h1: filled=4",
        "fvg_types_h4: filled=2",
        "entry_model_other: filled=1",
        "legacy_kept: setup_context=3, fvg_kind=5",
        "risk_violations: daily_risk=6, weekly_risk=1",
    ]


def test_after_counts_without_poi_values() -> None:
    lines = report(after_counts(NEW | {"poi_filled": 0}, {}))

    assert "poi_types: filled=0" in lines


# --- exit code when the scratch DB cannot be dropped (database-reviewer LOW 6) ---

FAKE_URL = "postgresql+psycopg://user:secret@localhost:5432/trading_journal"


def _settings() -> Settings:
    return cast(Settings, SimpleNamespace(database_url=FAKE_URL, postgres_port=5432))


def _no_db(monkeypatch: pytest.MonkeyPatch, *, run_fails: bool, drop_fails: bool) -> list[str]:
    calls: list[str] = []

    def create(url: str, source: str, scratch: str) -> None:
        calls.append(f"create {scratch}")

    def run(settings: object, target: object, scratch: str, out: object) -> None:
        calls.append("run")
        if run_fails:
            raise RuntimeError("upgrade failed")

    def drop(url: str, source: str, scratch: str) -> None:
        calls.append(f"drop {scratch}")
        if drop_fails:
            raise RuntimeError("database is being accessed by other users")

    monkeypatch.setattr(dry, "create_scratch", create)
    monkeypatch.setattr(dry, "_run_on_scratch", run)
    monkeypatch.setattr(dry, "drop_scratch", drop)
    return calls


def test_clean_run_returns_zero_and_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _no_db(monkeypatch, run_fails=False, drop_fails=False)
    out, err = io.StringIO(), io.StringIO()

    assert dry.dry_run(_settings(), out, err) == 0
    assert calls[-1] == "drop trading_journal_taxdry_test"
    assert err.getvalue() == ""


def test_failed_drop_is_a_non_zero_exit_naming_the_leftover_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_db(monkeypatch, run_fails=False, drop_fails=True)
    out, err = io.StringIO(), io.StringIO()

    assert dry.dry_run(_settings(), out, err) == 1
    assert "trading_journal_taxdry_test" in err.getvalue()
    assert "Готово" not in out.getvalue()


def test_failed_run_still_drops_and_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _no_db(monkeypatch, run_fails=True, drop_fails=False)
    out, err = io.StringIO(), io.StringIO()

    assert dry.dry_run(_settings(), out, err) == 1
    assert calls[-1] == "drop trading_journal_taxdry_test"
    assert "secret" not in err.getvalue() + out.getvalue()
    # review 2026-11-19: only the exception class and the log file, never its text
    assert "RuntimeError" in err.getvalue()
    assert "upgrade failed" not in err.getvalue()
    assert "logs/taxonomy_dry_run.log" in err.getvalue()
