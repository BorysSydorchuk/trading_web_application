"""`Mt5Source` backed by a JSON fixture (tests, demos). Same raw shape as the real source.

Fixture format (version 1); keys starting with ``_`` are comments:

    {
      "format": 1,
      "description": "...",
      "account":   RawAccountInfo | null,
      "ticks":     {"EURUSD": <server epoch>, ...},
      "symbols":   [RawSymbolSpec, ...],
      "deals":     [RawDeal, ...],
      "orders":    [RawOrder, ...],
      "positions": [RawPosition, ...],
      "failures":  {"<method>": Failure, ...},
      "steps":     [Step, ...]
    }

The top level is step 0. Each entry of ``steps`` is an overlay applied on top of the
previous step (step i = top level + steps[0..i-1]): keys ``account``, ``ticks``,
``symbols``, ``deals``, ``orders``, ``positions``, ``failures`` replace the previous value;
``add_deals`` / ``add_orders`` append. Use `advance()` to move to the next step, e.g. to
simulate a position opening and then closing between two sync cycles.

Failure: ``{"last_error": [code, "message"]}`` (mapped exactly like the real source) or
``{"code": "<Mt5ErrorCode>", "message": "..."}``. Method names: connect, account_info,
server_tick_epoch, symbol_spec, symbols_matching, deals, deals_for_position,
opening_order, open_positions.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.mt5.errors import Mt5Error, Mt5ErrorCode, error_from_last_error
from app.mt5.source import (
    DEFAULT_CONNECT_TIMEOUT_S,
    match_prefixes,
    require_password,
    verify_account,
)
from app.mt5.types import (
    RawAccountInfo,
    RawDeal,
    RawOrder,
    RawPosition,
    RawSymbolSpec,
    from_json_dict,
)

FORMAT_VERSION = 1
METHODS = frozenset(
    {
        "connect",
        "account_info",
        "server_tick_epoch",
        "symbol_spec",
        "symbols_matching",
        "deals",
        "deals_for_position",
        "opening_order",
        "open_positions",
    }
)
_REPLACE_KEYS = ("account", "ticks", "symbols", "deals", "orders", "positions", "failures")
_STEP_KEYS = frozenset({*_REPLACE_KEYS, "add_deals", "add_orders", "name"})
_TOP_KEYS = frozenset({*_REPLACE_KEYS, "format", "description", "steps"})


def _check_keys(data: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(k for k in data if k not in allowed and not k.startswith("_"))
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}")


def _failure(spec: Mapping[str, Any], method: str) -> Mt5Error:
    if "last_error" in spec:
        during = "initialize" if method == "connect" else method
        return error_from_last_error(tuple(spec["last_error"]), during=during)
    return Mt5Error(Mt5ErrorCode(spec["code"]), str(spec.get("message", "scripted failure")))


class _Snapshot:
    def __init__(self, data: Mapping[str, Any]) -> None:
        account = data.get("account")
        self.account = None if account is None else from_json_dict(RawAccountInfo, account)
        self.ticks: dict[str, int] = {str(k): int(v) for k, v in data.get("ticks", {}).items()}
        self.symbols = [from_json_dict(RawSymbolSpec, s) for s in data.get("symbols", [])]
        self.deals = [from_json_dict(RawDeal, d) for d in data.get("deals", [])]
        self.orders = [from_json_dict(RawOrder, o) for o in data.get("orders", [])]
        self.positions = [from_json_dict(RawPosition, p) for p in data.get("positions", [])]
        failures: Mapping[str, Mapping[str, Any]] = data.get("failures", {})
        unknown = sorted(set(failures) - METHODS)
        if unknown:
            raise ValueError(f"failures for unknown methods {unknown}")
        self.failures = {m: _failure(f, m) for m, f in failures.items()}


def _merge_steps(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    _check_keys(data, _TOP_KEYS, "fixture")
    if data.get("format", FORMAT_VERSION) != FORMAT_VERSION:
        raise ValueError(f"unsupported fixture format {data.get('format')!r}")
    current: dict[str, Any] = {k: data[k] for k in _REPLACE_KEYS if k in data}
    merged = [dict(current)]
    for i, step in enumerate(data.get("steps", []), start=1):
        _check_keys(step, _STEP_KEYS, f"step {i}")
        for key in _REPLACE_KEYS:
            if key in step:
                current[key] = step[key]
        current["deals"] = [*current.get("deals", []), *step.get("add_deals", [])]
        current["orders"] = [*current.get("orders", []), *step.get("add_orders", [])]
        merged.append(dict(current))
    return merged


class FixtureMt5Source:
    """Behaves like `RealMt5Source` (connect checks, not-connected errors), from JSON."""

    def __init__(self, data: Mapping[str, Any], *, step: int = 0) -> None:
        self.description = str(data.get("description", ""))
        self._snapshots = [_Snapshot(s) for s in _merge_steps(data)]
        self._extra_failures: dict[str, Mt5Error] = {}
        self._connected = False
        self.calls: list[str] = []
        self.connect_args: tuple[str, int, str] | None = None
        self.set_step(step)

    @classmethod
    def from_file(cls, path: str | Path, *, step: int = 0) -> FixtureMt5Source:
        with Path(path).open(encoding="utf-8") as fh:
            return cls(json.load(fh), step=step)

    # -- scripting --------------------------------------------------------------

    @property
    def step(self) -> int:
        return self._step

    @property
    def step_count(self) -> int:
        return len(self._snapshots)

    def set_step(self, step: int) -> None:
        if not 0 <= step < len(self._snapshots):
            raise IndexError(f"fixture has steps 0..{len(self._snapshots) - 1}, not {step}")
        self._step = step
        self._snap = self._snapshots[step]

    def advance(self) -> None:
        self.set_step(self._step + 1)

    def fail(self, method: str, error: Mt5Error | None) -> None:
        """Make ``method`` raise ``error`` in every step (None clears it)."""
        if method not in METHODS:
            raise ValueError(f"unknown method {method!r}")
        if error is None:
            self._extra_failures.pop(method, None)
        else:
            self._extra_failures[method] = error

    def _enter(self, method: str, *, needs_connection: bool = True) -> None:
        self.calls.append(method)
        error = self._extra_failures.get(method) or self._snap.failures.get(method)
        if error is not None:
            raise error
        if needs_connection and not self._connected:
            raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "not connected to an MT5 terminal")

    # -- Mt5Source --------------------------------------------------------------

    def connect(
        self,
        terminal_path: str,
        login: int,
        password: SecretStr | None,
        server: str,
        timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    ) -> RawAccountInfo:
        self._connected = False
        require_password(login, password)
        self._enter("connect", needs_connection=False)
        self.connect_args = (terminal_path, login, server)
        account = self._snap.account
        if account is None:
            raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "account_info failed: no account (fixture)")
        verify_account(account, login, server)
        self._connected = True
        return account

    def shutdown(self) -> None:
        self.calls.append("shutdown")
        self._connected = False

    def account_info(self) -> RawAccountInfo:
        self._enter("account_info")
        if self._snap.account is None:
            raise Mt5Error(Mt5ErrorCode.MT5_ERROR, "account_info failed: no account (fixture)")
        return self._snap.account

    def server_tick_epoch(self, symbol: str) -> int | None:
        self._enter("server_tick_epoch")
        return self._snap.ticks.get(symbol)

    def symbol_spec(self, symbol: str) -> RawSymbolSpec | None:
        self._enter("symbol_spec")
        return next((s for s in self._snap.symbols if s.name == symbol), None)

    def symbols_matching(self, prefixes: Iterable[str]) -> list[RawSymbolSpec]:
        self._enter("symbols_matching")
        by_name = {s.name: s for s in self._snap.symbols}
        return [by_name[n] for n in match_prefixes(by_name, prefixes)]

    def deals(self, from_server_epoch: int, to_server_epoch: int) -> list[RawDeal]:
        self._enter("deals")
        found = [d for d in self._snap.deals if from_server_epoch <= d.time <= to_server_epoch]
        return sorted(found, key=lambda d: (d.time, d.ticket))

    def deals_for_position(self, position_id: int) -> list[RawDeal]:
        self._enter("deals_for_position")
        found = [d for d in self._snap.deals if d.position_id == position_id]
        return sorted(found, key=lambda d: (d.time, d.ticket))

    def opening_order(self, order_ticket: int) -> RawOrder | None:
        self._enter("opening_order")
        return next((o for o in self._snap.orders if o.ticket == order_ticket), None)

    def open_positions(self) -> list[RawPosition]:
        self._enter("open_positions")
        return list(self._snap.positions)
