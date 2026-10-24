"""What the dashboard reads: the overview, a model page, an incident.

The worker materialises these documents whenever data changes, so reads are a primary-key
lookup each. Shapes are those of ``web/src/data/schema.ts`` (``schemaVersion`` 1), identical to
the static demo's JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from sentinel_server.analysis import fleet_document, incident_ref
from sentinel_server.contracts import Slug
from sentinel_server.db.models import Incident, ModelDocument

from ..deps import CanRead, Session, SettingsDep
from ..errors import ApiError

router = APIRouter(prefix="/v1", tags=["documents"], dependencies=[CanRead])

CACHE = "private, max-age=15"
"""Documents change at most every few seconds; a short cache spares the database repeat reads."""


@router.get("/fleet")
async def fleet(session: Session, settings: SettingsDep, response: Response) -> dict[str, Any]:
    """Every model's overview row and every open incident."""
    summaries = list(
        await session.scalars(select(ModelDocument.summary).order_by(ModelDocument.model_id))
    )
    incidents = list(
        await session.scalars(
            select(Incident.doc).where(Incident.status == "open").order_by(Incident.opened_on)
        )
    )
    response.headers["Cache-Control"] = CACHE
    return fleet_document(datetime.now(UTC).date(), settings.window_days, summaries, incidents)


@router.get("/models/{model_id}")
async def model(model_id: Slug, session: Session, response: Response) -> dict[str, Any]:
    """A model page: daily metrics, per-feature drift, reference facts."""
    doc: dict[str, Any] | None = await session.scalar(
        select(ModelDocument.doc).where(ModelDocument.model_id == model_id)
    )
    if doc is None:
        raise ApiError(
            404,
            "no-model-data",
            "No data for model",
            f"No computed data for '{model_id}': it is unknown, has no fitted active version, "
            "or has received no predictions in the dashboard window.",
        )
    response.headers["Cache-Control"] = CACHE
    return doc


@router.get("/incidents")
async def incidents(
    session: Session,
    status: Annotated[Literal["open", "resolved", "all"], Query()] = "open",
    model_id: Annotated[Slug | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    """Incidents, most recently opened first, in their short form."""
    query = select(Incident.doc, Incident.status, Incident.resolved_on)
    if status != "all":
        query = query.where(Incident.status == status)
    if model_id is not None:
        query = query.where(Incident.model_id == model_id)
    rows = await session.execute(
        query.order_by(Incident.opened_on.desc(), Incident.id.desc()).limit(limit)
    )
    return [
        {
            **incident_ref(doc),
            "status": state,
            "resolvedOn": resolved.isoformat() if resolved else None,
        }
        for doc, state, resolved in rows
    ]


@router.get("/incidents/{incident_id}")
async def incident(incident_id: str, session: Session, response: Response) -> dict[str, Any]:
    """One incident: what fired, the investigation, and the features drifting now."""
    doc: dict[str, Any] | None = await session.scalar(
        select(Incident.doc).where(Incident.id == incident_id)
    )
    if doc is None:
        raise ApiError(404, "unknown-incident", "Unknown incident", f"No incident '{incident_id}'.")
    response.headers["Cache-Control"] = CACHE
    return doc
