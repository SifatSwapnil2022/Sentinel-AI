from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import numpy as np
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.contracts import PredictionMessage, PredictionRecord, encode
from sentinel_server.db.models import DailyWindow, DirtyDay, Label, Prediction
from sentinel_server.db.partitions import partition_name
from sentinel_server.settings import Settings
from sentinel_server.worker.recompute import chunk_days
from sentinel_server.worker.retention import apply_retention
from support import (
    Keys,
    Worker,
    prediction_records,
    register,
    send_labels,
    send_predictions,
    traffic,
)

TODAY = datetime.now(UTC).date()


@pytest.fixture
async def ready(client: httpx.AsyncClient, keys: Keys, worker: Worker) -> None:
    assert (await register(client, keys.admin)).status_code == 202
    await worker.fit()


async def count(sessions: async_sessionmaker[AsyncSession], model: type) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def dirty(sessions: async_sessionmaker[AsyncSession]) -> list[date]:
    async with sessions() as session:
        return sorted(await session.scalars(select(DirtyDay.day)))


async def test_writes_are_idempotent(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    sessions: async_sessionmaker[AsyncSession],
    ready: None,
) -> None:
    records = prediction_records(traffic(np.random.default_rng(0), 120), TODAY - timedelta(days=2))
    await send_predictions(client, keys.ingest, "loans", records)
    first = await worker.drain()
    assert (first.written, first.duplicates) == (120, 0)
    # a client retry sends the same batch again: nothing new is written
    await send_predictions(client, keys.ingest, "loans", records)
    second = await worker.drain()
    assert (second.written, second.duplicates) == (0, 120)
    assert await count(sessions, Prediction) == 120


async def test_partitions_and_dirty_days(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    sessions: async_sessionmaker[AsyncSession],
    ready: None,
) -> None:
    rng = np.random.default_rng(1)
    days = [TODAY - timedelta(days=3), TODAY - timedelta(days=1)]
    for day in days:
        await send_predictions(
            client, keys.ingest, "loans", prediction_records(traffic(rng, 30), day)
        )
    await worker.drain()
    async with sessions() as session:
        tables = set(
            await session.scalars(
                text("SELECT tablename FROM pg_tables WHERE tablename LIKE 'predictions_%'")
            )
        )
    assert tables == {partition_name(d) for d in days}
    # each day dirties itself and the later days whose rolling label check includes it
    assert await dirty(sessions) == [TODAY - timedelta(days=k) for k in (3, 2, 1, 0)]


async def test_labels_in_either_order(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    sessions: async_sessionmaker[AsyncSession],
    ready: None,
) -> None:
    day = TODAY - timedelta(days=1)
    records = prediction_records(traffic(np.random.default_rng(2), 100), day, with_label=True)
    # half the labels arrive before their predictions
    early = [(r["request_id"], r["label"]) for r in records[:50]]
    await send_labels(client, keys.ingest, "loans", early)
    await worker.drain()
    assert await count(sessions, Label) == 50
    assert await dirty(sessions) == []  # no predictions yet, nothing to recompute

    await send_predictions(client, keys.ingest, "loans", records)
    await send_labels(
        client, keys.ingest, "loans", [(r["request_id"], r["label"]) for r in records[50:]]
    )
    await worker.settle()
    async with sessions() as session:
        doc = await session.scalar(select(DailyWindow.doc).where(DailyWindow.day == day))
    assert doc is not None
    assert doc["labelCoverage"] == 1.0
    assert doc["measured"] is not None


async def test_changed_label_recomputes_its_days(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    sessions: async_sessionmaker[AsyncSession],
    ready: None,
) -> None:
    day = TODAY - timedelta(days=2)
    records = prediction_records(traffic(np.random.default_rng(3), 60), day, with_label=True)
    await send_predictions(client, keys.ingest, "loans", records)
    labels = [(r["request_id"], r["label"]) for r in records]
    await send_labels(client, keys.ingest, "loans", labels)
    await worker.settle()
    assert await dirty(sessions) == []

    await send_labels(client, keys.ingest, "loans", labels)  # same labels again: no change
    await worker.drain()
    assert await dirty(sessions) == []

    await send_labels(client, keys.ingest, "loans", [(labels[0][0], 1 - labels[0][1])])
    await worker.drain()
    assert await dirty(sessions) == [day, day + timedelta(days=1), TODAY]


async def test_undecodable_entry_is_dead_lettered(
    worker: Worker, redis: Redis, settings: Settings
) -> None:
    await redis.xadd(settings.ingest_stream, {"kind": "predictions", "v": "1", "body": "{oops"})
    await redis.xadd(settings.ingest_stream, {"kind": "mystery", "v": "1", "body": "{}"})
    stats = await worker.drain()
    assert stats.dead == 2
    dead = await redis.xrange(settings.dead_letter_stream)
    assert [e[1][b"reason"].startswith(b"cannot decode") for e in dead] == [True, False]
    pending = await redis.xpending(settings.ingest_stream, settings.consumer_group)
    assert pending["pending"] == 0


async def test_failing_entry_is_retried_then_dead_lettered(
    worker: Worker, redis: Redis, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # A version that doesn't exist: the dirty-day foreign key fails on every attempt.
    record = PredictionRecord("x", datetime.now(UTC), {"income": 1.0}, 0.5, 1, None)
    await redis.xadd(settings.ingest_stream, encode(PredictionMessage("loans", 999, [record])))  # type: ignore[arg-type]
    first = await worker.drain()
    assert first.failed == 1
    assert "writing stream entry" in caplog.text

    # Delivery 1 was the read above; each reclaim is one more. Retried while the count is
    # within max_deliveries, dead-lettered on the reclaim that exceeds it.
    outcomes = [await worker.consumer.reclaim_once() for _ in range(settings.max_deliveries)]
    assert [(o.failed, o.dead) for o in outcomes] == [(1, 0)] * (settings.max_deliveries - 1) + [
        (0, 1)
    ]
    (dead,) = await redis.xrange(settings.dead_letter_stream)
    assert dead[1][b"reason"] == f"failed {settings.max_deliveries} times".encode()
    pending = await redis.xpending(settings.ingest_stream, settings.consumer_group)
    assert pending["pending"] == 0


async def test_stream_is_trimmed_to_the_backlog(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    redis: Redis,
    settings: Settings,
    ready: None,
) -> None:
    records = prediction_records(traffic(np.random.default_rng(5), 300), TODAY)
    await send_predictions(client, keys.ingest, "loans", records, batch=50)
    assert await redis.xlen(settings.ingest_stream) == 6
    await worker.drain()
    await worker.consumer.trim()
    # Only the last delivered entry may remain; without trimming, the stream would grow
    # until backpressure refused all ingest.
    assert await redis.xlen(settings.ingest_stream) <= 1

    # an unacknowledged entry, and everything after it, is kept for redelivery
    bad = PredictionRecord("x", datetime.now(UTC), {"income": 1.0}, 0.5, 1, None)
    await redis.xadd(settings.ingest_stream, encode(PredictionMessage("loans", 999, [bad])))  # type: ignore[arg-type]
    await send_predictions(client, keys.ingest, "loans", records[:10])
    stats = await worker.drain()
    assert stats.failed == 1
    await worker.consumer.trim()
    assert await redis.xlen(settings.ingest_stream) == 2


async def test_retention_drops_old_partitions(
    client: httpx.AsyncClient,
    keys: Keys,
    worker: Worker,
    sessions: async_sessionmaker[AsyncSession],
    ready: None,
) -> None:
    rng = np.random.default_rng(4)
    old, recent = TODAY - timedelta(days=20), TODAY - timedelta(days=2)
    for day in (old, recent):
        await send_predictions(
            client, keys.ingest, "loans", prediction_records(traffic(rng, 10), day)
        )
    await worker.settle()
    dropped = await apply_retention(sessions, retention_days=10)
    assert dropped == [partition_name(old)]
    assert await count(sessions, Prediction) == 10
    async with sessions() as session:
        days = set(await session.scalars(select(DailyWindow.day)))
    assert old not in days
    assert recent in days


def test_chunking() -> None:
    d = date(2026, 10, 1)
    days = [
        d,
        d + timedelta(days=1),
        d + timedelta(days=13),
        d + timedelta(days=14),
        d + timedelta(days=40),
    ]
    assert chunk_days(days, 14) == [days[:3], days[3:4], days[4:]]
