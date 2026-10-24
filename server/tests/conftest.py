"""Server tests run against real Postgres and Redis.

Point them at disposable instances with ``SENTINEL_TEST_DATABASE_URL`` and
``SENTINEL_TEST_REDIS_URL``: every test truncates the database and flushes the Redis database.
Without them the tests are skipped, unless ``SENTINEL_REQUIRE_SERVICES=1`` (set in CI), where a
missing service is an error rather than a silent skip.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sentinel_server.api.main import create_app
from sentinel_server.db import migrate
from sentinel_server.db.models import Scope
from sentinel_server.db.session import make_engine, make_sessionmaker
from sentinel_server.keys import create_key
from sentinel_server.settings import Settings
from support import Keys, Worker

DATABASE_URL = os.environ.get(
    "SENTINEL_TEST_DATABASE_URL", "postgresql+asyncpg://sentinel@127.0.0.1:5433/sentinel_test"
)
REDIS_URL = os.environ.get("SENTINEL_TEST_REDIS_URL", "redis://127.0.0.1:6380/15")
REQUIRE = os.environ.get("SENTINEL_REQUIRE_SERVICES") == "1"

TABLES = (
    "incidents, model_documents, daily_windows, dirty_days, labels, predictions, "
    "model_versions, models, api_keys"
)


async def _reachable() -> str | None:
    engine = make_engine(DATABASE_URL, pool_size=1)
    redis = Redis.from_url(REDIS_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await redis.ping()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    finally:
        await redis.aclose()
        await engine.dispose()
    return None


@pytest.fixture(scope="session")
def services() -> None:
    """Reachable, freshly migrated Postgres and Redis; requested by every fixture that uses them."""
    problem = asyncio.run(_reachable())
    if problem is not None:
        if REQUIRE:
            pytest.fail(f"test services unavailable: {problem}", pytrace=False)
        pytest.skip(f"Postgres/Redis for server tests not reachable ({problem})")
    migrate.downgrade(DATABASE_URL)
    migrate.upgrade(DATABASE_URL)


@pytest.fixture
def settings(services: None) -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        redis_url=REDIS_URL,
        ingest_stream="test:ingest",
        dead_letter_stream="test:ingest:dead",
        consumer_group="test-writers",
        recompute_debounce_seconds=0,
        reclaim_idle_ms=0,
        max_deliveries=2,
    )


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(settings.database_url, pool_size=4)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        partitions = await conn.execute(
            text(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'predictions'"
            )
        )
        for (name,) in partitions.all():
            await conn.execute(text(f"DROP TABLE {name}"))
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(engine)


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = Redis.from_url(settings.redis_url)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def client(
    settings: Settings, engine: AsyncEngine, redis: Redis
) -> AsyncIterator[httpx.AsyncClient]:
    del engine, redis  # requested for their clean-state side effects
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def keys(sessions: async_sessionmaker[AsyncSession]) -> Keys:
    async with sessions() as session:
        out = {}
        for scope in Scope:
            secret, _ = await create_key(session, f"test-{scope.value}", [scope])
            out[scope.value] = {"Authorization": f"Bearer {secret}"}
        await session.commit()
    return Keys(admin=out["admin"], ingest=out["ingest"], read=out["read"])


@pytest.fixture
async def worker(
    redis: Redis, sessions: async_sessionmaker[AsyncSession], settings: Settings
) -> Worker:
    w = Worker(redis, sessions, settings)
    await w.consumer.ensure_group()
    return w
