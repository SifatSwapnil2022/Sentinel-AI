"""Alembic environment: runs migrations over the async engine.

The database URL is taken, in order, from ``config.attributes["url"]`` (set by
``sentinel_server.db.migrate``), then ``SENTINEL_DATABASE_URL``.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from sentinel_server.db.models import Base
from sentinel_server.settings import get_settings

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return str(config.attributes.get("url") or get_settings().database_url)


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_online())
