"""Ingest: validate, fill in defaults, and queue on the stream. The worker does the writing.

Responses are ``202 Accepted``: the batch is durable in Redis and will be written, but isn't
yet visible in reads. When the stream backs up past ``max_stream_length`` the API answers
``503`` with ``Retry-After`` rather than letting Redis grow without bound.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_server.contracts import (
    Accepted,
    LabelBatch,
    LabelMessage,
    PredictionBatch,
    PredictionMessage,
    PredictionRecord,
    encode,
)
from sentinel_server.db.models import Model, ModelVersion, VersionStatus
from sentinel_server.settings import Settings

from ..deps import CanIngest, RedisDep, Session, SettingsDep
from ..errors import ApiError

router = APIRouter(prefix="/v1/ingest", tags=["ingest"], dependencies=[CanIngest])

RETRY_AFTER_SECONDS = 5


@dataclass(frozen=True)
class _Target:
    version_id: int
    threshold: float
    features: frozenset[str]


class TargetCache:
    """(model, version) → where predictions go.

    Entries live briefly, so activating a new version takes effect within ``ttl`` seconds
    without a registry lookup on every batch.
    """

    def __init__(self, ttl: float = 30.0) -> None:
        self.ttl = ttl
        self._items: dict[tuple[str, str | None], tuple[float, _Target]] = {}

    async def resolve(self, session: AsyncSession, model_id: str, version: str | None) -> _Target:
        """The version a batch belongs to, or a 404/409 problem."""
        key = (model_id, version)
        hit = self._items.get(key)
        if hit is not None and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        target = await _lookup(session, model_id, version)
        if len(self._items) > 10_000:
            self._items.clear()
        self._items[key] = (time.monotonic(), target)
        return target


def get_targets(request: Request) -> TargetCache:
    """The app's target cache."""
    cache: TargetCache = request.app.state.targets
    return cache


Targets = Annotated[TargetCache, Depends(get_targets)]


async def _lookup(session: AsyncSession, model_id: str, version: str | None) -> _Target:
    model = await session.get(Model, model_id)
    if model is None:
        raise ApiError(
            404, "unknown-model", "Unknown model", f"No model '{model_id}' is registered."
        )
    query = select(
        ModelVersion.id,
        ModelVersion.decision_threshold,
        ModelVersion.feature_schema,
        ModelVersion.status,
        ModelVersion.version,
    )
    if version is None:
        if model.active_version_id is None:
            raise ApiError(
                409,
                "no-active-version",
                "No active version",
                f"Model '{model_id}' has no active version yet; name the version explicitly "
                "or wait for its reference data to finish fitting.",
            )
        query = query.where(ModelVersion.id == model.active_version_id)
    else:
        query = query.where(ModelVersion.model_id == model_id, ModelVersion.version == version)
    row = (await session.execute(query)).first()
    if row is None:
        raise ApiError(
            404,
            "unknown-version",
            "Unknown version",
            f"Model '{model_id}' has no version '{version}'.",
        )
    if row.status == VersionStatus.FAILED:
        raise ApiError(
            409,
            "version-failed",
            "Version failed to fit",
            f"Version '{row.version}' of '{model_id}' failed to fit; upload its reference again.",
        )
    return _Target(
        version_id=row.id,
        threshold=row.decision_threshold,
        features=frozenset(item["name"] for item in row.feature_schema),
    )


async def _check_backlog(redis: RedisDep, settings: Settings) -> None:
    if await redis.xlen(settings.ingest_stream) >= settings.max_stream_length:
        raise ApiError(
            503,
            "backpressure",
            "Ingest is backed up",
            "Too many batches are waiting to be written. Retry shortly.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )


def _check_size(n: int, settings: Settings) -> None:
    if n > settings.max_batch:
        raise ApiError(
            413,
            "batch-too-large",
            "Batch too large",
            f"{n} records sent; at most {settings.max_batch} are accepted per request.",
        )


@router.post("/predictions", status_code=status.HTTP_202_ACCEPTED)
async def ingest_predictions(
    batch: PredictionBatch,
    session: Session,
    redis: RedisDep,
    settings: SettingsDep,
    targets: Targets,
) -> Accepted:
    """Queue a batch of predictions."""
    _check_size(len(batch.predictions), settings)
    target = await targets.resolve(session, batch.model_id, batch.version)
    await session.close()  # done with the database; don't hold a connection while queueing

    now = datetime.now(UTC)
    newest = now + timedelta(seconds=settings.max_clock_skew_seconds)
    oldest = now - timedelta(days=settings.retention_days)
    problems: list[dict[str, object]] = []
    records = []
    for i, p in enumerate(batch.predictions):
        ts = p.ts or now
        unknown = sorted(set(p.features) - target.features)
        if unknown:
            problems.append(
                {"index": i, "message": f"unknown feature(s): {', '.join(unknown[:10])}"}
            )
        if ts > newest:
            problems.append({"index": i, "message": "timestamp is in the future"})
        elif ts < oldest:
            problems.append(
                {"index": i, "message": f"timestamp is older than {settings.retention_days} days"}
            )
        records.append(
            PredictionRecord(
                request_id=p.request_id,
                ts=ts,
                features=p.features,
                score=p.score,
                prediction=p.prediction
                if p.prediction is not None
                else int(p.score >= target.threshold),
                latency_ms=p.latency_ms,
            )
        )
    if problems:
        raise ApiError(
            422,
            "invalid-records",
            "Invalid records",
            f"{len(problems)} problem(s) in the batch; nothing was queued.",
            errors=problems[:50],
        )

    await _check_backlog(redis, settings)
    message = PredictionMessage(batch.model_id, target.version_id, records)
    entry = await redis.xadd(settings.ingest_stream, encode(message))  # type: ignore[arg-type]
    return Accepted(accepted=len(records), queued_as=_text(entry))


@router.post("/labels", status_code=status.HTTP_202_ACCEPTED)
async def ingest_labels(
    batch: LabelBatch, session: Session, redis: RedisDep, settings: SettingsDep
) -> Accepted:
    """Queue a batch of ground-truth labels."""
    _check_size(len(batch.labels), settings)
    if await session.get(Model, batch.model_id) is None:
        raise ApiError(
            404, "unknown-model", "Unknown model", f"No model '{batch.model_id}' is registered."
        )
    await session.close()
    await _check_backlog(redis, settings)
    message = LabelMessage(batch.model_id, [(x.request_id, x.label) for x in batch.labels])
    entry = await redis.xadd(settings.ingest_stream, encode(message))  # type: ignore[arg-type]
    return Accepted(accepted=len(batch.labels), queued_as=_text(entry))


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
