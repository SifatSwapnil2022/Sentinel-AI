"""Recompute dirty days, then rebuild the model's documents and incident state.

A unit of work is one model version: claim its dirty days, recompute each day's document from
the predictions and labels in storage, then (if the version is active) rebuild the model page,
the overview row and the incident. Claim, compute and write share one transaction, so a crash
loses nothing: the claim rolls back and the days stay dirty. A day marked dirty again while it
is being computed waits on the row lock and is queued afresh once this transaction commits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.analysis import (
    CONCEPT_WINDOW_DAYS,
    DayData,
    ModelInfo,
    Monitors,
    compute_day,
    concat,
    evaluate,
    incident_document,
    investigate,
    model_document,
    model_summary,
)
from sentinel_server.db.models import (
    DailyWindow,
    Incident,
    Model,
    ModelDocument,
    ModelVersion,
    VersionStatus,
)
from sentinel_server.db.store import load_days

from .monitors_cache import MonitorCache

log = logging.getLogger(__name__)

CHUNK_DAYS = 14
"""Dirty days are loaded in chunks spanning at most this many days, plus the label lookback."""

INVESTIGATION_MAX_DAYS = 14
"""An incident's investigation covers at most this many days, bounding its cost."""


@dataclass(frozen=True)
class RecomputeConfig:
    """What recomputation needs from settings."""

    debounce_seconds: float
    window_days: int


@dataclass(frozen=True)
class _Version:
    id: int
    model_id: str
    version: str
    fitted_at: datetime | None


async def recompute_pending(
    sessions: async_sessionmaker[AsyncSession],
    cache: MonitorCache,
    config: RecomputeConfig,
    *,
    today: date | None = None,
) -> int:
    """Process every version with settled dirty days; returns how many days were recomputed."""
    total = 0
    while True:
        async with sessions() as session, session.begin():
            claimed = await _claim_one_version(session, config.debounce_seconds)
            if claimed is None:
                return total
            version, days = claimed
            await _recompute_version(
                session, cache, config, version, days, today or datetime.now(UTC).date()
            )
            total += len(days)


async def _claim_one_version(
    session: AsyncSession, debounce_seconds: float
) -> tuple[_Version, list[date]] | None:
    """Take the settled dirty days of one fitted version that no other worker holds."""
    row = (
        await session.execute(
            text(
                """
                SELECT v.id, v.model_id, v.version, v.fitted_at FROM dirty_days d
                JOIN model_versions v ON v.id = d.version_id AND v.status = :ready
                WHERE d.marked_at <= now() - make_interval(secs => :debounce)
                ORDER BY d.marked_at LIMIT 1
                FOR UPDATE OF d SKIP LOCKED
                """
            ),
            {"ready": VersionStatus.READY.value, "debounce": debounce_seconds},
        )
    ).first()
    if row is None:
        return None
    version = _Version(id=int(row[0]), model_id=row[1], version=row[2], fitted_at=row[3])
    days = await session.execute(
        text(
            """
            DELETE FROM dirty_days WHERE (version_id, day) IN (
                SELECT version_id, day FROM dirty_days
                WHERE version_id = :v AND marked_at <= now() - make_interval(secs => :debounce)
                FOR UPDATE SKIP LOCKED
            )
            RETURNING day
            """
        ),
        {"v": version.id, "debounce": debounce_seconds},
    )
    return version, sorted(r[0] for r in days)


async def _monitors(session: AsyncSession, cache: MonitorCache, version: _Version) -> Monitors:
    async def load() -> bytes:
        blob = await session.scalar(
            select(ModelVersion.monitors).where(ModelVersion.id == version.id)
        )
        if blob is None:
            raise RuntimeError(f"version {version.id} is ready but has no monitors")
        return blob

    return await cache.get(version.id, version.fitted_at, load)


async def _recompute_version(
    session: AsyncSession,
    cache: MonitorCache,
    config: RecomputeConfig,
    version: _Version,
    days: list[date],
    today: date,
) -> None:
    monitors = await _monitors(session, cache, version)
    for chunk in chunk_days(days, CHUNK_DAYS):
        lookback = chunk[0] - timedelta(days=CONCEPT_WINDOW_DAYS - 1)
        data = await load_days(session, version.id, monitors.schema, lookback, chunk[-1])
        docs = await asyncio.to_thread(_compute_days, monitors, data, chunk)
        for day, doc in docs.items():
            if doc is None:
                await session.execute(
                    delete(DailyWindow).where(
                        DailyWindow.version_id == version.id, DailyWindow.day == day
                    )
                )
                continue
            stmt = insert(DailyWindow).values(version_id=version.id, day=day, doc=doc)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[DailyWindow.version_id, DailyWindow.day],
                    set_={"doc": stmt.excluded.doc, "computed_at": text("now()")},
                )
            )

    model = await session.get_one(Model, version.model_id)
    if model.active_version_id == version.id:
        await refresh_documents(session, model, version, monitors, config.window_days, today)
    log.info("recomputed %d day(s) of %s %s", len(days), model.id, version.version)


def chunk_days(days: list[date], span: int) -> list[list[date]]:
    """Group sorted days into runs covering at most ``span`` calendar days each."""
    chunks: list[list[date]] = []
    for day in days:
        if chunks and (day - chunks[-1][0]).days < span:
            chunks[-1].append(day)
        else:
            chunks.append([day])
    return chunks


def _compute_days(
    monitors: Monitors, data: dict[date, DayData], days: list[date]
) -> dict[date, dict[str, Any] | None]:
    out: dict[date, dict[str, Any] | None] = {}
    for day in days:
        if day not in data:
            out[day] = None
            continue
        first = day - timedelta(days=CONCEPT_WINDOW_DAYS - 1)
        out[day] = compute_day(monitors, [data[d] for d in sorted(data) if first <= d <= day])
    return out


# --------------------------------------------------------------------------- documents


async def refresh_documents(
    session: AsyncSession,
    model: Model,
    version: _Version,
    monitors: Monitors,
    window_days: int,
    today: date,
) -> None:
    """Rebuild a model's page, overview row and incident from its stored day documents."""
    first = today - timedelta(days=window_days - 1)
    docs = list(
        await session.scalars(
            select(DailyWindow.doc)
            .where(DailyWindow.version_id == version.id, DailyWindow.day >= first)
            .order_by(DailyWindow.day)
        )
    )
    open_incident = await _sync_incident(session, model, version, monitors, docs)
    if not docs:
        await session.execute(delete(ModelDocument).where(ModelDocument.model_id == model.id))
        return

    info = ModelInfo(
        id=model.id,
        name=model.name,
        version=version.version,
        team=model.team,
        description=model.description,
        label_delay_days=model.label_delay_days,
    )
    incident_ids = list(
        await session.scalars(
            select(Incident.id)
            .where(Incident.model_id == model.id, Incident.version_id == version.id)
            .order_by(Incident.opened_on.desc(), Incident.id.desc())
        )
    )
    summary = model_summary(info, monitors, docs, [open_incident] if open_incident else [])
    doc = model_document(info, monitors, docs, incident_ids)
    stmt = insert(ModelDocument).values(model_id=model.id, summary=summary, doc=doc)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ModelDocument.model_id],
            set_={
                "summary": stmt.excluded.summary,
                "doc": stmt.excluded.doc,
                "updated_at": text("now()"),
            },
        )
    )


async def _sync_incident(
    session: AsyncSession,
    model: Model,
    version: _Version,
    monitors: Monitors,
    docs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Open, update or resolve the model's incident to match its days.

    Returns the open incident's document, if any.

    An incident covers one episode, evaluated on the days since the previous incident resolved
    (``analysis.evaluate`` decides when one opens and resolves). An episode that had already
    ended when first evaluated, as in a backfill, opens no incident.
    """
    current = await session.scalar(
        select(Incident).where(Incident.model_id == model.id, Incident.status == "open")
    )
    if current is not None and (current.version_id != version.id or not docs):
        # The model moved to another version, or has had no traffic for the whole window.
        await _resolve(session, current, datetime.now(UTC).date())
        current = None
    if not docs:
        return None

    since = await session.scalar(
        select(Incident.resolved_on)
        .where(Incident.model_id == model.id, Incident.status == "resolved")
        .order_by(Incident.resolved_on.desc())
        .limit(1)
    )
    days = [d for d in docs if since is None or date.fromisoformat(d["date"]) > since]
    episode = evaluate(monitors.reference_accuracy, days) if days else None
    latest = date.fromisoformat(docs[-1]["date"])
    if episode is None or episode.resolved_on is not None:
        if current is not None:
            ended = episode.resolved_on if episode is not None else None
            await _resolve(session, current, ended or latest)
        return None

    opened = current.opened_on if current is not None else episode.opened_on
    window_from = max(
        opened - timedelta(days=1), latest - timedelta(days=INVESTIGATION_MAX_DAYS - 1)
    )
    data = await load_days(session, version.id, monitors.schema, window_from, latest)
    span = concat([data[d] for d in sorted(data)])
    investigation = await asyncio.to_thread(investigate, monitors, episode.lead.kind, span)

    incident_id = current.id if current is not None else await _next_incident_id(session, model.id)
    doc = incident_document(
        incident_id=incident_id,
        model_id=model.id,
        signals=episode.signals,
        lead=episode.lead,
        opened_on=opened,
        window_from=window_from,
        window_to=latest,
        investigation=investigation,
        latest_day=docs[-1],
        monitors=monitors,
    )
    if current is None:
        session.add(
            Incident(
                id=incident_id,
                model_id=model.id,
                version_id=version.id,
                status="open",
                opened_on=opened,
                doc=doc,
            )
        )
        log.warning("incident %s opened: %s", incident_id, doc["title"])
    else:
        current.doc = doc
        current.updated_at = datetime.now(UTC)
    await session.flush()
    return doc


async def _resolve(session: AsyncSession, incident: Incident, on: date) -> None:
    incident.status = "resolved"
    incident.resolved_on = on
    incident.doc = {**incident.doc, "resolvedOn": on.isoformat()}
    incident.updated_at = datetime.now(UTC)
    await session.flush()
    log.info("incident %s resolved on %s", incident.id, on)


async def _next_incident_id(session: AsyncSession, model_id: str) -> str:
    seq = await session.scalar(
        update(Model)
        .where(Model.id == model_id)
        .values(incident_seq=Model.incident_seq + 1)
        .returning(Model.incident_seq)
    )
    return f"{model_id}-{seq}"
