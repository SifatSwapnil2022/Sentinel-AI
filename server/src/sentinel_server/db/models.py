"""The database schema, mapped for queries.

The migration in ``migrations/`` is the source of truth for DDL; these classes mirror it.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


class Scope(StrEnum):
    """What an API key may do."""

    INGEST = "ingest"
    READ = "read"
    ADMIN = "admin"


class VersionStatus(StrEnum):
    """Lifecycle of a model version's monitors.

    Fitting happens inside one transaction holding the version's row lock, so a crashed worker
    leaves the version ``pending`` for another to pick up rather than stuck mid-fit.
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class ApiKey(Base):
    """A credential. Only a SHA-256 digest of the secret is stored."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(String(12))
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Model(Base):
    """A model being monitored, independent of version."""

    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    team: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    label_delay_days: Mapped[int] = mapped_column(SmallInteger, default=0)
    active_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("model_versions.id", use_alter=True, ondelete="SET NULL")
    )
    incident_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelVersion(Base):
    """A version of a model, its reference data and, once fitted, its monitors."""

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=VersionStatus.PENDING)
    decision_threshold: Mapped[float] = mapped_column(Double, default=0.5)
    feature_schema: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    reference_csv: Mapped[bytes | None] = mapped_column(LargeBinary)
    """The uploaded reference, kept so monitors can be refitted after an engine upgrade."""
    score_column: Mapped[str] = mapped_column(Text)
    label_column: Mapped[str] = mapped_column(Text)
    prediction_column: Mapped[str | None] = mapped_column(Text)
    monitors: Mapped[bytes | None] = mapped_column(LargeBinary)
    summary: Mapped[dict[str, Any] | None]
    error: Mapped[str | None] = mapped_column(Text)
    activate: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Prediction(Base):
    """One scored request. Partitioned by day on ``ts``; partitions are created on demand."""

    __tablename__ = "predictions"
    __table_args__ = (
        Index("predictions_request", "model_id", "request_id"),
        {"postgresql_partition_by": "RANGE (ts)"},
    )

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    version_id: Mapped[int] = mapped_column(BigInteger)
    features: Mapped[dict[str, Any]]
    score: Mapped[float] = mapped_column(Double)
    prediction: Mapped[int] = mapped_column(SmallInteger)
    latency_ms: Mapped[float | None] = mapped_column(Double)


class Label(Base):
    """The true outcome for a request, which may arrive before or long after the prediction."""

    __tablename__ = "labels"

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[int] = mapped_column(SmallInteger)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DirtyDay(Base):
    """A day whose document must be recomputed because its data changed."""

    __tablename__ = "dirty_days"

    version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyWindow(Base):
    """The computed document for one version on one day."""

    __tablename__ = "daily_windows"

    version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    doc: Mapped[dict[str, Any]]
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelDocument(Base):
    """What the dashboard reads for a model, rebuilt by the worker after every recompute."""

    __tablename__ = "model_documents"

    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[dict[str, Any]]
    doc: Mapped[dict[str, Any]]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Incident(Base):
    """An alert: opened when a rule holds, updated while it does, resolved when it stops."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "incidents_one_open_per_model",
            "model_id",
            unique=True,
            postgresql_where="status = 'open'",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"))
    version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    opened_on: Mapped[date] = mapped_column(Date)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    doc: Mapped[dict[str, Any]]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
