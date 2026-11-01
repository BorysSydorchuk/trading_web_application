"""Editable YAML configuration in `config/` (rules.yaml, journal_fields.yaml).

Accessors are cached and reload automatically when a file changes; they raise
`ConfigError` (readable message with file path and key) when a file is invalid.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


def reload_config() -> None:
    """Drop cached configs; the next accessor call re-reads the files."""
    clear_rules_cache()
    clear_journal_fields_cache()


def check_config_files() -> list[ConfigError]:
    """Load every config file once; log each problem loudly. Used at process startup."""
    errors: list[ConfigError] = []
    for load in (get_rules, get_journal_fields):
        try:
            load()
        except ConfigError as exc:
            logger.error("CONFIG ERROR, fix the file and reload the page. %s", exc)
            errors.append(exc)
    if not errors:
        logger.info("Config files OK (%s)", config_dir())
    return errors


__all__ = [
    "RULE_KEYS",
    "ConfigError",
    "JournalField",
    "JournalFieldsConfig",
    "JournalOption",
    "RulesConfig",
    "SessionWindow",
    "check_config_files",
    "config_dir",
    "get_journal_fields",
    "get_rules",
    "reload_config",
]
