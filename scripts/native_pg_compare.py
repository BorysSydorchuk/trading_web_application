"""Copy verification for `scripts/native_pg.py` (pure, stdlib only): per-table row counts,
md5 checksums and the alembic revision compared between Docker and native, plus a
pg_restore error summary that never carries row data.
"""

# RUF001: the console messages are Ukrainian on purpose (Cyrillic look-alike letters).

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

ERROR_SUMMARY_CHARS = 300

# --------------------------------------------------------------------------- comparison

MISSING = "—"


@dataclass(frozen=True)
class Snapshot:
    counts: Mapping[str, int]
    checksums: Mapping[str, str]
    alembic: tuple[str, ...]


@dataclass(frozen=True)
class Row:
    table: str
    source: str
    target: str

    @property
    def ok(self) -> bool:
        """Equal and present: a value missing on both sides is never a verified copy."""
        return self.source == self.target and self.source != MISSING


@dataclass(frozen=True)
class Comparison:
    rows: tuple[Row, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return bool(self.rows) and all(row.ok for row in self.rows)


def compare(source: Snapshot, target: Snapshot) -> Comparison:
    """Row per table count, per checksum and the alembic revision; any mismatch -> not ok."""
    rows = [
        Row(f"{t} (рядків)", str(source.counts.get(t, MISSING)), str(target.counts.get(t, MISSING)))
        for t in sorted({*source.counts, *target.counts})
    ]
    rows += [
        Row(f"{t} (md5)", source.checksums.get(t, MISSING), target.checksums.get(t, MISSING))
        for t in sorted({*source.checksums, *target.checksums})
    ]
    rows.append(
        Row(
            "alembic_version",
            "+".join(source.alembic) or MISSING,
            "+".join(target.alembic) or MISSING,
        )
    )
    return Comparison(tuple(rows))


def format_comparison(result: Comparison) -> list[str]:
    width = max((len(row.table) for row in result.rows), default=10)
    lines = [f"{'таблиця'.ljust(width)}  {'Docker':>34}  {'native':>34}  стан"]
    for row in result.rows:
        state = "OK" if row.ok else "РІЗНИЦЯ"
        lines.append(f"{row.table.ljust(width)}  {row.source:>34}  {row.target:>34}  {state}")
    return lines


def checksum_tables(model_tables: Sequence[str]) -> list[str]:
    return sorted({*model_tables, "alembic_version"})


_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')


def restore_error_summary(stderr: str) -> str:
    """Last pg_restore error line, without DETAIL/CONTEXT/`Command was` lines (row data)
    and with quoted literals masked."""
    noise = ("detail:", "context:", "hint:", "command was", "line ")
    lines = [
        line.strip()
        for line in stderr.splitlines()
        if line.strip() and not any(n in line.strip().lower() for n in noise)
    ]
    if not lines:
        return "—"
    head, sep, tail = lines[-1].partition("ERROR:")
    return (head + sep + _QUOTED.sub('"…"', tail))[:ERROR_SUMMARY_CHARS]
