"""Daily partitions of ``predictions``: created on first write, dropped after retention.

A day's partition is created just before the first insert into it. There is deliberately no
DEFAULT partition: rows parked there would block creating the real partition later, and a
missing partition failing loudly is better than one silently absorbing data.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

Executor = AsyncConnection | AsyncSession
"""Anything that runs SQL; store functions work inside a session's transaction or a bare one."""

_LOCK_KEY = 0x5E47_1E01
"""Advisory lock serialising partition DDL across workers."""


def partition_name(day: date) -> str:
    """``predictions_20261024``."""
    return f"predictions_{day:%Y%m%d}"


async def ensure_partitions(conn: Executor, days: Iterable[date]) -> None:
    """Create any missing daily partitions for ``days``. Safe to call concurrently."""
    wanted = sorted(set(days))
    if not wanted:
        return
    existing = await _existing(conn)
    missing = [d for d in wanted if partition_name(d) not in existing]
    if not missing:
        return
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    for day in missing:
        # Partition bounds are UTC midnights, matching how days are bucketed everywhere else.
        await conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {partition_name(day)} PARTITION OF predictions "
                f"FOR VALUES FROM ('{day.isoformat()} 00:00:00+00') "
                f"TO ('{(day + timedelta(days=1)).isoformat()} 00:00:00+00')"
            )
        )


async def drop_partitions_before(conn: Executor, cutoff: date) -> list[str]:
    """Drop every daily partition for a day before ``cutoff``; returns the dropped names."""
    await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    dropped = []
    for name in sorted(await _existing(conn)):
        if name < partition_name(cutoff):
            await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
            dropped.append(name)
    return dropped


async def _existing(conn: Executor) -> set[str]:
    rows = await conn.execute(
        text(
            "SELECT c.relname FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = 'predictions'"
        )
    )
    return {r[0] for r in rows}
