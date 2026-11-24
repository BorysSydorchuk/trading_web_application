"""Phase c additions to the fake cTrader history server: assets (2112), tick data (2145) and
M1 trendbars (2137, c5).

Message numbers are literals on purpose: the protocol constants are part of the phase c
implementation (tests/test_ctrader_phase_c_specs.py pins their names), so this helper keeps
working while they are still missing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from tests.ctrader_fakes import CTID, Handler, Reply
from tests.ctrader_history_fakes import HistoryServer, load

ASSET_LIST_REQ, ASSET_LIST_RES = 2112, 2113
TICK_DATA_REQ, TICK_DATA_RES = 2145, 2146
TRENDBARS_REQ, TRENDBARS_RES = 2137, 2138
M1 = 1  # ProtoOATrendbarPeriod M1
MINUTE_MS = 60_000
BID, ASK = 1, 2  # ProtoOAQuoteType
PRICE_SCALE = 100_000  # ticks are integers in 1/100000

# (epoch ms UTC, price)
Point = tuple[int, Decimal]
# One M1 trendbar (BID prices): (start of the minute in epoch ms UTC, open, high, low, close)
Bar = tuple[int, Decimal, Decimal, Decimal, Decimal]


def encode_ticks(points: Iterable[Point]) -> list[dict[str, int]]:
    """ProtoOATickData as the server sends it (ASSUMPTION, to confirm on the first live run):
    ascending time; the first entry carries the absolute ``timestamp`` (ms) and ``tick``
    (price * 100000); every later entry carries the DELTA to the previous one."""
    out: list[dict[str, int]] = []
    last_time = last_price = 0
    for at, price in sorted(points):
        scaled = int(price * PRICE_SCALE)
        out.append({"timestamp": at - last_time, "tick": scaled - last_price})
        last_time, last_price = at, scaled
    return out


def encode_trendbar(bar: Bar) -> dict[str, int]:
    """ProtoOATrendbar as the server sends it. ASSUMPTION (Open API docs, to confirm on the
    first live run): ``low`` is absolute, ``deltaOpen``, ``deltaClose`` and ``deltaHigh`` are
    unsigned distances above ``low``; all prices are integers in 1/100000;
    ``utcTimestampInMinutes`` is the start of the bar in epoch minutes."""
    start_ms, open_, high, low, close = bar
    scaled = {name: int(value * PRICE_SCALE) for name, value in
              (("open", open_), ("high", high), ("low", low), ("close", close))}  # fmt: skip
    return {
        "low": scaled["low"],
        "deltaOpen": scaled["open"] - scaled["low"],
        "deltaClose": scaled["close"] - scaled["low"],
        "deltaHigh": scaled["high"] - scaled["low"],
        "utcTimestampInMinutes": start_ms // MINUTE_MS,
    }


def tick_points(name: str = "EURUSD") -> dict[int, list[Point]]:
    """The fixture ticks of one symbol: {BID: [...], ASK: [...]}."""
    raw = load("ticks_eurusd.json")[name]
    return {
        BID: [(int(t), Decimal(p)) for t, p in raw["bid"]],
        ASK: [(int(t), Decimal(p)) for t, p in raw["ask"]],
    }


class PhaseCServer(HistoryServer):
    """HistoryServer + assets + ticks + M1 trendbars.

    ``ticks``: {broker symbol name: {BID|ASK: points}}. ``bars``: {broker symbol name: [Bar]}
    (BID only, as the real 2137 answer). A bar is returned when its start lies in
    ``fromTimestamp..toTimestamp`` (ms); with ``bars_ignore_range`` every bar is returned (a
    real server may also send the bar that overlaps ``fromTimestamp``).

    ``requests`` lists every request type received (all connections), ``tick_requests`` the
    (symbolId, type, from_ms, to_ms) of every 2145, ``trendbar_requests`` the
    (symbolId, period, from_ms, to_ms) of every 2137.
    """

    def __init__(
        self,
        *args: Any,
        ticks: Mapping[str, Mapping[int, list[Point]]] | None = None,
        bars: Mapping[str, list[Bar]] | None = None,
        bars_ignore_range: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.ticks = dict(ticks or {})
        self.bars = dict(bars or {})
        self.bars_ignore_range = bars_ignore_range
        self.trendbar_requests: list[tuple[int, int, int, int]] = []
        self.assets = load("assets.json")
        self.requests: list[int] = []
        self.tick_requests: list[tuple[int, int, int, int]] = []
        self._names = {int(s["symbolId"]): s["symbolName"] for s in self.symbols["list"]["symbol"]}

    def count(self, payload_type: int) -> int:
        return self.requests.count(payload_type)

    def _tick_data(self, frame: dict[str, Any]) -> Reply:
        payload = frame["payload"]
        symbol_id, kind = int(payload["symbolId"]), int(payload["type"])
        lo, hi = int(payload["fromTimestamp"]), int(payload["toTimestamp"])
        self.tick_requests.append((symbol_id, kind, lo, hi))
        points = self.ticks.get(self._names.get(symbol_id, ""), {}).get(kind, [])
        inside = [pt for pt in points if lo <= pt[0] <= hi]
        return TICK_DATA_RES, {
            "ctidTraderAccountId": CTID,
            "tickData": encode_ticks(inside),
            "hasMore": False,
        }

    def _trendbars(self, frame: dict[str, Any]) -> Reply:
        payload = frame["payload"]
        symbol_id, period = int(payload["symbolId"]), int(payload["period"])
        lo, hi = int(payload["fromTimestamp"]), int(payload["toTimestamp"])
        self.trendbar_requests.append((symbol_id, period, lo, hi))
        found = self.bars.get(self._names.get(symbol_id, ""), []) if period == M1 else []
        inside = [b for b in sorted(found) if self.bars_ignore_range or lo <= b[0] <= hi]
        return TRENDBARS_RES, {
            "ctidTraderAccountId": CTID,
            "period": period,
            "timestamp": hi,
            "trendbar": [encode_trendbar(b) for b in inside],
            "symbolId": symbol_id,
        }

    def _logged(self, payload_type: int, handler: Handler) -> Handler:
        def run(frame: dict[str, Any]) -> Reply:
            self.requests.append(payload_type)
            return handler(frame) if callable(handler) else handler

        return run

    def handlers(self) -> dict[int, Handler]:
        base = super().handlers()
        base[ASSET_LIST_REQ] = (ASSET_LIST_RES, self.assets)
        base[TICK_DATA_REQ] = self._tick_data
        base[TRENDBARS_REQ] = self._trendbars
        return {kind: self._logged(kind, handler) for kind, handler in base.items()}
