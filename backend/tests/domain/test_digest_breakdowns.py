"""M8-04..08 merge B: journal breakdowns with multi fields, show_if coverage, the POI
combination and the H1 x H4 matrix (docs/api.md "Merge B exact shapes").

Module: ``app/domain/digest_breakdowns.py`` (pure, Decimal).
- ``JournalSpec(key, multi=False, options=(), show_if=None)``; ``ShowIfSpec(field, includes)``.
- ``field_breakdown(trades, spec)``: kind ``field``; a multi field puts a trade in each value
  (empty -> None group); coverage.total = trades where the field applies (show_if parent equals
  / contains the option), filled = those with a value; hidden trades are in no group.
- ``combination_breakdown(trades, spec)``: kind ``combination``, field ``<key>__combo``; key =
  values in option order joined `` + ``; empty -> None.
- ``matrix_breakdown(trades, row, col)``: kind ``matrix``, field ``<row>__x__<col>``; key =
  ``(row value, col value)``; filled = trades with both set.
- ``journal_breakdowns(trades, specs, combinations=(), matrices=())``: file order, a
  combination right after its field, a matrix right after the later of its two fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.domain.digest_breakdowns import (
    JournalSpec,
    ShowIfSpec,
    combination_breakdown,
    field_breakdown,
    journal_breakdowns,
    matrix_breakdown,
)
from app.domain.digest_metrics import DigestTrade

D = Decimal
POI_OPTIONS = ("fvg_h4", "fvg_h1", "fractal_h1", "fractal_h4", "other")
CONTEXTS = ("flow", "reversal", "range", "other")
POI = JournalSpec("poi_types", multi=True, options=POI_OPTIONS)
FVG_H1 = JournalSpec(
    "fvg_types_h1",
    multi=True,
    options=("fractal_updating", "post_manipulation", "other"),
    show_if=ShowIfSpec("poi_types", "fvg_h1"),
)
H1 = JournalSpec("h1_context", options=CONTEXTS)
H4 = JournalSpec("h4_context", options=CONTEXTS)


def tr(tid: int, pnl: str, r: str | None, **journal: Any) -> DigestTrade:
    return DigestTrade(
        id=tid,
        account_id=1,
        symbol="GER40",
        close_time=datetime(2026, 11, 10, 9, tid, tzinfo=UTC),
        net_pnl=D(pnl),
        r_multiple=None if r is None else D(r),
        journal=journal,
    )


def trades() -> list[DigestTrade]:
    return [
        tr(1, "100", "1", poi_types=("fvg_h1", "fractal_h4"), fvg_types_h1=("post_manipulation",),
           h1_context="flow", h4_context="flow"),
        tr(2, "-50", "-1", poi_types=("fractal_h4",), h1_context="flow", h4_context="reversal"),
        tr(3, "30", "0.5", poi_types=("fractal_h4", "fvg_h1"), fvg_types_h1=None,
           h1_context="flow", h4_context="flow"),
        tr(4, "10", None, h1_context="range"),
    ]  # fmt: skip


def test_multi_field_counts_a_trade_in_each_of_its_values() -> None:
    # Arrange
    items = trades()

    # Act
    b = field_breakdown(items, POI)

    # Assert
    assert b.kind == "field"
    by_key = {g.key: g for g in b.groups}
    assert list(by_key) == ["fractal_h4", "fvg_h1", None]
    assert (by_key["fractal_h4"].trades, by_key["fractal_h4"].net_pnl) == (3, D("80"))
    assert (by_key["fvg_h1"].trades, by_key["fvg_h1"].total_r) == (2, D("1.5"))
    assert by_key["fvg_h1"].win_rate == D(100)
    assert (by_key[None].trades, by_key[None].net_pnl) == (1, D("10"))
    assert (b.filled, b.total) == (3, 4)


def test_show_if_field_covers_only_trades_whose_parent_includes_the_option() -> None:
    # Arrange: t1 and t3 have POI fvg_h1, t3 left the FVG type empty

    # Act
    b = field_breakdown(trades(), FVG_H1)

    # Assert
    assert [(g.key, g.trades) for g in b.groups] == [("post_manipulation", 1), (None, 1)]
    assert (b.filled, b.total) == (1, 2)


def test_show_if_on_an_enum_parent_uses_equality() -> None:
    # Arrange
    spec = JournalSpec("h1_context_detail", show_if=ShowIfSpec("h1_context", "range"))
    items = [tr(1, "5", "1", h1_context="range", h1_context_detail="x"), tr(2, "5", "1")]

    # Act
    b = field_breakdown(items, spec)

    # Assert
    assert [(g.key, g.trades) for g in b.groups] == [("x", 1)]
    assert (b.filled, b.total) == (1, 1)


def test_scalar_field_breakdown_keeps_the_old_shape() -> None:
    b = field_breakdown(trades(), H1)

    assert [(g.key, g.trades) for g in b.groups] == [("flow", 3), ("range", 1)]
    assert (b.filled, b.total) == (4, 4)


def test_combination_joins_values_in_option_order() -> None:
    # Arrange: t1 and t3 chose the same pair in a different order

    # Act
    b = combination_breakdown(trades(), POI)

    # Assert
    assert (b.kind, b.field) == ("combination", "poi_types__combo")
    assert [(g.key, g.trades) for g in b.groups] == [
        ("fvg_h1 + fractal_h4", 2),
        ("fractal_h4", 1),
        (None, 1),
    ]
    assert b.groups[0].net_pnl == D("130")
    assert (b.filled, b.total) == (3, 4)


def test_matrix_groups_by_both_values_with_list_keys() -> None:
    # Act
    b = matrix_breakdown(trades(), H1, H4)

    # Assert
    assert (b.kind, b.field) == ("matrix", "h1_context__x__h4_context")
    assert [(g.key, g.trades) for g in b.groups] == [
        (("flow", "flow"), 2),
        (("flow", "reversal"), 1),
        (("range", None), 1),
    ]
    flow_flow = b.groups[0]
    assert (flow_flow.net_pnl, flow_flow.total_r) == (D("130"), D("1.5"))
    assert flow_flow.win_rate == D(100)
    assert (b.filled, b.total) == (3, 4)


def test_journal_breakdowns_place_combination_and_matrix_in_file_order() -> None:
    # Act
    result = journal_breakdowns(
        trades(),
        (H1, H4, POI, FVG_H1),
        combinations=("poi_types",),
        matrices=(("h1_context", "h4_context"),),
    )

    # Assert
    assert list(result) == [
        "h1_context",
        "h4_context",
        "h1_context__x__h4_context",
        "poi_types",
        "poi_types__combo",
        "fvg_types_h1",
    ]


def test_journal_breakdowns_skip_a_combination_or_matrix_of_unknown_fields() -> None:
    result = journal_breakdowns(
        trades(), (H1,), combinations=("poi_types",), matrices=(("h1_context", "h4_context"),)
    )

    assert list(result) == ["h1_context"]


def test_empty_period_gives_empty_groups_and_zero_coverage() -> None:
    b = matrix_breakdown([], H1, H4)

    assert (b.groups, b.filled, b.total) == ((), 0, 0)
