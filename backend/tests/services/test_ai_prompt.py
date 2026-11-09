"""backend/prompts/extract_trade.md rendering (app.services.ai.prompt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config_files import get_bias_config, get_journal_fields, get_number_words
from app.models.enums import BiasKind
from app.services.ai.prompt import (
    EXTRACT_BIAS_PROMPT,
    EXTRACT_TRADE_PROMPT,
    FIELDS_PLACEHOLDER,
    KIND_PLACEHOLDER,
    PROMPTS_DIR,
    SYMBOLS_PLACEHOLDER,
    PromptError,
    extract_bias_system_prompt,
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


def test_trade_prompt_maps_take_profit_at_point_b_to_point_b() -> None:
    # PM 2026-11-09 (live M4 eval): "по тейку в точке B" = the point B target, not TP.
    prompt = extract_trade_system_prompt(get_journal_fields())
    for phrase in ("по тейку в точке B", "тейк на точці B", "закрив по тейку в точці B"):
        assert phrase in prompt
    assert "is the point B target (`point_b`), not the plain TP (`tp`)" in prompt


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


# --- bias prompt (M4-06) ---


def test_bias_prompt_has_rules_kind_and_aliases() -> None:
    prompt = extract_bias_system_prompt(get_bias_config(), BiasKind.PRE_NY)
    assert KIND_PLACEHOLDER not in prompt
    assert SYMBOLS_PLACEHOLDER not in prompt
    for phrase in ("Never invent", "verbatim", "Never ask questions", "no_trade", "POI"):
        assert phrase in prompt
    assert "This note is `pre_ny`: the daily bias" in prompt
    assert "- `XAUUSD`: also called золото, gold, голд, XAU/USD, XAU" in prompt


def test_bias_prompt_is_byte_stable_per_kind() -> None:
    config = get_bias_config()
    weekly = extract_bias_system_prompt(config, BiasKind.WEEKLY)
    assert weekly == extract_bias_system_prompt(config, BiasKind.WEEKLY)
    assert weekly != extract_bias_system_prompt(config, BiasKind.MONTHLY)


def test_bias_prompt_missing_file_or_placeholder(tmp_path: Path) -> None:
    config = get_bias_config()
    with pytest.raises(PromptError, match="Cannot read prompt"):
        extract_bias_system_prompt(config, BiasKind.PRE_LONDON, tmp_path)
    (tmp_path / EXTRACT_BIAS_PROMPT).write_text("only {{KIND}}", encoding="utf-8")
    with pytest.raises(PromptError, match="SYMBOLS"):
        extract_bias_system_prompt(config, BiasKind.PRE_LONDON, tmp_path)


# Number words the bias prompt names for `confidence`; each must mean the same number in
# config/extraction.yaml, or the guard would drop what the prompt asks for.
BIAS_PROMPT_NUMBER_WORDS = {
    **dict.fromkeys(("один", "одна", "одиниця", "одиничка", "единица", "единичка", "one"), 1),
    **dict.fromkeys(("два", "дві", "двійка", "двойка", "two"), 2),
    **dict.fromkeys(("три", "трійка", "тройка", "three"), 3),
}


def test_bias_prompt_lists_confidence_number_words_known_to_the_guard() -> None:
    prompt = extract_bias_system_prompt(get_bias_config(), BiasKind.PRE_NY)
    words = get_number_words().words
    for word, number in BIAS_PROMPT_NUMBER_WORDS.items():
        assert f'"{word}"' in prompt, word
        assert words[word] == number, word
    assert '"уверенность единица" = 1' in prompt


def test_bias_prompt_asks_for_all_key_levels_joined_in_text_order() -> None:
    prompt = extract_bias_system_prompt(get_bias_config(), BiasKind.PRE_LONDON)
    assert 'joined by "; "' in prompt
    assert '`key_levels` "хаю Азії; 18900"' in prompt
    assert 'never "POI H4; 1.2710"' in prompt  # a zone with its price stays one level
    assert "`narrative` is one continuous piece" in prompt
