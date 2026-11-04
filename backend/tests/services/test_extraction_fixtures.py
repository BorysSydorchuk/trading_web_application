"""Extraction fixtures (tests/fixtures/extraction/*.json, format in its README.md).

Each fixture replays a recorded/hand-written model answer through the full extraction
with a fake model (never the real API) and checks the guarded result. QA adds the real
sample texts in M2-07; a new file is picked up without code changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config_files import get_journal_fields, get_number_words
from app.domain.extraction import contains_phrase, evidence_in_text, normalise_for_match
from app.domain.journal import ai_fillable_keys
from app.services.ai.extraction import ExtractionSettings, extract_trade_fields
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, reply

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "extraction"
FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))
SETTINGS = ExtractionSettings("claude-sonnet-5-5", "claude-opus-5-5", "medium")


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for key in ("text", "model_output", "expected_fields"):
        assert key in data, f"{path.name}: missing {key!r}"
    return data


def test_fixtures_exist() -> None:
    assert len(FIXTURES) >= 2


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_extraction_fixture(path: Path, tmp_path: Path) -> None:
    fixture = load(path)
    config = get_journal_fields()
    text: str = fixture["text"]
    output: dict[str, Any] = fixture["model_output"]

    outcome = extract_trade_fields(
        text,
        trade_id=1,
        config=config,
        number_words=get_number_words(),
        client=FakeClient([reply(output)]),
        settings=SETTINGS,
        usage_log=UsageLog(tmp_path / "ai_usage.jsonl"),
    )

    assert outcome.fields == fixture["expected_fields"]
    dropped = [{"key": d.key, "reason": d.reason} for d in outcome.dropped]
    assert dropped == fixture.get("expected_dropped", [])
    if "expected_missing_required" in fixture:
        assert outcome.missing_required == fixture["expected_missing_required"]

    # Invariants (PRD 6.5): nothing without a quote from the text, no questions,
    # nothing outside the schema.
    fillable = {k.key for k in ai_fillable_keys(config)}
    normalised = normalise_for_match(text)
    for key, value in outcome.fields.items():
        assert key in fillable
        evidence = output[key]["evidence"]
        assert evidence_in_text(evidence, normalised), f"{key}: evidence not in text"
        if isinstance(value, str) and "?" in value:
            assert "?" in evidence, f"{key}: question in a value"
        if isinstance(value, str) and output[key]["value"] == value.strip():
            spec_type = next(k.type for k in ai_fillable_keys(config) if k.key == key)
            if spec_type == "text":
                assert contains_phrase(normalise_for_match(value), normalised), key
