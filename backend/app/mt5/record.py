"""Record raw MT5 data from a (DEMO) terminal into a fixture JSON. Read-only.

    (repo root, PowerShell or cmd; works without uv on PATH)
    python -m uv run --project backend python -m app.mt5.record \\
        --terminal "D:\\MT5\\demo\\terminal64.exe" --login 12345678 \\
        --server "FundedNext-Demo" --days 14 --anonymize \\
        --out backend/tests/fixtures/mt5/recorded_demo.json

The investor password is read from ``.env`` (``MT5_PASSWORD_<login>``) or asked
interactively; it is never written to the file. ``--anonymize`` replaces login and server.
The output is loadable by `app.mt5.fixture.FixtureMt5Source`.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.config import mt5_password_for
from app.mt5.errors import Mt5Error
from app.mt5.fixture import FORMAT_VERSION
from app.mt5.real import RealMt5Source
from app.mt5.source import Mt5Source, connected
from app.mt5.types import RawDeal, RawOrder, RawSymbolSpec, to_json_dict

DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "XAUUSD", "GER40")
ANON_LOGIN = 10000001
ANON_SERVER = "Anonymized-Server"
# Server clocks are at most UTC+14: this end bound is in the future for any broker.
FUTURE_PAD_S = 15 * 3600
TRADE_TYPES = (0, 1)  # buy, sell
ENTRY_IN = 0


def collect(
    source: Mt5Source, days: int, symbols: Sequence[str], now_epoch: int | None = None
) -> dict[str, Any]:
    """Read everything a sync needs from a connected source into fixture form."""
    now = int(time.time()) if now_epoch is None else now_epoch
    to_epoch = now + FUTURE_PAD_S
    from_epoch = to_epoch - (days + 1) * 86400

    account = source.account_info()
    specs: dict[str, RawSymbolSpec] = {s.name: s for s in source.symbols_matching(symbols)}
    ticks: dict[str, int] = {}
    for name in specs:
        tick = source.server_tick_epoch(name)
        if tick is not None:
            ticks[name] = tick

    window = source.deals(from_epoch, to_epoch)
    positions = source.open_positions()
    position_ids = {d.position_id for d in window if d.type in TRADE_TYPES and d.position_id}
    position_ids |= {p.identifier for p in positions}
    deals: dict[int, RawDeal] = {d.ticket: d for d in window}
    for pid in sorted(position_ids):
        for d in source.deals_for_position(pid):
            deals[d.ticket] = d

    orders: dict[int, RawOrder] = {}
    for d in deals.values():
        if d.type in TRADE_TYPES and d.entry == ENTRY_IN:
            order = source.opening_order(d.order)
            if order is not None:
                orders[order.ticket] = order
        if d.symbol and d.symbol not in specs:
            spec = source.symbol_spec(d.symbol)
            if spec is not None:
                specs[spec.name] = spec

    return {
        "format": FORMAT_VERSION,
        "description": f"Recorded {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, last {days} days",
        "account": to_json_dict(account),
        "ticks": ticks,
        "symbols": [to_json_dict(s) for s in specs.values()],
        "deals": [
            to_json_dict(d) for d in sorted(deals.values(), key=lambda d: (d.time, d.ticket))
        ],
        "orders": [to_json_dict(o) for o in sorted(orders.values(), key=lambda o: o.ticket)],
        "positions": [to_json_dict(p) for p in positions],
    }


def anonymize(data: dict[str, Any]) -> dict[str, Any]:
    data["account"] = {**data["account"], "login": ANON_LOGIN, "server": ANON_SERVER}
    data["_anonymized"] = "login and server replaced"
    return data


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dump raw MT5 data (read-only) into a fixture JSON.")
    p.add_argument("--terminal", required=True, help="path to terminal64.exe (portable folder)")
    p.add_argument("--login", required=True, type=int)
    p.add_argument("--server", required=True)
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="comma-separated prefixes")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--anonymize", action="store_true", help="replace login and server")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None, source: Mt5Source | None = None) -> int:
    args = _parse_args(argv)
    password = mt5_password_for(args.login)
    if password is None and sys.stdin.isatty():
        typed = getpass.getpass(f"Investor password for {args.login} (not stored): ")
        password = SecretStr(typed) if typed else None
    src = source if source is not None else RealMt5Source()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    try:
        with connected(src, args.terminal, args.login, password, args.server):
            data = collect(src, args.days, symbols)
    except Mt5Error as exc:
        print(f"MT5 error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    if args.anonymize:
        data = anonymize(data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"Wrote {args.out}: {len(data['deals'])} deals, {len(data['orders'])} orders, "
        f"{len(data['positions'])} open positions, {len(data['symbols'])} symbols"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
