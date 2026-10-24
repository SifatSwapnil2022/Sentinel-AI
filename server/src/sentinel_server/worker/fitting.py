"""Fit monitors for newly uploaded model versions."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_core.errors import SentinelError
from sentinel_server.analysis import FeatureSchema, Monitors
from sentinel_server.db.models import Model, ModelVersion, VersionStatus
from sentinel_server.reference import ReferenceError, parse_reference

log = logging.getLogger(__name__)


async def fit_pending(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Fit every pending version, one transaction each; returns how many were processed."""
    done = 0
    while True:
        async with sessions() as session, session.begin():
            version = await session.scalar(
                select(ModelVersion)
                .where(ModelVersion.status == VersionStatus.PENDING)
                .order_by(ModelVersion.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if version is None:
                return done
            await _fit(session, version)
            done += 1


async def _fit(session: AsyncSession, version: ModelVersion) -> None:
    started = datetime.now(UTC)
    try:
        monitors = await asyncio.to_thread(_fit_monitors, version)
    except (ReferenceError, SentinelError, ValueError) as exc:
        version.status = VersionStatus.FAILED
        version.error = str(exc)
        log.warning("fitting %s %s failed: %s", version.model_id, version.version, exc)
        return

    version.monitors = monitors.to_bytes()
    version.summary = {
        **monitors.summary(),
        "referenceAccuracy": monitors.reference_accuracy,
        "coreVersion": monitors.core_version,
    }
    version.status = VersionStatus.READY
    version.error = None
    version.fitted_at = datetime.now(UTC)
    if version.activate:
        await session.execute(
            update(Model).where(Model.id == version.model_id).values(active_version_id=version.id)
        )
    # Predictions that arrived before the fit are already marked dirty and are now eligible;
    # nudge their timestamps so they are computed straight away.
    await session.execute(
        text("UPDATE dirty_days SET marked_at = now() - interval '1 hour' WHERE version_id = :v"),
        {"v": version.id},
    )
    log.info(
        "fitted %s %s in %.1fs",
        version.model_id,
        version.version,
        (datetime.now(UTC) - started).total_seconds(),
    )


def _fit_monitors(version: ModelVersion) -> Monitors:
    if version.reference_csv is None:
        raise ReferenceError(["reference data is missing"])
    reference = parse_reference(
        version.reference_csv,
        score_column=version.score_column,
        label_column=version.label_column,
        prediction_column=version.prediction_column,
    )
    return Monitors.fit(
        reference.features,
        reference.outcome,
        reference.score,
        reference.prediction,
        decision_threshold=version.decision_threshold,
        schema=FeatureSchema.from_json(version.feature_schema),
    )
