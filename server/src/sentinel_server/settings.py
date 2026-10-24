"""Runtime configuration, read from ``SENTINEL_*`` environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every knob the API and worker read. Defaults suit local development."""

    model_config = SettingsConfigDict(env_prefix="SENTINEL_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sentinel@127.0.0.1:5433/sentinel"
    redis_url: str = "redis://127.0.0.1:6380/0"

    ingest_stream: str = "sentinel:ingest"
    dead_letter_stream: str = "sentinel:ingest:dead"
    consumer_group: str = "writers"

    max_batch: int = Field(default=500, ge=1, le=10_000)
    """Most records accepted in one ingest request."""
    max_stream_length: int = Field(default=20_000, ge=100)
    """Ingest returns 503 once this many batches are waiting, so a slow database pushes back on
    clients instead of growing Redis without bound."""
    max_reference_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    max_clock_skew_seconds: int = 300
    retention_days: int = Field(default=90, ge=8)
    """Predictions older than this are rejected at ingest and their partitions dropped."""

    public_read: bool = False
    """Serve the read endpoints without a key, for a public demo dashboard."""
    cors_origins: list[str] = Field(default_factory=list)

    window_days: int = Field(default=30, ge=7, le=90)
    """Days shown on the dashboard."""

    worker_batch: int = Field(default=50, ge=1)
    """Stream messages a worker reads at once."""
    worker_block_ms: int = 2000
    reclaim_idle_ms: int = 60_000
    """A message unacknowledged this long is taken over by another worker."""
    max_deliveries: int = 5
    """After this many failed attempts a message goes to the dead-letter stream."""
    recompute_debounce_seconds: float = 2.0
    """Wait this long after a day is marked dirty, so a burst of ingest is computed once."""
    monitor_cache_size: int = 16


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings."""
    return Settings()
