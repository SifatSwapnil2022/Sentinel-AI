"""Run the bundled migrations without needing ``alembic.ini`` on disk."""

from __future__ import annotations

from alembic import command
from alembic.config import Config


def _config(url: str | None) -> Config:
    config = Config()
    config.set_main_option("script_location", "sentinel_server:migrations")
    if url:
        config.attributes["url"] = url
    return config


def upgrade(url: str | None = None, revision: str = "head") -> None:
    """Migrate the database up to ``revision``. Blocking: call from a thread inside async code."""
    command.upgrade(_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    """Migrate the database down to ``revision``."""
    command.downgrade(_config(url), revision)
