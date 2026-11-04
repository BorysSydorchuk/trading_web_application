"""backend/prompts/extract_trade.md rendering (app.services.ai.prompt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config_files import get_journal_fields
from app.services.ai.prompt import (
    EXTRACT_TRADE_PROMPT,
    FIELDS_PLACEHOLDER,
    PROMPTS_DIR,
    PromptError,
    extract_trade_system_prompt,
)


def test_prompt_file_is_in_backend_prompts() -> None:
    assert (PROMPTS_DIR / EXTRACT_TRADE_PROMPT).is_file()
    assert PROMPTS_DIR.parent.name == "backend"


def test_system_prompt_has_rules_glossary_and_yaml_options() -> None:
    prompt = extract_trade_system_prompt(get_journal_fields())
    assert FIELDS_PLACEHOLDER not in prompt
    for phrase in ("Never invent", "verbatim", "Never ask questions", "IFVG", "QM", "Point B"):
        assert phrase in prompt
    assert "`fvg_kind` (Тип FVG): one option value:" in prompt
    assert "  - `post_manipulation`: після маніпуляції" in prompt


def test_system_prompt_is_deterministic() -> None:
    config = get_journal_fields()
    assert extract_trade_system_prompt(config) == extract_trade_system_prompt(config)


def test_missing_prompt_or_placeholder_is_a_prompt_error(tmp_path: Path) -> None:
    config = get_journal_fields()
    with pytest.raises(PromptError, match="Cannot read prompt"):
        extract_trade_system_prompt(config, tmp_path)
    (tmp_path / EXTRACT_TRADE_PROMPT).write_text("no placeholder", encoding="utf-8")
    with pytest.raises(PromptError, match="placeholder"):
        extract_trade_system_prompt(config, tmp_path)
