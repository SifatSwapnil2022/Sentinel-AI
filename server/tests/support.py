"""Shared test code: synthetic data, API helpers, and a hand-driven worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import numpy as np
import pandas as pd
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.settings import Settings
from sentinel_server.worker.consumer import Consumer, ConsumerConfig, ConsumeStats
from sentinel_server.worker.fitting import fit_pending
from sentinel_server.worker.monitors_cache import MonitorCache
from sentinel_server.worker.recompute import RecomputeConfig, recompute_pending

REGIONS = ["north", "south", "east", "west"]


def traffic(rng: np.random.Generator, n: int, *, broken: bool = False) -> pd.DataFrame:
    """Rows with a score and a label. ``broken`` makes the model wrong for region 'east'."""
    frame = pd.DataFrame(
        {
            "income": rng.lognormal(10.5, 0.5, n).round(2),
            "region": rng.choice(REGIONS, n),
            "tenure": rng.integers(0, 120, n),
        }
    )
    logit = 0.9 * (np.log(frame["income"]) - 10.5) / 0.5 - 0.02 * (frame["tenure"] - 60)
    score = 1 / (1 + np.exp(-logit))
    truth = score.copy()
    if broken:
        east = (frame["region"] == "east").to_numpy()
        truth[east] = 1 - truth[east]
    label = rng.binomial(1, truth)
    return frame.assign(score=score.round(6), label=label)


def reference_csv(rng: np.random.Generator, n: int = 1500) -> bytes:
    return traffic(rng, n).to_csv(index=False).encode()


async def register(
    client: httpx.AsyncClient,
    admin: dict[str, str],
    model_id: str = "loans",
    *,
    version: str = "v1",
    csv: bytes | None = None,
    rng: np.random.Generator | None = None,
    **form: Any,
) -> httpx.Response:
    """Register a model and upload a version's reference; returns the upload response."""
    r = await client.put(
        f"/v1/registry/models/{model_id}",
        json={"name": model_id, "team": "Risk", "label_delay_days": 3},
        headers=admin,
    )
    assert r.status_code in (200, 201), r.text
    data = csv if csv is not None else reference_csv(rng or np.random.default_rng(0))
    return await client.post(
        f"/v1/registry/models/{model_id}/versions",
        data={"version": version, **{k: str(v) for k, v in form.items()}},
        files={"reference": ("reference.csv", data, "text/csv")},
        headers=admin,
    )


def at(day: date, seconds: float = 0.0) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC) + timedelta(seconds=seconds)


def prediction_records(
    frame: pd.DataFrame, day: date, *, prefix: str = "r", with_label: bool = False
) -> list[dict[str, Any]]:
    """API records for a day's rows, spread evenly over the first hours of the day."""
    records = []
    for i, row in enumerate(frame.itertuples(index=False)):
        record: dict[str, Any] = {
            "request_id": f"{prefix}-{day:%Y%m%d}-{i:06d}",
            "ts": at(day, i).isoformat(),
            "features": {"income": row.income, "region": row.region, "tenure": int(row.tenure)},
            "score": float(row.score),
            "latency_ms": 20.0 + i % 7,
        }
        if with_label:
            record["label"] = int(row.label)
        records.append(record)
    return records


async def send_predictions(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    model_id: str,
    records: list[dict[str, Any]],
    *,
    batch: int = 500,
) -> None:
    for start in range(0, len(records), batch):
        chunk = [
            {k: v for k, v in r.items() if k != "label"} for r in records[start : start + batch]
        ]
        r = await client.post(
            "/v1/ingest/predictions",
            json={"model_id": model_id, "predictions": chunk},
            headers=headers,
        )
        assert r.status_code == 202, r.text


async def send_labels(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    model_id: str,
    labels: list[tuple[str, int]],
    *,
    batch: int = 500,
) -> None:
    for start in range(0, len(labels), batch):
        chunk = [{"request_id": rid, "label": y} for rid, y in labels[start : start + batch]]
        r = await client.post(
            "/v1/ingest/labels", json={"model_id": model_id, "labels": chunk}, headers=headers
        )
        assert r.status_code == 202, r.text


@dataclass(frozen=True)
class Keys:
    admin: dict[str, str]
    ingest: dict[str, str]
    read: dict[str, str]


class Worker:
    """Drives the worker's jobs synchronously, so tests control when each step runs."""

    def __init__(
        self, redis: Redis, sessions: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self.sessions = sessions
        self.consumer = Consumer(
            redis,
            sessions,
            ConsumerConfig(
                stream=settings.ingest_stream,
                dead_letter=settings.dead_letter_stream,
                group=settings.consumer_group,
                batch=100,
                reclaim_idle_ms=settings.reclaim_idle_ms,
                max_deliveries=settings.max_deliveries,
            ),
        )
        self.cache = MonitorCache(4)
        self.config = RecomputeConfig(debounce_seconds=0, window_days=settings.window_days)

    async def drain(self) -> ConsumeStats:
        """Write everything queued."""
        await self.consumer.ensure_group()
        total = ConsumeStats()
        while True:
            stats = await self.consumer.consume_once(block=False)
            if stats == ConsumeStats():
                return total
            total.written += stats.written
            total.duplicates += stats.duplicates
            total.dead += stats.dead
            total.failed += stats.failed

    async def fit(self) -> int:
        return await fit_pending(self.sessions)

    async def recompute(self, today: date | None = None) -> int:
        return await recompute_pending(self.sessions, self.cache, self.config, today=today)

    async def settle(self, today: date | None = None) -> None:
        """Everything the worker would do eventually: write, fit, recompute."""
        await self.drain()
        await self.fit()
        await self.recompute(today)
