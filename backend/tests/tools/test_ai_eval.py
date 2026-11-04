"""Live eval tool (app.tools.ai_eval) with the fake model client: no network, no DB."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.tools import ai_eval
from app.tools.ai_eval import compare_fields, percentile
from tests.services.ai_fakes import FakeClient, overloaded, reply

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "extraction"
FAKE_KEY = "sk-ant-test-DO-NOT-PRINT-0123456789"


def make_settings(tmp_path: Path, key: str = FAKE_KEY) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused@localhost/unused",
        anthropic_api_key=SecretStr(key),
        log_dir=tmp_path / "logs",
    )


def fixture_data(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def usage_lines(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "logs" / "ai_usage.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_compare_fields_counts_correct_wrong_missing_extra() -> None:
    result = compare_fields(
        {"entry_model": "qm_m5", "exit_reason": "sl", "lesson": "урок", "quality_rating": 4},
        {"entry_model": "qm_m5", "exit_reason": "tp", "lesson": " урок ", "followed_plan": True},
    )
    assert result.correct == ("entry_model", "lesson")
    assert result.wrong == (("exit_reason", "sl", "tp"),)
    assert result.missing == ("quality_rating",)
    assert result.extra == ("followed_plan",)
    assert result.total == 5


def test_compare_fields_bool_is_not_int() -> None:
    assert compare_fields({"quality_rating": 1}, {"quality_rating": True}).wrong


def test_percentile_nearest_rank() -> None:
    assert percentile([], 0.95) == 0.0
    assert percentile([3.0], 0.95) == 3.0
    assert percentile([float(v) for v in range(1, 13)], 0.95) == 12.0
    assert percentile([float(v) for v in range(1, 21)], 0.95) == 19.0


def test_refuses_without_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeClient([])
    code = ai_eval.main([], settings=make_settings(tmp_path, key="  "), client=client)
    assert code == 1
    assert "ANTHROPIC_API_KEY is empty" in capsys.readouterr().err
    assert client.requests == []
    assert not (tmp_path / "logs" / "ai_usage.jsonl").exists()


def right_answer(fixture: dict[str, Any]) -> dict[str, Any]:
    answer: dict[str, Any] = fixture.get("eval_expected_fields", fixture["expected_fields"])
    return answer


def test_replays_all_fixtures_and_reports_totals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = sorted(FIXTURES_DIR.glob("*.json"))
    fixtures = [fixture_data(p) for p in paths]
    client = FakeClient([reply(f["model_output"]) for f in fixtures])
    out = io.StringIO()

    code = ai_eval.main(
        ["--model", "claude-opus-5-5"],
        settings=make_settings(tmp_path),
        client=client,
        out=out,
        configure_logging=False,
    )

    report = out.getvalue()
    assert code == 0
    assert {r.model for r in client.requests} == {"claude-opus-5-5"}
    assert [r.user_text for r in client.requests] == [f["text"] for f in fixtures]
    # The replayed answer yields `expected_fields`; the eval scores it against the right
    # answer (`eval_expected_fields` where a fixture's model_output is deliberately bad).
    cmps = [compare_fields(right_answer(f), f["expected_fields"]) for f in fixtures]
    correct, total = sum(len(c.correct) for c in cmps), sum(c.total for c in cmps)
    assert sum(len(c.wrong) + len(c.extra) for c in cmps) == 0
    assert correct < total  # some fixtures are bad answers on purpose
    assert f"correct {correct}/{total} ({100 * correct / total:.1f}%)" in report
    n = len(paths)
    assert f"fixtures {n}, ok {n}, failed calls 0, bad fixture files 0" in report
    # FakeClient USAGE = 1830 in / 210 out on Sonnet prices: 0.00366 + 0.0021 = 0.0058
    assert "cost USD 0.0058" in report
    assert f"{n} attempts): total {0.0058 * n:.4f}, mean per extraction 0.0058" in report
    assert "chart_links (not_fillable)" in report  # tradingview_link
    lines = usage_lines(tmp_path)
    assert len(lines) == n
    assert {(line["purpose"], line["trade_id"]) for line in lines} == {("eval", None)}
    everything = report + capsys.readouterr().out + capsys.readouterr().err
    assert FAKE_KEY not in everything
    assert FAKE_KEY not in (tmp_path / "logs" / "ai_usage.jsonl").read_text(encoding="utf-8")


def test_eval_expected_fields_is_the_right_answer(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    shutil.copy(FIXTURES_DIR / "bad_answer_guards.json", fixtures_dir / "bad.json")
    fixture = fixture_data(fixtures_dir / "bad.json")
    assert fixture["eval_expected_fields"] != fixture["expected_fields"]
    plain = {k: v for k, v in fixture.items() if k != "eval_expected_fields"}
    (fixtures_dir / "plain.json").write_text(json.dumps(plain), encoding="utf-8")
    assert ai_eval.load_fixture(fixtures_dir / "bad.json")[1] == fixture["eval_expected_fields"]
    assert ai_eval.load_fixture(fixtures_dir / "plain.json")[1] == fixture["expected_fields"]

    # a correct live answer: right for the text, so no EXTRA / MISSING
    correct = {
        "poi_type": {"value": "fvg_h4", "evidence": "POI FVG H4"},
        "entry_model": {"value": "other", "evidence": "Зашел по IFVG на M15"},
        "exit_reason": {"value": "tp", "evidence": "Закрыл в TP"},
        "followed_plan": {"value": False, "evidence": "не по моему плану"},
    }
    out = io.StringIO()
    code = ai_eval.main(
        ["--fixtures", str(fixtures_dir)],
        settings=make_settings(tmp_path),
        client=FakeClient([reply(correct), reply(correct)]),
        out=out,
        configure_logging=False,
    )

    report = out.getvalue()
    assert code == 0
    bad_section, plain_section = report.split("## plain")
    assert "correct 4/4" in bad_section
    assert "MISSING" not in bad_section
    assert "EXTRA" not in bad_section
    # against expected_fields (the guarded bad answer) the same answer looks wrong
    assert "EXTRA: entry_model, exit_reason, followed_plan" in plain_section


def test_wrong_answer_and_failed_calls_are_reported(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    for name in ("ger40_ny_ifvg_complete", "mixed_ua_ru_basic", "xau_london_qm_partial"):
        shutil.copy(FIXTURES_DIR / f"{name}.json", fixtures_dir / f"{name}.json")
    (fixtures_dir / "zz_broken.json").write_text("{not json", encoding="utf-8")
    wrong = {
        "entry_model": {"value": "ifvg_m5", "evidence": "QM-ка на M5"},
        "followed_plan": {"value": True, "evidence": "взял тейк"},
    }
    # ger40: refusal (billed, no fallback); mixed: overloaded on primary and fallback
    # (no tokens, cost 0); xau: a wrong answer
    client = FakeClient(
        [reply({}, stop_reason="refusal"), overloaded(), overloaded(), reply(wrong)]
    )
    out = io.StringIO()

    code = ai_eval.main(
        ["--fixtures", str(fixtures_dir)],
        settings=make_settings(tmp_path),
        client=client,
        out=out,
        configure_logging=False,
    )

    report = out.getvalue()
    assert code == 0
    assert "ERROR refusal" in report
    assert "attempts 1, cost USD 0.0058" in report
    assert "ERROR overloaded" in report
    assert "attempts 2, cost USD 0.0000" in report
    assert "ERROR bad fixture" in report
    assert "WRONG entry_model: expected 'qm_m5', got 'ifvg_m5'" in report
    assert "MISSING: setup_context, exit_reason" in report
    assert "EXTRA: followed_plan" in report
    assert "fixtures 4, ok 1, failed calls 2, bad fixture files 1" in report
    assert "duration s (all calls incl. failed, n=3)" in report
    assert "duration s (successful calls, n=1)" in report
    # failed attempts are in the cost: refusal 0.0058 + overloads 0 + xau 0.0058
    assert "incl. failed, 4 attempts): total 0.0116, mean per extraction 0.0039" in report
    assert "correct 0/4 (0.0%), wrong 1, missing 2, extra 1" in report
    assert len(usage_lines(tmp_path)) == 4


def test_totals_include_failed_call_durations() -> None:
    results = [
        ai_eval.FixtureResult("ok", 2.0, attempts=1, comparison=compare_fields({}, {})),
        ai_eval.FixtureResult("timeout", 27.0, attempts=2, call_failed=True, error="timeout"),
        ai_eval.FixtureResult("broken", 0.0, error="bad fixture: x"),
    ]

    totals = " | ".join(ai_eval.format_totals(results))

    assert "fixtures 3, ok 1, failed calls 1, bad fixture files 1" in totals
    assert "(all calls incl. failed, n=2): mean 14.5, p95 27.0" in totals
    assert "(successful calls, n=1): mean 2.0, p95 2.0" in totals
