"""Live extraction eval on the QA fixtures (M2-07): latency, cost and field accuracy.

    (repo root)  make ai-eval                          # ANTHROPIC_MODEL_EXTRACTION
                 make ai-eval AI_MODEL=claude-opus-5-5 AI_EFFORT=medium

Sends the `text` of every `backend/tests/fixtures/extraction/*.json` through the real
extraction service (same prompt, schema, guards, fallback and timeouts as the endpoint; no
DB) and compares the guarded `fields` with the right answer for the text: the fixture's
`eval_expected_fields`, else its `expected_fields` (`expected_fields` is the guarded result
of the replayed `model_output`, which may be a deliberately bad answer). `model_output` is
not used here (it is for the offline test). Costs real money: about one extraction call
per fixture. Every attempt is logged to logs/ai_usage.jsonl with purpose "eval" (so it
counts in the month-to-date cost). Refuses to run without ANTHROPIC_API_KEY; the key is
never printed.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO, override

from app.config import REPO_ROOT, Settings, get_settings
from app.config_files import get_journal_fields
from app.config_files.journal_fields import JournalFieldsConfig
from app.logging_setup import setup_logging
from app.services.ai.client import AnthropicModelClient, ModelClient
from app.services.ai.extraction import (
    ExtractionFailed,
    ExtractionOutcome,
    ExtractionSettings,
    extract_trade_fields,
)
from app.services.ai.usage_log import UsageLog, UsageRecord, usage_log_path

PURPOSE = "eval"
EVAL_TRADE_ID = 0  # the service needs an id for its log lines; the usage line gets null
DEFAULT_FIXTURES_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "extraction"
LOG_FILE = "ai_eval.log"
P95 = 0.95
COST_QUANTUM = Decimal("0.0001")
EFFORTS = ("low", "medium", "high")
# Right answer for the live eval, first key present wins.
EXPECTED_KEYS = ("eval_expected_fields", "expected_fields")
NO_KEY_MESSAGE = (
    "Error: ANTHROPIC_API_KEY is empty. Set it in .env (repo root) to run the live eval; "
    "the offline fixture test is `make test`."
)


class EvalUsageLog(UsageLog):
    """Usage log that marks lines as eval calls (purpose "eval", no trade) and keeps this
    run's records, so the cost of failed attempts is counted too."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.records: list[UsageRecord] = []

    @override
    def append(self, record: UsageRecord) -> None:
        eval_record = replace(record, purpose=PURPOSE, trade_id=None)
        self.records.append(eval_record)
        super().append(eval_record)


def attempts_cost(records: Sequence[UsageRecord]) -> Decimal | None:
    """Sum of `cost_usd` of the attempts; None if any attempt is unpriced."""
    if any(r.cost_usd is None for r in records):
        return None
    return sum((Decimal(r.cost_usd) for r in records if r.cost_usd is not None), Decimal("0"))


# --- comparison ---


@dataclass(frozen=True)
class FieldComparison:
    correct: tuple[str, ...]
    wrong: tuple[tuple[str, Any, Any], ...]  # (key, expected, got)
    missing: tuple[str, ...]  # expected, not filled
    extra: tuple[str, ...]  # filled, not expected

    @property
    def total(self) -> int:
        return len(self.correct) + len(self.wrong) + len(self.missing) + len(self.extra)


def compare_fields(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> FieldComparison:
    """Field-level comparison; text values must match exactly (after strip)."""
    correct: list[str] = []
    wrong: list[tuple[str, Any, Any]] = []
    for key in expected:
        if key not in actual:
            continue
        if _same(expected[key], actual[key]):
            correct.append(key)
        else:
            wrong.append((key, expected[key], actual[key]))
    return FieldComparison(
        correct=tuple(correct),
        wrong=tuple(wrong),
        missing=tuple(k for k in expected if k not in actual),
        extra=tuple(k for k in actual if k not in expected),
    )


def _same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip() == actual.strip()
    return type(expected) is type(actual) and bool(expected == actual)


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile (p95 of 12 values = the 12th smallest)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


# --- run ---


@dataclass(frozen=True)
class FixtureResult:
    name: str
    duration_s: float
    attempts: int = 0  # usage-log lines (a fallback = 2)
    cost_usd: Decimal | None = Decimal("0")  # all attempts, failed ones included
    outcome: ExtractionOutcome | None = None
    comparison: FieldComparison | None = None
    error: str | None = None
    call_failed: bool = False  # ExtractionFailed (not a broken fixture file)

    @property
    def called(self) -> bool:
        return self.call_failed or self.comparison is not None


def load_fixture(path: Path) -> tuple[str, dict[str, Any]]:
    """(text, right answer): `eval_expected_fields` if present, else `expected_fields`."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise ValueError("fixture has no `text` string")
    key = next((k for k in EXPECTED_KEYS if k in data), EXPECTED_KEYS[-1])
    expected = data.get(key, {})
    if not isinstance(expected, dict):
        raise ValueError(f"`{key}` is not an object")
    return data["text"], expected


@dataclass(frozen=True)
class EvalContext:
    config: JournalFieldsConfig
    client: ModelClient
    settings: ExtractionSettings
    usage_log: EvalUsageLog
    clock: Callable[[], float] = time.monotonic


def run_fixture(path: Path, ctx: EvalContext) -> FixtureResult:
    try:
        text, expected = load_fixture(path)
    except (OSError, ValueError) as exc:
        return FixtureResult(path.stem, 0.0, error=f"bad fixture: {exc}")
    first_record = len(ctx.usage_log.records)
    started = ctx.clock()
    try:
        outcome = extract_trade_fields(
            text,
            trade_id=EVAL_TRADE_ID,
            config=ctx.config,
            client=ctx.client,
            settings=ctx.settings,
            usage_log=ctx.usage_log,
            clock=ctx.clock,
        )
    except ExtractionFailed as exc:
        records = ctx.usage_log.records[first_record:]
        return FixtureResult(
            path.stem,
            ctx.clock() - started,
            attempts=len(records),
            cost_usd=attempts_cost(records),
            error=f"{exc.kind}: {exc.message}",
            call_failed=True,
        )
    return FixtureResult(
        path.stem,
        outcome.usage.duration_ms / 1000,
        attempts=len(ctx.usage_log.records) - first_record,
        cost_usd=outcome.usage.cost_usd,
        outcome=outcome,
        comparison=compare_fields(expected, outcome.fields),
    )


# --- report ---


def _cost(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def format_fixture(result: FixtureResult) -> list[str]:
    head = f"## {result.name}  ({result.duration_s:.1f} s)"
    if result.outcome is None or result.comparison is None:
        lines = [head, f"  ERROR {result.error}"]
        if result.call_failed:
            lines.append(f"  attempts {result.attempts}, cost USD {_cost(result.cost_usd)}")
        return lines
    usage, cmp = result.outcome.usage, result.comparison
    fallback = " (fallback)" if usage.fallback_used else ""
    dropped = ", ".join(f"{d.key} ({d.reason})" for d in result.outcome.dropped) or "-"
    lines = [
        head,
        f"  model {usage.model}{fallback}, tokens in/out {usage.input_tokens}/"
        f"{usage.output_tokens}, cost USD {_cost(usage.cost_usd)}",
        f"  filled ({len(result.outcome.fields)}): {', '.join(result.outcome.fields) or '-'}",
        f"  dropped: {dropped}",
        f"  correct {len(cmp.correct)}/{cmp.total}: {', '.join(cmp.correct) or '-'}",
    ]
    lines += [f"  WRONG {key}: expected {exp!r}, got {got!r}" for key, exp, got in cmp.wrong]
    if cmp.missing:
        lines.append(f"  MISSING: {', '.join(cmp.missing)}")
    if cmp.extra:
        lines.append(f"  EXTRA: {', '.join(cmp.extra)}")
    return lines


def _durations_line(label: str, durations: Sequence[float]) -> str:
    mean_s = sum(durations) / len(durations) if durations else 0.0
    p95 = percentile(durations, P95)
    return f"  duration s ({label}, n={len(durations)}): mean {mean_s:.1f}, p95 {p95:.1f}"


def _cost_line(called: Sequence[FixtureResult]) -> str:
    """Cost of every attempt, failed calls included; extractions with an unpriced attempt
    are left out of the sum (and counted)."""
    priced = [r.cost_usd for r in called if r.cost_usd is not None]
    total = sum(priced, Decimal("0"))
    mean = (total / len(priced)).quantize(COST_QUANTUM) if priced else None
    unpriced = len(called) - len(priced)
    note = f", {unpriced} with an unpriced attempt not counted" if unpriced else ""
    return (
        f"  cost USD (all attempts incl. failed, {sum(r.attempts for r in called)} attempts): "
        f"total {total:.4f}, mean per extraction {_cost(mean)}{note}"
    )


def _accuracy_line(cmps: Sequence[FieldComparison]) -> str:
    correct = sum(len(c.correct) for c in cmps)
    total = sum(c.total for c in cmps)
    accuracy = f"{100 * correct / total:.1f}%" if total else "n/a"
    return (
        f"  fields (successful calls): correct {correct}/{total} ({accuracy}), "
        f"wrong {sum(len(c.wrong) for c in cmps)}, "
        f"missing {sum(len(c.missing) for c in cmps)}, extra {sum(len(c.extra) for c in cmps)}"
    )


def format_totals(results: Sequence[FixtureResult]) -> list[str]:
    called = [r for r in results if r.called]  # bad fixture files are not calls
    ok = [r for r in called if not r.call_failed]
    return [
        "## Totals",
        f"  fixtures {len(results)}, ok {len(ok)}, failed calls {len(called) - len(ok)}, "
        f"bad fixture files {len(results) - len(called)}",
        _durations_line("all calls incl. failed", [r.duration_s for r in called]),
        _durations_line("successful calls", [r.duration_s for r in ok]),
        _cost_line(called),
        _accuracy_line([r.comparison for r in ok if r.comparison is not None]),
    ]


# --- CLI ---


def _parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live AI extraction eval on the fixtures.")
    parser.add_argument("--model", default=settings.anthropic_model_extraction)
    parser.add_argument("--effort", choices=EFFORTS, default=settings.anthropic_effort)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES_DIR)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    client: ModelClient | None = None,
    out: TextIO | None = None,
    configure_logging: bool = True,
) -> int:
    settings = settings or get_settings()
    args = _parser(settings).parse_args(argv)
    if not settings.ai_configured:
        print(NO_KEY_MESSAGE, file=sys.stderr)
        return 1
    out = out or sys.stdout
    if isinstance(out, io.TextIOWrapper):
        out.reconfigure(encoding="utf-8")  # Ukrainian/Russian text on a cp1252 console
    if configure_logging:
        setup_logging(LOG_FILE, settings)
    fixtures = sorted(Path(args.fixtures).glob("*.json"))
    if not fixtures:
        print(f"Error: no *.json fixtures in {args.fixtures}", file=sys.stderr)
        return 1
    ctx = EvalContext(
        config=get_journal_fields(),
        client=client or AnthropicModelClient(settings.anthropic_api_key),
        settings=ExtractionSettings(args.model, settings.anthropic_model_fallback, args.effort),
        usage_log=EvalUsageLog(usage_log_path(settings)),
    )
    print(f"# AI extraction eval: model {args.model}, effort {args.effort}", file=out)
    results: list[FixtureResult] = []
    for path in fixtures:
        result = run_fixture(path, ctx)
        results.append(result)
        print("\n".join(format_fixture(result)), file=out, flush=True)
    print("\n".join(format_totals(results)), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
