"""ai_pricing.yaml loader, cost and the month-to-date summary of logs/ai_usage.jsonl."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.config import REPO_ROOT
from app.config_files import ConfigError, get_ai_pricing, reload_config
from app.config_files.ai_pricing import ModelPrice, load_ai_pricing
from app.config_files.loader import CONFIG_DIR_ENV
from app.services.ai.client import TokenUsage
from app.services.ai.usage_log import (
    UsageLog,
    UsageRecord,
    compute_cost,
    cost_for,
    find_price,
    summarise_month,
    utc_ts,
)

REAL_CONFIG = REPO_ROOT / "config"


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    target = tmp_path / "cfg"
    target.mkdir()
    for name in ("rules.yaml", "journal_fields.yaml", "ai_pricing.yaml"):
        shutil.copy(REAL_CONFIG / name, target / name)
    monkeypatch.setenv(CONFIG_DIR_ENV, str(target))
    reload_config()
    yield target
    reload_config()


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- pricing file ---


def test_real_pricing_file() -> None:
    pricing = get_ai_pricing()
    assert pricing.models["claude-sonnet-5-5"] == ModelPrice(
        input=Decimal("2.00"),
        output=Decimal("10.00"),
        cache_write=Decimal("2.50"),
        cache_read=Decimal("0.20"),
    )
    opus = pricing.models["claude-opus-5-5"]
    assert (opus.input, opus.output, opus.cache_write, opus.cache_read) == (
        Decimal("4.00"),
        Decimal("20.00"),
        Decimal("5.00"),
        Decimal("0.20"),
    )


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("models: {}\n", "models"),
        ("models:\n  m1: { input: 1, output: 1, cache_write: 1 }\n", "cache_read"),
        ("models:\n  m1: { input: -1, output: 1, cache_write: 1, cache_read: 1 }\n", "input"),
        ("models:\n  m1: { input: x, output: 1, cache_write: 1, cache_read: 1 }\n", "input"),
        ("models:\n  m1: { input: true, output: 1, cache_write: 1, cache_read: 1 }\n", "input"),
        (
            "models:\n  m1: { input: 1, output: 1, cache_write: 1, cache_read: 1, extra: 1 }\n",
            "extra",
        ),
        (
            "models:\n  Bad Id: { input: 1, output: 1, cache_write: 1, cache_read: 1 }\n",
            "model ids",
        ),
        ("prices: {}\n", "prices"),
        ("- a\n", "(root)"),
        ("models:\n  m1: { input: 1 }\n  m1: { input: 2 }\n", "duplicate"),
    ],
)
def test_pricing_file_is_strictly_validated(tmp_path: Path, content: str, problem: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load_ai_pricing(write(tmp_path / "ai_pricing.yaml", content))
    assert problem in str(caught.value)


def test_unquoted_prices_are_exact(tmp_path: Path) -> None:
    path = write(
        tmp_path / "p.yaml",
        "models:\n  m1: { input: 0.2, output: 10, cache_write: 2.5, cache_read: 0.1 }\n",
    )
    price = load_ai_pricing(path).models["m1"]
    assert price.input == Decimal("0.2")
    assert price.cache_read == Decimal("0.1")


# --- cost ---


def test_compute_cost_all_token_kinds() -> None:
    price = get_ai_pricing().models["claude-sonnet-5-5"]
    usage = TokenUsage(1_000_000, 100_000, 200_000, 500_000)
    # 2.00 + 1.00 + 0.50 + 0.10
    assert compute_cost(price, usage) == Decimal("3.6000")
    assert compute_cost(price, TokenUsage(1830, 210)) == Decimal("0.0058")


def test_find_price_exact_then_dated_snapshot() -> None:
    models = get_ai_pricing().models
    assert find_price(models, "claude-sonnet-5-5") is models["claude-sonnet-5-5"]
    assert find_price(models, "claude-sonnet-5-5-20261101") is models["claude-sonnet-5-5"]
    assert find_price(models, "claude-sonnet-5") is None


def test_cost_for_zero_tokens_is_zero_even_without_model() -> None:
    assert cost_for(None, TokenUsage()) == Decimal("0.0000")
    assert cost_for(None, TokenUsage(1, 1)) is None


def test_cost_for_broken_pricing_is_null_and_logged(
    cfg_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write(cfg_dir / "ai_pricing.yaml", "models: nope\n")
    reload_config()
    with caplog.at_level(logging.ERROR):
        assert cost_for("claude-sonnet-5-5", TokenUsage(10, 10)) is None
    assert any("ai_pricing.yaml is invalid" in r.getMessage() for r in caplog.records)


# --- append ---


RECORD = UsageRecord(
    ts="2026-11-04T09:30:00.000Z",
    purpose="extract",
    trade_id=1,
    requested_model="claude-sonnet-5-5",
    model="claude-sonnet-5-5",
    fallback_used=False,
    input_tokens=100,
    output_tokens=10,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=0,
    cost_usd="0.0003",
    ok=True,
    error_kind=None,
    duration_ms=1200,
)


def test_append_creates_dir_and_adds_lines(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "new" / "ai_usage.jsonl")
    log.append(RECORD)
    log.append(replace(RECORD, ok=False, error_kind="timeout"))
    rows = [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]
    assert [r["ok"] for r in rows] == [True, False]
    assert rows[1]["error_kind"] == "timeout"


def test_utc_ts() -> None:
    assert utc_ts(datetime(2026, 3, 1, 12, 0, 0, 123456, tzinfo=UTC)) == "2026-03-01T12:00:00.123Z"


# --- month summary ---


def line(ts: str, **kw: Any) -> str:
    data: dict[str, Any] = {
        "ts": ts,
        "ok": True,
        "cost_usd": "0.0100",
        "input_tokens": 100,
        "output_tokens": 10,
    }
    return json.dumps(data | kw)


def test_summary_uses_the_brussels_month(tmp_path: Path) -> None:
    path = write(
        tmp_path / "u.jsonl",
        "\n".join(
            [
                line("2026-10-31T22:59:59Z"),  # 23:59:59 Brussels (CET): October
                line("2026-10-31T23:00:00Z"),  # 00:00 Brussels 1 Nov: counted
                line("2026-11-15T10:00:00Z", ok=False, cost_usd="0.0000"),
                line("2026-11-30T22:59:00Z", cost_usd=None),  # 23:59 Brussels: counted
                line("2026-11-30T23:00:00Z"),  # 1 Dec Brussels
            ]
        )
        + "\n",
    )
    month = summarise_month(path, datetime(2026, 11, 10, 12, tzinfo=UTC))
    assert month.month == "2026-11"
    assert (month.calls, month.failed_calls, month.unpriced_calls) == (3, 1, 1)
    assert month.cost_usd == Decimal("0.0100")
    assert (month.input_tokens, month.output_tokens) == (300, 30)


def test_summary_month_of_now_in_brussels(tmp_path: Path) -> None:
    path = write(tmp_path / "u.jsonl", line("2026-10-31T23:30:00Z") + "\n")
    # 2026-10-31 23:30 UTC is already November in Brussels
    month = summarise_month(path, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    assert (month.month, month.calls) == ("2026-11", 1)


def test_broken_lines_are_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write(
        tmp_path / "u.jsonl",
        "\n".join(
            [
                "{not json",
                "[]",
                line("not a date"),
                line("2026-11-02T10:00:00"),  # naive ts
                line("2026-11-02T10:00:00Z", ok="yes"),
                line("2026-11-02T10:00:00Z", cost_usd="abc"),
                "",
                line("2026-11-02T10:00:00Z"),
            ]
        ),
    )
    with caplog.at_level(logging.WARNING):
        month = summarise_month(path, datetime(2026, 11, 10, tzinfo=UTC))
    assert month.calls == 1
    assert any(
        "skipped 6 broken line(s), first at line 1" in r.getMessage() for r in caplog.records
    )


def test_missing_file_is_an_empty_month(tmp_path: Path) -> None:
    month = summarise_month(tmp_path / "none.jsonl", datetime(2026, 11, 10, tzinfo=UTC))
    assert (month.calls, month.cost_usd) == (0, Decimal("0.0000"))
