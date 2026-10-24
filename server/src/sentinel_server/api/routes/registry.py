"""The model registry: models, their versions, and reference data uploads."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sentinel_server.contracts import Slug
from sentinel_server.db.models import Model, ModelVersion, VersionStatus
from sentinel_server.reference import ReferenceError, parse_reference

from ..deps import CanAdmin, CanRead, Session, SettingsDep
from ..errors import ApiError

router = APIRouter(prefix="/v1/registry", tags=["registry"])

VersionName = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
]


class ModelIn(BaseModel):
    """Create or update a model."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    team: Annotated[str, StringConstraints(max_length=200)] = ""
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    label_delay_days: Annotated[int, Field(ge=0, le=365)] = 0


class VersionOut(BaseModel):
    """A version and the state of its monitors."""

    version: str
    status: VersionStatus
    active: bool
    decision_threshold: float
    features: list[dict[str, str]]
    error: str | None
    summary: dict[str, object] | None
    created_at: datetime
    fitted_at: datetime | None


class ModelOut(BaseModel):
    """A registered model."""

    id: str
    name: str
    team: str
    description: str
    label_delay_days: int
    active_version: str | None
    versions: list[VersionOut]


@router.get("/models", dependencies=[CanRead])
async def list_models(session: Session) -> list[ModelOut]:
    """Every registered model with its versions."""
    models = list(await session.scalars(select(Model).order_by(Model.id)))
    return [await _model_out(session, m) for m in models]


@router.get("/models/{model_id}", dependencies=[CanRead])
async def get_model(model_id: Slug, session: Session) -> ModelOut:
    """One registered model."""
    return await _model_out(session, await _model(session, model_id))


@router.put("/models/{model_id}", dependencies=[CanAdmin])
async def put_model(
    model_id: Slug, body: ModelIn, session: Session, response: Response
) -> ModelOut:
    """Register a model, or update its details."""
    model = await session.get(Model, model_id)
    if model is None:
        model = Model(id=model_id, **body.model_dump())
        session.add(model)
        response.status_code = status.HTTP_201_CREATED
    else:
        for field, value in body.model_dump().items():
            setattr(model, field, value)
    await session.commit()
    return await _model_out(session, model)


@router.post(
    "/models/{model_id}/versions",
    dependencies=[CanAdmin],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_version(
    model_id: Slug,
    session: Session,
    settings: SettingsDep,
    version: Annotated[VersionName, Form()],
    reference: Annotated[UploadFile, File(description="CSV: features, score and label columns")],
    score_column: Annotated[str, Form()] = "score",
    label_column: Annotated[str, Form()] = "label",
    prediction_column: Annotated[str | None, Form()] = None,
    decision_threshold: Annotated[float, Form(gt=0, lt=1)] = 0.5,
    activate: Annotated[bool, Form()] = True,
) -> VersionOut:
    """Upload a version's reference data.

    It is validated now and fitted in the background; poll the version until its status is
    ``ready``.
    """
    model = await _model(session, model_id)
    data = await reference.read(settings.max_reference_bytes + 1)
    if len(data) > settings.max_reference_bytes:
        raise ApiError(
            413,
            "reference-too-large",
            "Reference too large",
            f"Reference data is limited to {settings.max_reference_bytes // (1024 * 1024)} MB; "
            "a uniform sample of 20-50k rows is plenty.",
        )
    try:
        parsed = await asyncio.to_thread(
            parse_reference,
            data,
            score_column=score_column,
            label_column=label_column,
            prediction_column=prediction_column,
        )
    except ReferenceError as exc:
        raise ApiError(
            422,
            "invalid-reference",
            "Reference data rejected",
            f"{len(exc.problems)} problem(s) with the reference data.",
            problems=exc.problems,
        ) from exc

    row = ModelVersion(
        model_id=model.id,
        version=version,
        status=VersionStatus.PENDING,
        decision_threshold=decision_threshold,
        feature_schema=parsed.schema.to_json(),
        reference_csv=data,
        score_column=score_column,
        label_column=label_column,
        prediction_column=prediction_column,
        activate=activate,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise ApiError(
            409,
            "version-exists",
            "Version exists",
            f"'{model_id}' already has a version '{version}'. Versions are immutable; "
            "upload under a new version name.",
        ) from exc
    return _version_out(row, active=False)


@router.get("/models/{model_id}/versions/{version}", dependencies=[CanRead])
async def get_version(model_id: Slug, version: VersionName, session: Session) -> VersionOut:
    """A version's status; ``ready`` once its monitors are fitted."""
    model = await _model(session, model_id)
    row = await _version(session, model_id, version)
    return _version_out(row, active=model.active_version_id == row.id)


@router.post("/models/{model_id}/versions/{version}/activate", dependencies=[CanAdmin])
async def activate_version(model_id: Slug, version: VersionName, session: Session) -> ModelOut:
    """Make a fitted version the one predictions default to and the dashboard shows."""
    model = await _model(session, model_id)
    row = await _version(session, model_id, version)
    if row.status != VersionStatus.READY:
        raise ApiError(
            409,
            "version-not-ready",
            "Version not ready",
            f"Version '{version}' is {row.status}; only a fitted version can be activated.",
        )
    model.active_version_id = row.id
    await session.commit()
    return await _model_out(session, model)


async def _model(session: Session, model_id: str) -> Model:
    model = await session.get(Model, model_id)
    if model is None:
        raise ApiError(
            404, "unknown-model", "Unknown model", f"No model '{model_id}' is registered."
        )
    return model


async def _version(session: Session, model_id: str, version: str) -> ModelVersion:
    row = await session.scalar(
        select(ModelVersion).where(
            ModelVersion.model_id == model_id, ModelVersion.version == version
        )
    )
    if row is None:
        raise ApiError(
            404,
            "unknown-version",
            "Unknown version",
            f"Model '{model_id}' has no version '{version}'.",
        )
    return row


async def _model_out(session: Session, model: Model) -> ModelOut:
    versions = list(
        await session.scalars(
            select(ModelVersion)
            .where(ModelVersion.model_id == model.id)
            .order_by(ModelVersion.created_at.desc())
        )
    )
    active = next((v.version for v in versions if v.id == model.active_version_id), None)
    return ModelOut(
        id=model.id,
        name=model.name,
        team=model.team,
        description=model.description,
        label_delay_days=model.label_delay_days,
        active_version=active,
        versions=[_version_out(v, active=v.id == model.active_version_id) for v in versions],
    )


def _version_out(row: ModelVersion, *, active: bool) -> VersionOut:
    return VersionOut(
        version=row.version,
        status=VersionStatus(row.status),
        active=active,
        decision_threshold=row.decision_threshold,
        features=row.feature_schema,
        error=row.error,
        summary=row.summary,
        created_at=row.created_at,
        fitted_at=row.fitted_at,
    )
