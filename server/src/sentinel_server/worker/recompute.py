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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sentinel_server.analysis import (
    CONCEPT_WINDOW_DAYS,
    DayData,
    Episode,
    ModelInfo,
    Monitors,
    compute_day,
    concat,
    episode_document,
    episodes,
    investigation_window,
    model_document,
    model_summary,
    segment_table,
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

SEGMENT_DAYS = 7
"""The model page's segments compare the reference with the last week of traffic."""


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
    """Rebuild a model's page, overview row and incidents from its stored day documents."""
    first = today - timedelta(days=window_days - 1)
    docs = list(
        await session.scalars(
            select(DailyWindow.doc)
            .where(DailyWindow.version_id == version.id, DailyWindow.day >= first)
            .order_by(DailyWindow.day)
        )
    )
    if not docs:
        for incident in await _open_incidents(session, model.id):
            await _resolve(session, incident, today)
        await session.execute(delete(ModelDocument).where(ModelDocument.model_id == model.id))
        return

    incidents = await _reconcile_incidents(session, model, version, monitors, docs)
    latest = date.fromisoformat(docs[-1]["date"])
    recent = await load_days(
        session, version.id, monitors.schema, latest - timedelta(days=SEGMENT_DAYS - 1), latest
    )
    segments = (
        await asyncio.to_thread(
            segment_table, monitors, concat([recent[d] for d in sorted(recent)])
        )
        if recent
        else None
    )
    info = ModelInfo(
        id=model.id,
        name=model.name,
        version=version.version,
        team=model.team,
        description=model.description,
        label_delay_days=model.label_delay_days,
    )
    open_docs = [i for i in incidents if i["status"] == "open"]
    summary = model_summary(info, monitors, docs, open_docs)
    doc = model_document(info, monitors, docs, [i["id"] for i in reversed(incidents)], segments)
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


async def _open_incidents(session: AsyncSession, model_id: str) -> list[Incident]:
    return list(
        await session.scalars(
            select(Incident).where(Incident.model_id == model_id, Incident.status == "open")
        )
    )


def _overlaps(incident: Incident, episode: Episode) -> bool:
    return incident.opened_on <= episode.last_day and (
        incident.resolved_on is None or incident.resolved_on > episode.opened_on
    )


async def _reconcile_incidents(
    session: AsyncSession,
    model: Model,
    version: _Version,
    monitors: Monitors,
    docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Make stored incidents match the episodes in the model's days.

    Returns their documents, oldest first.

    Episodes are recomputed from the day documents every time (``analysis.episodes``), so a
    backfill, late labels or a worker restart all converge on the same history. Each episode
    keeps the incident it overlaps, so ids are stable. Resolutions are applied before anything
    opens, because a model has at most one open incident.
    """
    latest = date.fromisoformat(docs[-1]["date"])
    window_start = date.fromisoformat(docs[0]["date"])
    by_date = {d["date"]: d for d in docs}
    found = episodes(monitors.reference_accuracy, docs)

    stored = list(
        await session.scalars(
            select(Incident)
            .where(Incident.model_id == model.id)
            .order_by(Incident.opened_on, Incident.id)
        )
    )
    for incident in stored:
        if incident.version_id != version.id and incident.status == "open":
            # The model moved to another version: that version's episode is over.
            await _resolve(session, incident, latest)
    mine = [i for i in stored if i.version_id == version.id]

    matches: list[Incident | None] = []
    used: set[str] = set()
    for episode in found:
        match = next((i for i in mine if i.id not in used and _overlaps(i, episode)), None)
        if match is not None:
            used.add(match.id)
        matches.append(match)
    for incident in mine:
        if incident.id not in used and incident.status == "open":
            # Revised days no longer support it (late labels, say).
            await _resolve(session, incident, latest)

    # Resolved episodes first, so the one open episode is applied last.
    order = sorted(range(len(found)), key=lambda k: found[k].resolved_on is None)
    documents: dict[int, dict[str, Any]] = {}
    for k in order:
        episode, match = found[k], matches[k]
        # An episode that began before the window keeps the start the incident recorded.
        opened = (
            match.opened_on
            if match is not None and match.opened_on < window_start
            else episode.opened_on
        )
        unchanged = (
            match is not None
            and match.status == "resolved"
            and episode.resolved_on == match.resolved_on
            and opened == match.opened_on
        )
        if unchanged:
            assert match is not None
            documents[k] = match.doc
            continue
        incident_id = match.id if match is not None else await _next_incident_id(session, model.id)
        start, end = investigation_window(episode)
        data = await load_days(session, version.id, monitors.schema, start, end)
        span = concat([data[d] for d in sorted(data)])
        doc = await asyncio.to_thread(
            episode_document,
            incident_id,
            model.id,
            replace(episode, opened_on=opened),
            span,
            by_date,
            monitors,
        )
        status = doc["status"]
        if match is None:
            session.add(
                Incident(
                    id=incident_id,
                    model_id=model.id,
                    version_id=version.id,
                    status=status,
                    opened_on=opened,
                    resolved_on=episode.resolved_on,
                    doc=doc,
                )
            )
            if status == "open":
                log.warning("incident %s opened: %s", incident_id, doc["title"])
        else:
            match.status = status
            match.opened_on = opened
            match.resolved_on = episode.resolved_on
            match.doc = doc
            match.updated_at = datetime.now(UTC)
        await session.flush()
        documents[k] = doc
    return [documents[k] for k in range(len(found))]


async def _resolve(session: AsyncSession, incident: Incident, on: date) -> None:
    incident.status = "resolved"
    incident.resolved_on = on
    incident.doc = {**incident.doc, "status": "resolved", "resolvedOn": on.isoformat()}
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
