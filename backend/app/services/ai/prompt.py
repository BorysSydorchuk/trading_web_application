"""System prompts in `backend/prompts/` (versioned in git), rendered from the YAML config.

Rendering is deterministic (no timestamps, YAML order) so the system prompt is byte-stable
between calls and could be prompt-cached.
"""

from __future__ import annotations

from pathlib import Path

from app.config_files.bias import BiasConfig
from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.bias_extraction import KIND_DESCRIPTIONS, render_symbol_catalogue
from app.domain.extraction import render_field_catalogue
from app.models.enums import BiasKind

# app/services/ai/prompt.py -> parents[3] = backend/
PROMPTS_DIR: Path = Path(__file__).resolve().parents[3] / "prompts"
EXTRACT_TRADE_PROMPT = "extract_trade.md"
FIELDS_PLACEHOLDER = "{{JOURNAL_FIELDS}}"
EXTRACT_BIAS_PROMPT = "extract_bias.md"
SYMBOLS_PLACEHOLDER = "{{SYMBOLS}}"
KIND_PLACEHOLDER = "{{KIND}}"


class PromptError(RuntimeError):
    """A prompt file is missing or has no placeholder (a deployment bug, not user input)."""


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    path = prompts_dir / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"Cannot read prompt {path}: {exc}") from exc


def extract_trade_system_prompt(
    config: JournalFieldsConfig, prompts_dir: Path = PROMPTS_DIR
) -> str:
    """The extraction system prompt with the field/option list from journal_fields.yaml."""
    template = load_prompt(EXTRACT_TRADE_PROMPT, prompts_dir)
    if FIELDS_PLACEHOLDER not in template:
        raise PromptError(f"{EXTRACT_TRADE_PROMPT} has no {FIELDS_PLACEHOLDER} placeholder")
    return template.replace(FIELDS_PLACEHOLDER, render_field_catalogue(config)).strip() + "\n"


def extract_bias_system_prompt(
    config: BiasConfig, kind: BiasKind, prompts_dir: Path = PROMPTS_DIR
) -> str:
    """The bias extraction system prompt with the note kind and the bias.yaml symbols and
    aliases. Byte-stable for the same kind and bias.yaml."""
    template = load_prompt(EXTRACT_BIAS_PROMPT, prompts_dir)
    for placeholder in (KIND_PLACEHOLDER, SYMBOLS_PLACEHOLDER):
        if placeholder not in template:
            raise PromptError(f"{EXTRACT_BIAS_PROMPT} has no {placeholder} placeholder")
    rendered = template.replace(KIND_PLACEHOLDER, KIND_DESCRIPTIONS[kind]).replace(
        SYMBOLS_PLACEHOLDER, render_symbol_catalogue(config)
    )
    return rendered.strip() + "\n"
