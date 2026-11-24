"""Sliding-window request limiter, one per connection and per limit."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class RateLimiter:
    """At most ``max_calls`` per ``period_s``; ``acquire`` waits for a free slot."""

    def __init__(
        self,
        max_calls: int,
        period_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max_calls = max_calls
        self._period_s = period_s
        self._clock = clock
        self._sleep = sleep
        self._stamps: deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            now = self._clock()
            while self._stamps and self._stamps[0] <= now - self._period_s:
                self._stamps.popleft()
            if len(self._stamps) < self._max_calls:
                self._stamps.append(now)
                return
            await self._sleep(self._stamps[0] + self._period_s - now)
