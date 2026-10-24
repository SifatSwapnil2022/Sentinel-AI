"""Engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str, *, pool_size: int = 10) -> AsyncEngine:
    """An engine with health-checked pooled connections."""
    return create_async_engine(url, pool_size=pool_size, max_overflow=pool_size, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Sessions that keep loaded objects usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
