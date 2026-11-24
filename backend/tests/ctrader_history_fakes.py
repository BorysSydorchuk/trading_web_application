"""A fake cTrader history server built from the JSON fixtures in tests/fixtures/ctrader/.

It answers reconcile (2124), deal list (2133, filtered by the requested time range, with
``hasMore`` when more than ``max_rows`` deals match), symbols (2114/2116), assets (2112), an
empty tick answer (2145) and the position P&L (2187) on top of
`ctrader_fakes.default_handlers`. No network is involved.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.ctrader import protocol as p
from tests.ctrader_fakes import CTID, FakeTransport, Handler, Reply, default_handlers

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ctrader"


def load(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


class HistoryServer:
    def __init__(
        self,
        deals: Iterable[dict[str, Any]] = (),
        positions: Iterable[dict[str, Any]] = (),
        pnl: Iterable[dict[str, Any]] = (),
        *,
        max_rows: int | None = None,
        balance: int = 100050,
    ) -> None:
        self.deals = list(deals)
        self.positions = list(positions)
        self.pnl = list(pnl)
        self.max_rows = max_rows
        self.balance = balance
        self.symbols = load("symbols.json")
        self.deal_requests: list[tuple[int, int]] = []

    def _deal_list(self, frame: dict[str, Any]) -> Reply:
        payload = frame["payload"]
        lo, hi = int(payload["fromTimestamp"]), int(payload["toTimestamp"])
        self.deal_requests.append((lo, hi))
        if hi - lo > p.MAX_DEAL_WINDOW_MS:  # what the real server refuses
            return p.ERROR_RES, {"errorCode": "INCORRECT_BOUNDARIES", "description": "range"}
        found = [d for d in self.deals if lo <= int(d["executionTimestamp"]) <= hi]
        more = self.max_rows is not None and len(found) > self.max_rows
        shown = found[: self.max_rows] if more else found
        return p.DEAL_LIST_RES, {"ctidTraderAccountId": CTID, "deal": shown, "hasMore": more}

    def handlers(self) -> dict[int, Handler]:
        handlers = default_handlers()
        handlers[p.TRADER_REQ] = (
            p.TRADER_RES,
            {
                "ctidTraderAccountId": CTID,
                "trader": {"ctidTraderAccountId": CTID, "balance": self.balance, "moneyDigits": 2},
            },
        )
        handlers[p.POSITION_PNL_REQ] = (
            p.POSITION_PNL_RES,
            {"ctidTraderAccountId": CTID, "moneyDigits": 2, "positionUnrealizedPnL": self.pnl},
        )
        handlers[p.RECONCILE_REQ] = (
            p.RECONCILE_RES,
            {"ctidTraderAccountId": CTID, "position": self.positions, "order": []},
        )
        handlers[p.DEAL_LIST_REQ] = self._deal_list
        handlers[p.SYMBOLS_LIST_REQ] = (p.SYMBOLS_LIST_RES, self.symbols["list"])
        handlers[p.SYMBOL_BY_ID_REQ] = (p.SYMBOL_BY_ID_RES, self.symbols["byId"])
        # Phase c reads specs and conversion ticks in the same cycle: the assets, and no
        # tick at all (tests/ctrader_phase_c_fakes.PhaseCServer serves real ticks).
        handlers[p.ASSET_LIST_REQ] = (p.ASSET_LIST_RES, load("assets.json"))
        handlers[p.TICK_DATA_REQ] = (
            p.TICK_DATA_RES,
            {"ctidTraderAccountId": CTID, "tickData": [], "hasMore": False},
        )
        return handlers

    def transport(self) -> FakeTransport:
        return FakeTransport(self.handlers())
