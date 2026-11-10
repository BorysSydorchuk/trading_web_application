"""Re-apply config/symbols.yaml to stored rows (docs/api.md M5-08, DECISIONS 2026-11-10).

The migration only copied `symbol` into the broker/canonical columns; the canonical names
come from the YAML map at run time, so stored GER30 trades show and aggregate as GER40 and a
later edit of symbols.yaml applies to history too. Run by the worker at start and at the
start of every sync cycle. Idempotent and cheap when nothing changed (one DISTINCT query per
table, nothing else). Flushes, never commits.

Renaming trades changes their bias alignment and rules (re-entry is per canonical symbol),
so a rename and its recompute are one step: bias.yaml and rules.yaml are loaded *before*
anything is renamed. If either is broken, nothing is renamed and `apply_symbol_map` returns
None; the next attempt (next sync cycle) renames and recomputes together. With nothing to
rename the two files are not needed, so a broken bias.yaml never blocks the steady state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.config_files.loader import ConfigError
from app.config_files.rules import RulesConfig, get_rules
from app.config_files.symbols import SymbolsConfig
from app.domain.bias_alignment import AlignmentSettings
from app.domain.symbols import canonical_symbol
from app.models import SymbolSpec, Trade
from app.models.calculator import CalculatorMarginRequest
from app.services.bias_alignment import alignment_settings, recompute_trades
from app.services.trade_rules import recompute_rules

logger = logging.getLogger(__name__)

# (stored canonical name, broker name) -> canonical name the map wants.
WrongPairs = dict[tuple[str, str], str]


@dataclass(frozen=True, slots=True)
class RenamedTrade:
    id: int
    account_id: int
    open_time: datetime


def _wrong_pairs(
    session: Session,
    canonical_col: InstrumentedAttribute[str],
    broker_col: InstrumentedAttribute[str],
    symbols: SymbolsConfig,
) -> WrongPairs:
    """(canonical, broker) pairs stored with a canonical name the map disagrees with."""
    rows = session.execute(select(canonical_col, broker_col).distinct()).all()
    wrong: WrongPairs = {}
    for row in rows:
        canonical: str = row[0]
        broker: str = row[1]
        wanted = canonical_symbol(symbols, broker)
        if wanted != canonical:
            wrong[(canonical, broker)] = wanted
    return wrong


def _rowcount(result: object) -> int:
    count = getattr(result, "rowcount", 0)
    return count if isinstance(count, int) and count > 0 else 0


def _rename(
    session: Session,
    canonical_col: InstrumentedAttribute[str],
    broker_col: InstrumentedAttribute[str],
    wrong: WrongPairs,
) -> int:
    """One set-based UPDATE per wrong pair (specs, margin requests)."""
    changed = 0
    for (canonical, broker), wanted in sorted(wrong.items()):
        result = session.execute(
            update(canonical_col.class_)
            .where(canonical_col == canonical, broker_col == broker)
            .values({canonical_col.key: wanted})
        )
        changed += _rowcount(result)
    return changed


def _rename_trades(session: Session, wrong: WrongPairs) -> list[RenamedTrade]:
    """Set-based UPDATE per pair; returns (id, account_id, open_time) of the renamed trades."""
    renamed: list[RenamedTrade] = []
    for (canonical, broker), wanted in sorted(wrong.items()):
        rows = session.execute(
            update(Trade)
            .where(Trade.symbol == canonical, Trade.broker_symbol == broker)
            .values(symbol=wanted)
            .returning(Trade.id, Trade.account_id, Trade.open_time)
        ).all()
        renamed.extend(RenamedTrade(row[0], row[1], row[2]) for row in rows)
    return renamed


def _recompute(
    session: Session,
    renamed: list[RenamedTrade],
    bias: AlignmentSettings,
    rules: RulesConfig,
) -> None:
    """Bias alignment of the renamed trades and the rules of their weeks onward."""
    ids = sorted(t.id for t in renamed)
    trades = session.scalars(select(Trade).where(Trade.id.in_(ids)).order_by(Trade.id)).all()
    recompute_trades(session, trades, bias)
    since: dict[int, datetime] = {}
    for t in renamed:
        if t.account_id not in since or t.open_time < since[t.account_id]:
            since[t.account_id] = t.open_time
    for account_id, start in sorted(since.items()):
        recompute_rules(session, account_id, start, rules)


def _recompute_configs() -> tuple[AlignmentSettings, RulesConfig] | None:
    try:
        return alignment_settings(), get_rules()
    except ConfigError as exc:
        logger.error(
            "Symbol map not applied (renamed trades need their alignment and rules recomputed): %s",
            exc,
        )
        return None


def apply_symbol_map(session: Session, symbols: SymbolsConfig) -> int | None:
    """Give stored trades, specs and margin requests their canonical names.

    Returns the number of rows changed (0 = everything already matches), or None when trades
    need renaming but bias.yaml / rules.yaml is broken: then nothing at all is renamed
    (logged at ERROR). Flushes, never commits.
    """
    wrong_trades = _wrong_pairs(session, Trade.symbol, Trade.broker_symbol, symbols)
    wrong_specs = _wrong_pairs(session, SymbolSpec.canonical_symbol, SymbolSpec.symbol, symbols)
    model = CalculatorMarginRequest
    wrong_requests = _wrong_pairs(session, model.symbol, model.broker_symbol, symbols)
    if not (wrong_trades or wrong_specs or wrong_requests):
        return 0
    configs = _recompute_configs() if wrong_trades else None
    if wrong_trades and configs is None:
        return None
    session.flush()  # pending ORM changes first; the UPDATEs below bypass the unit of work
    changed = _rename(session, SymbolSpec.canonical_symbol, SymbolSpec.symbol, wrong_specs)
    changed += _rename(session, model.symbol, model.broker_symbol, wrong_requests)
    renamed = _rename_trades(session, wrong_trades)
    if renamed and configs is not None:
        _recompute(session, renamed, *configs)
        logger.info("Symbol map: %s trades renamed to their canonical symbol", len(renamed))
    session.flush()
    return changed + len(renamed)
