"""Fitted monitors are loaded once per version and kept in a small LRU cache."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import datetime

from sentinel_server.analysis import Monitors


class MonitorCache:
    """Version id → monitors, invalidated if the version is refitted."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._items: OrderedDict[int, tuple[datetime | None, Monitors]] = OrderedDict()

    async def get(
        self,
        version_id: int,
        fitted_at: datetime | None,
        load: Callable[[], Awaitable[bytes]],
    ) -> Monitors:
        """Cached monitors for a version; on a miss, ``load`` fetches the serialised blob."""
        hit = self._items.get(version_id)
        if hit is not None and hit[0] == fitted_at:
            self._items.move_to_end(version_id)
            return hit[1]
        monitors = Monitors.from_bytes(await load())
        self._items[version_id] = (fitted_at, monitors)
        self._items.move_to_end(version_id)
        while len(self._items) > self._size:
            self._items.popitem(last=False)
        return monitors
