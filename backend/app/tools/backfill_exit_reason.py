"""M8-09 backfill: prefill empty exit reasons of already synced trades from stored deals.

    (repo root, PowerShell or cmd)
    python -m uv run --project backend python -m app.tools.backfill_exit_reason          # dry run
    python -m uv run --project backend python -m app.tools.backfill_exit_reason --apply

Only closed trades whose exit_reason is empty and has no source are touched, with the same
rule as the sync (`app.domain.exit_reason`). Reads the stored exit deals and symbol specs;
no MT5 call. Deals stored before M8-09 already carry the mapped DEAL_REASON key. Prints how
many trades were filled and by which source. Dry run (default) changes nothing.
Before ``--apply`` on the real database take a backup: ``python -m app.tools.backup``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import SymbolSpec, Trade
from app.services.exit_reason import prefill_exit_reason

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    checked: int  # closed trades with an empty exit reason and no source
    filled: dict[str, int] = field(default_factory=dict)  # source -> trades


def backfill(session: Session, *, apply: bool) -> BackfillResult:
    """Fill what the sync would fill; commits only with ``apply``, else rolls back."""
    trades = session.scalars(
        select(Trade)
        .where(
            Trade.close_time.is_not(None),
            Trade.exit_reason.is_(None),
            Trade.exit_reason_source.is_(None),
        )
        .options(selectinload(Trade.exit_deals))
        .order_by(Trade.id)
    ).all()
    ticks = {(s.account_id, s.symbol): s.tick_size for s in session.scalars(select(SymbolSpec))}
    filled: Counter[str] = Counter()
    for trade in trades:
        tick = ticks.get((trade.account_id, trade.broker_symbol))
        source = prefill_exit_reason(session, trade, trade.exit_deals, tick)
        if source is not None:
            filled[source] += 1
    if apply:
        session.commit()
        logger.info("Exit reason backfill applied: %s of %s trades", dict(filled), len(trades))
    else:
        session.rollback()
    return BackfillResult(checked=len(trades), filled=dict(filled))


def _report(result: BackfillResult, *, apply: bool) -> str:
    mode = "застосовано" if apply else "пробний запуск, нічого не змінено"
    lines = [
        f"Причина виходу з MT5 ({mode})",
        f"Перевірено угод з порожньою причиною: {result.checked}",
    ]
    lines += [f"  {source}: {count}" for source, count in sorted(result.filled.items())]
    lines.append(f"Заповнено всього: {sum(result.filled.values())}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = parser.parse_args(argv)
    from app.db import get_session_factory  # lazy: tests build their own session

    with get_session_factory()() as session:
        result = backfill(session, apply=args.apply)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(_report(result, apply=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
