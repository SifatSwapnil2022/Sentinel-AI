"""Drop data older than the retention period."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.db.models import DailyWindow, Label
from sentinel_server.db.partitions import drop_partitions_before
from sentinel_server.db.store import day_start

log = logging.getLogger(__name__)


async def apply_retention(
    sessions: async_sessionmaker[AsyncSession], retention_days: int, *, today: date | None = None
) -> list[str]:
    """Drop prediction partitions, day documents and labels past retention."""
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=retention_days)
    async with sessions() as session, session.begin():
        dropped = await drop_partitions_before(session, cutoff)
        await session.execute(delete(DailyWindow).where(DailyWindow.day < cutoff))
        await session.execute(delete(Label).where(Label.received_at < day_start(cutoff)))
    if dropped:
        log.info("retention: dropped %s", ", ".join(dropped))
    return dropped
