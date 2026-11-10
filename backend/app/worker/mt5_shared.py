"""One MT5 source and one lock per worker process, shared by the sync and margin jobs.

The MetaTrader5 package talks to one terminal per process, so only one job may be inside it
at a time: sync acquires the lock blocking and holds it for its whole cycle (priority), the
margin job only tries (non-blocking) and skips its run while sync is busy.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from app.mt5.source import Mt5Source


class SharedMt5:
    """Creates the `Mt5Source` lazily on first use (building the scheduler creates none)."""

    def __init__(self, factory: Callable[[], Mt5Source]) -> None:
        self._factory = factory
        self._source: Mt5Source | None = None
        self._create_lock = threading.Lock()
        self.lock = threading.Lock()

    def source(self) -> Mt5Source:
        with self._create_lock:
            if self._source is None:
                self._source = self._factory()
            return self._source
