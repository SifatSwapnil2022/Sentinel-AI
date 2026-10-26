"""What the dashboard reads: the overview, a model page, an incident.

The worker materialises these documents whenever data changes, so reads are a primary-key
lookup each. Shapes are those of ``web/src/data/schema.ts`` (``schemaVersion`` 1), identical to
the static demo's JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from sentinel_server.analysis import (
    TABLES,
    bi_tables,
    fleet_daily,
    fleet_document,
    incident_ref,
    to_csv,
)
from sentinel_server.contracts import Slug
from sentinel_server.db.models import Incident, ModelDocument

from ..deps import CanRead, Session, SettingsDep
from ..errors import ApiError

router = APIRouter(prefix="/v1", tags=["documents"], dependencies=[CanRead])

CACHE = "private, max-age=15"
"""Documents change at most every few seconds; a short cache spares the database repeat reads."""


@router.get("/fleet")
async def fleet(session: Session, settings: SettingsDep, response: Response) -> dict[str, Any]:
    """Every model's overview row, open incidents, and those resolved within the window."""
    response.headers["Cache-Control"] = CACHE
    return await _fleet(session, settings.window_days)


async def _fleet(session: Session, window_days: int) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    summaries = list(await session.scalars(select(ModelDocument.summary)))
    open_docs = list(
        await session.scalars(
            select(Incident.doc).where(Incident.status == "open").order_by(Incident.opened_on)
        )
    )
    resolved_docs = list(
        await session.scalars(
            select(Incident.doc).where(
                Incident.status == "resolved",
                Incident.resolved_on >= today - timedelta(days=window_days - 1),
            )
        )
    )
    return fleet_document(today, window_days, summaries, open_docs, resolved_docs)


async def _model_docs(session: Session) -> list[dict[str, Any]]:
    return list(await session.scalars(select(ModelDocument.doc).order_by(ModelDocument.model_id)))


@router.get("/fleet/daily")
async def daily(session: Session, response: Response) -> dict[str, Any]:
    """One row per model per day: the facts behind slicers, heatmaps and the explore view."""
    response.headers["Cache-Control"] = CACHE
    return fleet_daily(await _model_docs(session))


@router.get(
    "/export/{table}.csv",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export(table: str, session: Session, settings: SettingsDep) -> PlainTextResponse:
    """One table of the BI star schema as CSV, for Power BI, Tableau or a spreadsheet.

    Tables: ``dim_model``, ``dim_date``, ``fact_model_day``, ``fact_feature_day``,
    ``fact_segment``, ``fact_incident`` and ``fact_incident_signal``; columns in ``docs/bi.md``.
    """
    if table not in TABLES:
        raise ApiError(
            404,
            "unknown-table",
            "Unknown table",
            f"No export table '{table}'. Tables: {', '.join(TABLES)}.",
        )
    fleet_doc = await _fleet(session, settings.window_days)
    window_start = datetime.now(UTC).date() - timedelta(days=settings.window_days - 1)
    incidents = list(
        await session.scalars(
            select(Incident.doc)
            .where((Incident.status == "open") | (Incident.resolved_on >= window_start))
            .order_by(Incident.opened_on, Incident.id)
        )
    )
    tables = bi_tables(fleet_doc, await _model_docs(session), incidents)
    return PlainTextResponse(
        to_csv(tables[table]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": CACHE,
            "Content-Disposition": f'inline; filename="sentinel_{table}.csv"',
        },
    )


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
    query = select(Incident.doc)
    if status != "all":
        query = query.where(Incident.status == status)
    if model_id is not None:
        query = query.where(Incident.model_id == model_id)
    docs = await session.scalars(
        query.order_by(Incident.opened_on.desc(), Incident.id.desc()).limit(limit)
    )
    return [incident_ref(doc) for doc in docs]


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
