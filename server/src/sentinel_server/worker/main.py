"""The background worker: ingest writer, fitting, recomputation and retention in one process.

Every loop survives its own failures (logged, then retried after a pause), so a bad batch or a
database blip never takes the worker down. Run several workers for throughput: stream entries
are shared through the consumer group and every database job claims rows with
``SKIP LOCKED``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from sentinel_server.db.session import make_engine, make_sessionmaker
from sentinel_server.logs import configure_logging
from sentinel_server.settings import Settings, get_settings

from .consumer import Consumer, ConsumerConfig
from .fitting import fit_pending
from .monitors_cache import MonitorCache
from .recompute import RecomputeConfig, recompute_pending
from .retention import apply_retention

log = logging.getLogger(__name__)


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    """Run every loop until ``stop`` is set."""
    engine = make_engine(settings.database_url, pool_size=5)
    sessions = make_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url)
    consumer = Consumer(
        redis,
        sessions,
        ConsumerConfig(
            stream=settings.ingest_stream,
            dead_letter=settings.dead_letter_stream,
            group=settings.consumer_group,
            batch=settings.worker_batch,
            block_ms=settings.worker_block_ms,
            reclaim_idle_ms=settings.reclaim_idle_ms,
            max_deliveries=settings.max_deliveries,
        ),
    )
    cache = MonitorCache(settings.monitor_cache_size)
    recompute = RecomputeConfig(settings.recompute_debounce_seconds, settings.window_days)
    await consumer.ensure_group()
    log.info("worker %s started", consumer.config.name)

    async def consume() -> None:
        await consumer.consume_once()

    async def reclaim() -> None:
        await consumer.reclaim_once()

    async def trim() -> None:
        await consumer.trim()

    async def fit() -> None:
        await fit_pending(sessions)

    async def compute() -> None:
        await recompute_pending(sessions, cache, recompute)

    async def retain() -> None:
        await apply_retention(sessions, settings.retention_days)

    loops = [
        _forever("consume", consume, 0, stop),
        _forever("reclaim", reclaim, 15, stop),
        _forever("trim", trim, 5, stop),
        _forever("fit", fit, 2, stop),
        _forever("recompute", compute, 1, stop),
        _forever("retention", retain, 3600, stop),
    ]
    try:
        await asyncio.gather(*loops)
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("worker stopped")


async def _forever(
    name: str, job: Callable[[], Awaitable[None]], every: float, stop: asyncio.Event
) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            await job()
            backoff = 1.0
            delay = every
        except Exception:
            log.exception("%s loop failed; retrying in %.0fs", name, backoff)
            delay, backoff = backoff, min(backoff * 2, 60)
        if delay:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)


def run() -> None:
    """Entry point for ``sentinel-worker``."""
    settings = get_settings()
    configure_logging()

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_worker(settings, stop)

    asyncio.run(main())
