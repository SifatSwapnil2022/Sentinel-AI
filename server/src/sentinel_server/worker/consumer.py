"""Move ingest batches from the Redis stream into Postgres.

Delivery is at-least-once: an entry is acknowledged only after its transaction commits, and
writes are idempotent (predictions on their primary key, labels by upsert), so a redelivered
entry changes nothing. Entries a crashed worker left unacknowledged are claimed by another
after ``reclaim_idle_ms``. An entry that cannot be decoded, or fails ``max_deliveries`` times,
is copied to the dead-letter stream with the reason and acknowledged, so it can be inspected
without blocking the rest.

Acknowledged entries are trimmed from the stream, so its length is the backlog the API's
backpressure check reads.
"""

from __future__ import annotations

import logging
import socket
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.contracts import LabelMessage, MalformedMessageError, PredictionMessage, decode
from sentinel_server.db.store import affected_days, insert_predictions, mark_dirty, upsert_labels

log = logging.getLogger(__name__)

Entry = tuple[bytes, dict[bytes, bytes]]


@dataclass(frozen=True)
class ConsumerConfig:
    """Stream names and limits."""

    stream: str
    dead_letter: str
    group: str
    batch: int = 50
    block_ms: int = 2000
    reclaim_idle_ms: int = 60_000
    max_deliveries: int = 5
    name: str = field(default_factory=lambda: f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")
    """Consumer name within the group; unique per process so pending entries are attributable."""


@dataclass
class ConsumeStats:
    """Counts from one pass, for logs and tests."""

    written: int = 0
    duplicates: int = 0
    dead: int = 0
    failed: int = 0


class Consumer:
    """One member of the consumer group."""

    def __init__(
        self,
        redis: Redis,
        sessions: async_sessionmaker[AsyncSession],
        config: ConsumerConfig,
    ) -> None:
        self.redis = redis
        self.sessions = sessions
        self.config = config

    async def ensure_group(self) -> None:
        """Create the stream and group if this is the first worker ever."""
        try:
            await self.redis.xgroup_create(
                self.config.stream, self.config.group, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_once(self, *, block: bool = True) -> ConsumeStats:
        """Read and process one batch of new entries."""
        reply = await self.redis.xreadgroup(  # RESP2: [[stream, entries]]
            self.config.group,
            self.config.name,
            {self.config.stream: ">"},
            count=self.config.batch,
            block=self.config.block_ms if block else None,
        )
        entries = cast(list[list[Any]], reply)[0][1] if reply else []
        return await self._process(entries)

    async def reclaim_once(self) -> ConsumeStats:
        """Take over entries another worker read but never acknowledged, and retry them."""
        reply = await self.redis.xautoclaim(
            self.config.stream,
            self.config.group,
            self.config.name,
            min_idle_time=self.config.reclaim_idle_ms,
            start_id="0-0",
            count=self.config.batch,
        )
        entries: list[Entry] = [e for e in reply[1] if e[1]]  # deleted entries come back empty
        if not entries:
            return ConsumeStats()
        deliveries = await self._delivery_counts([e[0] for e in entries])
        stats = ConsumeStats()
        retry = []
        for entry in entries:
            if deliveries.get(entry[0], 0) > self.config.max_deliveries:
                await self._dead_letter(entry, f"failed {self.config.max_deliveries} times")
                stats.dead += 1
            else:
                retry.append(entry)
        more = await self._process(retry)
        return ConsumeStats(
            stats.written + more.written,
            stats.duplicates + more.duplicates,
            stats.dead + more.dead,
            stats.failed + more.failed,
        )

    async def trim(self) -> int:
        """Drop entries every consumer is done with; returns how many were removed.

        Everything before the oldest unacknowledged entry is done; with nothing pending,
        everything up to the last delivered entry is.
        """
        groups = await self.redis.xinfo_groups(self.config.stream)
        group = next((g for g in groups if _text(g["name"]) == self.config.group), None)
        if group is None:
            return 0
        pending = await self.redis.xpending(self.config.stream, self.config.group)
        floor = pending["min"] if pending["pending"] else group["last-delivered-id"]
        removed: int = await self.redis.xtrim(self.config.stream, minid=floor, approximate=False)
        return removed

    async def _process(self, entries: Sequence[Entry]) -> ConsumeStats:
        stats = ConsumeStats()
        for entry_id, fields in entries:
            try:
                message = decode(fields)
            except MalformedMessageError as exc:
                await self._dead_letter((entry_id, fields), str(exc))
                stats.dead += 1
                continue
            try:
                written, total = await self._write(message)
            except Exception:
                # Left unacknowledged: retried via reclaim, dead-lettered if it keeps failing.
                log.exception("writing stream entry %s failed", entry_id.decode())
                stats.failed += 1
                continue
            await self.redis.xack(self.config.stream, self.config.group, entry_id)
            stats.written += written
            stats.duplicates += total - written
        return stats

    async def _write(self, message: PredictionMessage | LabelMessage) -> tuple[int, int]:
        today = datetime.now(UTC).date()
        async with self.sessions() as session, session.begin():
            if isinstance(message, PredictionMessage):
                written, new_days = await insert_predictions(
                    session, message.model_id, message.version_id, message.records
                )
                await mark_dirty(
                    session,
                    (
                        (message.version_id, d)
                        for day in new_days
                        for d in affected_days(day, today)
                    ),
                )
                return written, len(message.records)
            changed = await upsert_labels(session, message.model_id, message.labels)
            await mark_dirty(
                session,
                (
                    (version_id, d)
                    for version_id, days in changed.items()
                    for day in days
                    for d in affected_days(day, today)
                ),
            )
            return len(message.labels), len(message.labels)

    async def _delivery_counts(self, ids: list[bytes]) -> dict[bytes, int]:
        counts: dict[bytes, int] = {}
        for entry_id in ids:
            pending: list[dict[str, Any]] = await self.redis.xpending_range(
                self.config.stream, self.config.group, min=entry_id, max=entry_id, count=1
            )
            if pending:
                counts[entry_id] = int(pending[0]["times_delivered"])
        return counts

    async def _dead_letter(self, entry: Entry, reason: str) -> None:
        entry_id, fields = entry
        log.error("dead-lettering stream entry %s: %s", entry_id.decode(), reason)
        record: dict[Any, Any] = {**fields, b"source_id": entry_id, b"reason": reason.encode()}
        await self.redis.xadd(
            self.config.dead_letter,
            record,
            maxlen=100_000,
            approximate=True,
        )
        await self.redis.xack(self.config.stream, self.config.group, entry_id)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
