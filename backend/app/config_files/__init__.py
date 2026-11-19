"""Editable YAML configuration in `config/` (rules.yaml, journal_fields.yaml,
ai_pricing.yaml, extraction.yaml, transcription.yaml, transcript_glossary.yaml, bias.yaml,
symbols.yaml, violations.yaml).

Accessors are cached and reload automatically when a file changes; they raise
`ConfigError` (readable message with file path and key) when a file is invalid.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.config_files.ai_models import (
    AiModelsConfig,
    clear_ai_models_cache,
    get_ai_models,
)
from app.config_files.ai_pricing import (
    AiPricingConfig,
    ModelPrice,
    clear_ai_pricing_cache,
    get_ai_pricing,
)
from app.config_files.bias import (
    BiasConfig,
    BiasSymbol,
    ReminderWindow,
    clear_bias_cache,
    get_bias_config,
)
from app.config_files.extraction import clear_extraction_cache, get_number_words
from app.config_files.journal_fields import (
    JournalField,
    JournalFieldsConfig,
    JournalOption,
    clear_journal_fields_cache,
    get_journal_fields,
)
from app.config_files.loader import ConfigError, config_dir
from app.config_files.rules import (
    RULE_KEYS,
    RulesConfig,
    SessionWindow,
    clear_rules_cache,
    get_rules,
)
from app.config_files.symbols import (
    CanonicalSymbol,
    SymbolsConfig,
    clear_symbols_cache,
    get_symbols_config,
)
from app.config_files.transcript_glossary import (
    clear_transcript_glossary_cache,
    get_transcript_glossary,
)
from app.config_files.transcription import (
    TranscriptionConfig,
    clear_transcription_cache,
    get_transcription,
)
from app.config_files.violations import (
    ViolationsConfig,
    clear_violations_cache,
    get_violations,
)

logger = logging.getLogger(__name__)


def reload_config() -> None:
    """Drop cached configs; the next accessor call re-reads the files."""
    clear_rules_cache()
    clear_journal_fields_cache()
    clear_ai_pricing_cache()
    clear_ai_models_cache()
    clear_extraction_cache()
    clear_transcription_cache()
    clear_transcript_glossary_cache()
    clear_bias_cache()
    clear_symbols_cache()
    clear_violations_cache()


def check_config_files() -> list[ConfigError]:
    """Load every config file once; log each problem loudly. Used at API and worker start."""
    errors: list[ConfigError] = []
    loaders: list[Callable[[], object]] = [
        get_rules,
        get_violations,
        get_journal_fields,
        get_ai_pricing,
        get_ai_models,
        get_number_words,
        get_transcription,
        get_transcript_glossary,
        get_bias_config,
        get_symbols_config,
    ]
    for load in loaders:
        try:
            load()
        except ConfigError as exc:
            # journal_fields.yaml re-raises a broken violations.yaml: report it once.
            if not any(e.path == exc.path and e.problems == exc.problems for e in errors):
                errors.append(exc)
    for error in errors:
        logger.error("CONFIG ERROR, fix the file and reload the page. %s", error)
    if not errors:
        logger.info("Config files OK (%s)", config_dir())
    return errors


__all__ = [
    "RULE_KEYS",
    "AiModelsConfig",
    "AiPricingConfig",
    "BiasConfig",
    "BiasSymbol",
    "CanonicalSymbol",
    "ConfigError",
    "JournalField",
    "JournalFieldsConfig",
    "JournalOption",
    "ModelPrice",
    "ReminderWindow",
    "RulesConfig",
    "SessionWindow",
    "SymbolsConfig",
    "TranscriptionConfig",
    "ViolationsConfig",
    "check_config_files",
    "config_dir",
    "get_ai_models",
    "get_ai_pricing",
    "get_bias_config",
    "get_journal_fields",
    "get_number_words",
    "get_rules",
    "get_symbols_config",
    "get_transcript_glossary",
    "get_transcription",
    "get_violations",
    "reload_config",
]
