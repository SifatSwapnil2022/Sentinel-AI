"""One-line structured logs, readable by people and parsable by log tooling."""

from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    """Configure the root logger from ``SENTINEL_LOG_LEVEL`` (default INFO)."""
    logging.basicConfig(
        level=os.environ.get("SENTINEL_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
