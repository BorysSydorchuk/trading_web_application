"""Journal-field digest breakdowns (M8-04..08 merge B, docs/api.md "Merge B exact shapes").

Pure: no DB, no I/O, Decimal via ``digest_metrics.group_stats``. Three kinds:
- ``field``: one group per value; a multi field puts a trade in each of its values (empty ->
  the None group). Coverage total = trades where the field applies (a ``show_if`` field only
  where the parent equals / contains the option); hidden trades are in no group.
- ``combination`` (``<key>__combo``): one group per distinct selection of a multi field, key =
  the values in option order joined `` + ``; empty -> None.
- ``matrix`` (``<row>__x__<col>``): one group per (row value, column value) pair; filled =
  trades with both values set.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from app.domain import digest_metrics as dm

COMBO_SUFFIX = "__combo"
MATRIX_SEPARATOR = "__x__"
COMBO_JOINER = " + "


@dataclass(frozen=True)
class ShowIfSpec:
    field: str
    includes: str


@dataclass(frozen=True)
class JournalSpec:
    """One analytics journal field as the digest needs it (from journal_fields.yaml)."""

    key: str
    multi: bool = False
    options: tuple[str, ...] = ()  # option values in YAML order
    show_if: ShowIfSpec | None = None


def combination_key(key: str) -> str:
    return f"{key}{COMBO_SUFFIX}"


def matrix_key(row: str, col: str) -> str:
    return f"{row}{MATRIX_SEPARATOR}{col}"


def _values(t: dm.DigestTrade, key: str) -> tuple[dm.ScalarKey, ...]:
    """The trade's values of ``key``: () when empty, one item for a scalar."""
    value = t.journal.get(key)
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(dict.fromkeys(value))  # distinct, stored order
    return (value,)


def applies(t: dm.DigestTrade, spec: JournalSpec) -> bool:
    """False when ``show_if`` hides the field for this trade."""
    if spec.show_if is None:
        return True
    return spec.show_if.includes in _values(t, spec.show_if.field)


def _option_index(spec: JournalSpec, value: dm.ScalarKey) -> tuple[int, str]:
    """Position in the YAML options; unknown values after them, by text; None last."""
    if value is None:
        return (len(spec.options) + 1, "")
    if isinstance(value, str) and value in spec.options:
        return (spec.options.index(value), "")
    return (len(spec.options), str(value))


type _Rank = tuple[tuple[int, str], ...]


def _breakdown(
    field: str,
    kind: dm.BreakdownKind,
    members: Mapping[dm.GroupKey, tuple[_Rank, list[dm.DigestTrade]]],
    coverage: tuple[int, int],
) -> dm.Breakdown:
    """Groups ordered by their rank (members: key -> (rank, trades))."""
    order = sorted(members, key=lambda k: members[k][0])
    return dm.Breakdown(
        field=field,
        groups=tuple(dm.group_stats(k, members[k][1]) for k in order),
        filled=coverage[0],
        total=coverage[1],
        kind=kind,
    )


def field_breakdown(trades: Iterable[dm.DigestTrade], spec: JournalSpec) -> dm.Breakdown:
    items = [t for t in trades if applies(t, spec)]
    by_key: dict[dm.ScalarKey, list[dm.DigestTrade]] = {}
    for t in items:
        for value in _values(t, spec.key) or (None,):
            by_key.setdefault(value, []).append(t)
    # same order as the trade-field breakdowns: numbers, then text, None last
    members: dict[dm.GroupKey, tuple[_Rank, list[dm.DigestTrade]]] = {
        k: (((i, ""),), by_key[k]) for i, k in enumerate(dm.sorted_keys(list(by_key)))
    }
    filled = sum(1 for t in items if _values(t, spec.key))
    return _breakdown(spec.key, "field", members, (filled, len(items)))


def _combo(t: dm.DigestTrade, spec: JournalSpec) -> str | None:
    values = sorted(_values(t, spec.key), key=lambda v: _option_index(spec, v))
    return COMBO_JOINER.join(str(v) for v in values) or None


def combination_breakdown(trades: Iterable[dm.DigestTrade], spec: JournalSpec) -> dm.Breakdown:
    items = [t for t in trades if applies(t, spec)]
    members: dict[dm.GroupKey, tuple[_Rank, list[dm.DigestTrade]]] = {}
    for t in items:
        ranks = tuple(sorted(_option_index(spec, v) for v in _values(t, spec.key)))
        rank = ranks or (_option_index(spec, None),)
        members.setdefault(_combo(t, spec), (rank, []))[1].append(t)
    filled = sum(1 for t in items if _values(t, spec.key))
    return _breakdown(combination_key(spec.key), "combination", members, (filled, len(items)))


def _first(t: dm.DigestTrade, key: str) -> dm.ScalarKey:
    values = _values(t, key)
    return values[0] if values else None


def matrix_breakdown(
    trades: Iterable[dm.DigestTrade], row: JournalSpec, col: JournalSpec
) -> dm.Breakdown:
    """Scalar fields only (a multi value counts by its first value)."""
    items = [t for t in trades if applies(t, row) and applies(t, col)]
    members: dict[dm.GroupKey, tuple[_Rank, list[dm.DigestTrade]]] = {}
    for t in items:
        a, b = _first(t, row.key), _first(t, col.key)
        rank = (_option_index(row, a), _option_index(col, b))
        members.setdefault((a, b), (rank, []))[1].append(t)
    filled = sum(1 for t in items if _values(t, row.key) and _values(t, col.key))
    return _breakdown(matrix_key(row.key, col.key), "matrix", members, (filled, len(items)))


def journal_breakdowns(
    trades: Iterable[dm.DigestTrade],
    specs: Sequence[JournalSpec],
    combinations: Sequence[str] = (),
    matrices: Sequence[tuple[str, str]] = (),
) -> Mapping[str, dm.Breakdown]:
    """Fields in ``specs`` order; a combination right after its (multi) field, a matrix
    right after the later of its two fields. One whose field is not in ``specs`` is skipped."""
    items = tuple(trades)
    by_key = {s.key: s for s in specs}
    position = {s.key: i for i, s in enumerate(specs)}
    usable = [(r, c) for r, c in matrices if r in by_key and c in by_key]
    result: dict[str, dm.Breakdown] = {}
    for spec in specs:
        result[spec.key] = field_breakdown(items, spec)
        if spec.key in combinations and spec.multi:
            result[combination_key(spec.key)] = combination_breakdown(items, spec)
        for r, c in usable:
            if max(position[r], position[c]) == position[spec.key]:
                result[matrix_key(r, c)] = matrix_breakdown(items, by_key[r], by_key[c])
    return MappingProxyType(result)
