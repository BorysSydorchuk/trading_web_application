"""M8-04..M8-08 dry-run tool (app.tools.taxonomy_dry_run, docs/api.md "Migration" Dry run).

Pure functions only: the report over counts and the scratch-database guard. No test connects
to a database; the dev database `trading_journal` is never touched.

Assumed API (the contract names only the module and the `*_taxdry_test` scratch name):
- `report(counts) -> list[str]`: counts = {mapping: {counter: int}}, one line per mapping
- `scratch_database_name(source_db) -> str`
- `assert_safe_scratch(source_db, scratch_db) -> None`, raises ValueError
"""

from __future__ import annotations

import pytest

from app.tools.taxonomy_dry_run import assert_safe_scratch, report, scratch_database_name

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
