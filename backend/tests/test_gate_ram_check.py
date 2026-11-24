"""Gate RAM check: start at >= 3 GB free, re-check for 10 min, then report instead of starting."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "gate_ram_check.py"
    spec = importlib.util.spec_from_file_location("tj_gate_ram_check", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _run(
    readings: list[float | None], env: dict[str, str] | None = None
) -> tuple[bool, list[float], list[str]]:
    values: Iterator[float | None] = iter(readings)
    slept: list[float] = []
    said: list[str] = []
    ok = gate.wait_for_memory(
        env or {}, read=lambda: next(values), sleep=slept.append, say=said.append
    )
    return ok, slept, said


def test_enough_free_ram_starts_at_once() -> None:
    ok, slept, said = _run([5.2])
    assert ok is True
    assert slept == []
    assert "5.2 GB" in said[0]


def test_low_ram_waits_and_starts_when_memory_frees() -> None:
    ok, slept, _said = _run([2.5, 2.8, 3.0])
    assert ok is True
    assert slept == [gate.RECHECK_S, gate.RECHECK_S]


def test_low_ram_for_ten_minutes_reports_instead_of_starting() -> None:
    checks = gate.WAIT_S // gate.RECHECK_S + 1
    ok, slept, said = _run([2.5] * checks)
    assert ok is False
    assert sum(slept) == gate.WAIT_S
    assert said[-1].startswith("[gate] NOT STARTED")
    assert "2.5 GB" in said[-1]


def test_unknown_ram_does_not_block_the_gate() -> None:
    ok, _slept, said = _run([None])
    assert ok is True
    assert "unknown" in said[0]


def test_limits_can_be_set_for_one_run() -> None:
    ok, slept, _said = _run([1.5], {gate.MIN_ENV: "1", gate.WAIT_ENV: "0"})
    assert ok is True
    assert slept == []
    ok, slept, said = _run([0.5], {gate.MIN_ENV: "1", gate.WAIT_ENV: "0"})
    assert ok is False
    assert slept == []
    assert said[-1].startswith("[gate] NOT STARTED")


def test_this_machine_reports_a_plausible_value() -> None:
    free = gate.free_gb()
    assert free is None or 0 < free < 4096
