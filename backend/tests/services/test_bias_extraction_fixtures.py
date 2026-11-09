"""Bias extraction fixtures (tests/fixtures/extraction_bias/*.json, format in its README.md).

Each fixture replays a model answer through the full bias extraction with a fake model
(never the real API) and checks the guarded result and the PRD 6.5/6.6 invariants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.config_files import get_bias_config, get_number_words
from app.domain.bias_extraction import (
    KEY_LEVELS,
    KEY_LEVELS_SEPARATOR,
    TEXT_KEYS,
    mentioned_symbols,
)
from app.domain.extraction import contains_phrase, evidence_in_text, normalise_for_match
from app.models.enums import BiasKind
from app.services.ai.bias_extraction import extract_bias_fields
from app.services.ai.extraction import ExtractionSettings
from app.services.ai.usage_log import UsageLog
from tests.services.ai_fakes import FakeClient, reply

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "extraction_bias"
FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))
SETTINGS = ExtractionSettings("claude-sonnet-5-5", "claude-opus-5-5", "low")


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for key in ("kind", "text", "model_output", "expected_entries"):
        assert key in data, f"{path.name}: missing {key!r}"
    return data


def test_fixtures_exist() -> None:
    assert len(FIXTURES) >= 8


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_bias_extraction_fixture(path: Path, tmp_path: Path) -> None:
    fixture = load(path)
    config = get_bias_config()
    text: str = fixture["text"]
    answer = json.dumps({"entries": fixture["model_output"]}, ensure_ascii=False)

    outcome = extract_bias_fields(
        text,
        BiasKind(fixture["kind"]),
        config=config,
        number_words=get_number_words(),
        client=FakeClient([reply(text=answer)]),
        settings=SETTINGS,
        usage_log=UsageLog(tmp_path / "ai_usage.jsonl"),
    )

    assert {e.symbol: e.fields for e in outcome.entries} == fixture["expected_entries"]
    symbols = [e.symbol for e in outcome.entries]
    assert symbols == [s for s in config.symbol_names if s in symbols]  # bias.yaml order
    dropped = [{"symbol": d.symbol, "key": d.key, "reason": d.reason} for d in outcome.dropped]
    assert dropped == fixture.get("expected_dropped", [])

    # Invariants: nothing without a quote from the text, only named symbols, his own
    # words, no questions.
    normalised = normalise_for_match(text)
    named = mentioned_symbols(config, text)
    for entry in outcome.entries:
        assert entry.symbol in named
        assert entry.evidence.keys() == entry.fields.keys()
        for key, value in entry.fields.items():
            evidence = entry.evidence[key]
            assert evidence_in_text(evidence, normalised), f"{entry.symbol}.{key}"
            if key in TEXT_KEYS:
                assert isinstance(value, str)
                # key_levels: one or more pieces of his text joined by "; "
                parts = value.split(KEY_LEVELS_SEPARATOR) if key == KEY_LEVELS else [value]
                for part in parts:
                    assert contains_phrase(normalise_for_match(part), normalised)
                assert "?" not in value or "?" in evidence
