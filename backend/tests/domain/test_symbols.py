"""Pure canonical <-> broker symbol resolution (app/domain/symbols.py, docs/api.md M5-08)."""

from __future__ import annotations

import pytest

from app.config_files.symbols import SymbolsConfig
from app.domain.symbols import broker_candidates, canonical_symbol, resolve_broker_symbol

CONFIG = SymbolsConfig.model_validate(
    {
        "symbols": [
            {"name": "EURUSD"},
            {"name": "GBPUSD"},
            {"name": "XAUUSD"},
            {"name": "GER40", "broker_names": ["GER30", "GER40.cash", "DE40"]},
        ],
        "firms": {"FundedNext": {"GER40": ["GER30"]}, "FTMO": {"GER40": ["DAX40", "DE40"]}},
    }
)


# --- candidates ------------------------------------------------------------------------------


def test_candidates_without_override_are_name_then_broker_names() -> None:
    assert broker_candidates(CONFIG, "GER40", None) == ("GER40", "GER30", "GER40.cash", "DE40")
    assert broker_candidates(CONFIG, "GER40", "Other firm") == (
        "GER40",
        "GER30",
        "GER40.cash",
        "DE40",
    )
    assert broker_candidates(CONFIG, "EURUSD", "FundedNext") == ("EURUSD",)


@pytest.mark.parametrize("firm", ["FundedNext", "fundednext", " FundedNext "])
def test_firm_override_replaces_the_candidates(firm: str) -> None:
    assert broker_candidates(CONFIG, "GER40", firm) == ("GER30",)


def test_override_keeps_its_order() -> None:
    assert broker_candidates(CONFIG, "GER40", "FTMO") == ("DAX40", "DE40")


# --- canonical -> broker ---------------------------------------------------------------------


def test_funded_next_ger40_resolves_to_ger30() -> None:
    """The real case (M5-07): FundedNext has GER30, no GER40."""
    available = ["EURUSD", "GBPUSD", "XAUUSD", "GER30", "US30"]
    assert resolve_broker_symbol(CONFIG, "GER40", "FundedNext", available) == "GER30"


def test_override_means_only_those_names() -> None:
    """FundedNext's override lists only GER30: a broker GER40 is not used for that firm."""
    assert resolve_broker_symbol(CONFIG, "GER40", "FundedNext", ["GER40", "EURUSD"]) is None


def test_exact_match_wins_over_an_earlier_prefix_candidate() -> None:
    # GER40 (first candidate) only matches GER40.cash by prefix; GER30 matches exactly.
    available = ["GER40.cash.x", "GER30"]
    assert resolve_broker_symbol(CONFIG, "GER40", None, available) == "GER30"


def test_first_exact_candidate_in_candidate_order() -> None:
    available = ["DE40", "GER40.cash", "GER30"]
    assert resolve_broker_symbol(CONFIG, "GER40", None, available) == "GER30"


@pytest.mark.parametrize("broker", ["eurusd", "EurUsd"])
def test_exact_match_is_case_insensitive_and_returns_the_broker_spelling(broker: str) -> None:
    assert resolve_broker_symbol(CONFIG, "EURUSD", None, ["GBPUSD", broker]) == broker


def test_suffix_found_by_prefix_in_broker_order() -> None:
    available = ["GBPUSD.r", "EURUSD.r", "EURUSD.x"]
    assert resolve_broker_symbol(CONFIG, "EURUSD", None, available) == "EURUSD.r"


def test_prefix_match_is_case_insensitive() -> None:
    assert resolve_broker_symbol(CONFIG, "XAUUSD", None, ["xauusd+"]) == "xauusd+"


def test_prefix_follows_candidate_order() -> None:
    # No exact candidate; GER30 comes before DE40 in the candidates.
    available = ["DE40.r", "GER30.r"]
    assert resolve_broker_symbol(CONFIG, "GER40", None, available) == "GER30.r"


def test_override_candidates_also_match_by_prefix() -> None:
    assert resolve_broker_symbol(CONFIG, "GER40", "FundedNext", ["GER30.r"]) == "GER30.r"


@pytest.mark.parametrize("available", [[], ["EURUSD", "GBPUSD", "XAUUSD"], ["GER", "DAX"]])
def test_not_found_at_the_broker(available: list[str]) -> None:
    assert resolve_broker_symbol(CONFIG, "GER40", None, available) is None


# --- broker -> canonical ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("broker", "canonical"),
    [
        ("GER40", "GER40"),
        ("GER30", "GER40"),
        ("ger30", "GER40"),
        ("DE40", "GER40"),
        ("GER40.cash", "GER40"),
        ("EURUSD", "EURUSD"),
        ("eurusd", "EURUSD"),
        ("DAX40", "GER40"),  # a firm override name is a broker name of GER40 too
    ],
)
def test_exact_name_or_broker_name(broker: str, canonical: str) -> None:
    assert canonical_symbol(CONFIG, broker) == canonical


@pytest.mark.parametrize(
    ("broker", "canonical"),
    [
        ("EURUSD.r", "EURUSD"),
        ("EURUSDm", "EURUSD"),
        ("GER30.r", "GER40"),
        ("GER40.cash.x", "GER40"),
        ("xauusd+", "XAUUSD"),
    ],
)
def test_longest_prefix(broker: str, canonical: str) -> None:
    assert canonical_symbol(CONFIG, broker) == canonical


@pytest.mark.parametrize("broker", ["US30", "GER", "AUDUSD", "", "DE4"])
def test_unconfigured_symbol_keeps_its_name(broker: str) -> None:
    assert canonical_symbol(CONFIG, broker) == broker


def test_candidates_lookup_is_case_insensitive_like_the_rest() -> None:
    assert broker_candidates(CONFIG, "ger40", None) == ("GER40", "GER30", "GER40.cash", "DE40")
    assert broker_candidates(CONFIG, "Ger40", "fundednext") == ("GER30",)
    assert resolve_broker_symbol(CONFIG, "ger40", None, ["GER30"]) == "GER30"


def test_unknown_canonical_name_is_its_own_only_candidate() -> None:
    assert broker_candidates(CONFIG, "US30", "FundedNext") == ("US30",)
