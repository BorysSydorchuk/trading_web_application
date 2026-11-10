"""Canonical <-> broker symbol names (docs/api.md "M5-08 Canonical symbols"). Pure.

Canonical names (config/symbols.yaml) are used everywhere in the app; broker names only in
MT5 calls. All comparisons are case-insensitive; results keep the broker's own spelling.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.config_files.symbols import SymbolsConfig


def broker_candidates(config: SymbolsConfig, name: str, firm: str | None) -> tuple[str, ...]:
    """Broker names to try for canonical ``name`` (matched case-insensitively, like the
    firm): the firm override if it has one for this symbol, else the configured name followed
    by its broker names. Unknown names: just ``name``."""
    override = config.firm_override(firm)
    if override is not None:
        folded = name.casefold()
        chosen = next((v for k, v in override.items() if k.casefold() == folded), None)
        if chosen is not None:
            return chosen
    symbol = config.symbol(name)
    if symbol is None:
        return (name,)
    return (symbol.name, *symbol.broker_names)


def resolve_broker_symbol(
    config: SymbolsConfig, name: str, firm: str | None, available: Iterable[str]
) -> str | None:
    """The broker symbol for canonical ``name`` among ``available`` broker symbols.

    The first candidate the broker has exactly wins; else, in candidate order, the first
    broker symbol starting with a candidate (suffixes like ``EURUSD.r``); else None.
    """
    names = list(available)
    folded = [(n, n.casefold()) for n in names]
    candidates = [c.casefold() for c in broker_candidates(config, name, firm)]
    for candidate in candidates:
        exact = next((n for n, f in folded if f == candidate), None)
        if exact is not None:
            return exact
    for candidate in candidates:
        prefixed = next((n for n, f in folded if f.startswith(candidate)), None)
        if prefixed is not None:
            return prefixed
    return None


def _all_words(config: SymbolsConfig) -> list[tuple[str, str]]:
    """(casefolded name or broker name, canonical name), override names included."""
    words: list[tuple[str, str]] = []
    for entry in config.symbols:
        words.extend((w.casefold(), entry.name) for w in (entry.name, *entry.broker_names))
    for overrides in config.firms.values():
        for key, override in overrides.items():
            symbol = next((s for s in config.symbols if s.name.casefold() == key.casefold()), None)
            if symbol is not None:
                words.extend((w.casefold(), symbol.name) for w in override)
    return words


def canonical_symbol(config: SymbolsConfig, broker_symbol: str) -> str:
    """Canonical name of a broker symbol: exact name/broker name, else the longest
    name/broker name it starts with, else the broker name itself (unconfigured symbol)."""
    folded = broker_symbol.casefold()
    words = _all_words(config)
    exact = next((canonical for word, canonical in words if word == folded), None)
    if exact is not None:
        return exact
    prefixes = [(len(word), canonical) for word, canonical in words if folded.startswith(word)]
    if not prefixes or not folded:
        return broker_symbol
    return max(prefixes, key=lambda item: item[0])[1]
