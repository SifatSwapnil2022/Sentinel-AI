"""Ingest payloads, and the form they take on the Redis stream between API and worker."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import orjson
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
RequestId = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")
]
"""Printable ASCII without spaces: request ids end up in URLs and logs."""
FeatureValue = str | bool | int | float | None


def _aware(ts: datetime) -> datetime:
    """Timestamps without a zone are taken as UTC, the convention for machine logs."""
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _finite_features(features: dict[str, FeatureValue]) -> dict[str, FeatureValue]:
    for name, value in features.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"feature {name!r} is {value}; send null for a missing value")
    return features


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PredictionIn(_Strict):
    """One scored request."""

    request_id: RequestId
    ts: Annotated[datetime, AfterValidator(_aware)] | None = None
    """When the prediction was made; defaults to when the API received it."""
    features: Annotated[
        dict[Annotated[str, StringConstraints(min_length=1, max_length=128)], FeatureValue],
        Field(max_length=500),
        AfterValidator(_finite_features),
    ]
    score: Annotated[float, Field(ge=0, le=1)]
    """The model's probability for the positive class."""
    prediction: Literal[0, 1] | None = None
    """The decision taken; defaults to ``score >= decision_threshold`` of the version."""
    latency_ms: Annotated[float, Field(ge=0)] | None = None


class PredictionBatch(_Strict):
    """``POST /v1/ingest/predictions``."""

    model_id: Slug
    version: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    """The model version that scored these; defaults to the model's active version."""
    predictions: Annotated[list[PredictionIn], Field(min_length=1)]


class LabelIn(_Strict):
    """The true outcome of a request."""

    request_id: RequestId
    label: Literal[0, 1]


class LabelBatch(_Strict):
    """``POST /v1/ingest/labels``."""

    model_id: Slug
    labels: Annotated[list[LabelIn], Field(min_length=1)]


class Accepted(BaseModel):
    """Response to an ingest request: queued, not yet written."""

    accepted: int
    queued_as: str


# ----------------------------------------------------------------------------- stream messages


@dataclass(frozen=True)
class PredictionRecord:
    """A prediction after the API filled in defaults; what the worker writes."""

    request_id: str
    ts: datetime
    features: dict[str, Any]
    score: float
    prediction: int
    latency_ms: float | None


@dataclass(frozen=True)
class PredictionMessage:
    """A batch of predictions on the stream."""

    model_id: str
    version_id: int
    records: list[PredictionRecord]


@dataclass(frozen=True)
class LabelMessage:
    """A batch of labels on the stream."""

    model_id: str
    labels: list[tuple[str, int]]


Message = PredictionMessage | LabelMessage


def encode(message: Message) -> dict[str, bytes]:
    """Stream fields for a message. The body is one compact JSON document."""
    if isinstance(message, PredictionMessage):
        body: dict[str, Any] = {
            "model_id": message.model_id,
            "version_id": message.version_id,
            "records": [
                [r.request_id, r.ts.isoformat(), r.features, r.score, r.prediction, r.latency_ms]
                for r in message.records
            ],
        }
        kind = b"predictions"
    else:
        body = {"model_id": message.model_id, "labels": message.labels}
        kind = b"labels"
    return {"kind": kind, "v": b"1", "body": orjson.dumps(body)}


class MalformedMessageError(ValueError):
    """A stream entry that cannot be decoded; it goes to the dead-letter stream."""


def decode(fields: dict[bytes, bytes]) -> Message:
    """Inverse of :func:`encode`."""
    try:
        if fields.get(b"v") != b"1":
            raise MalformedMessageError(f"unknown message version {fields.get(b'v')!r}")
        kind, body = fields[b"kind"], orjson.loads(fields[b"body"])
        if kind == b"predictions":
            return PredictionMessage(
                model_id=str(body["model_id"]),
                version_id=int(body["version_id"]),
                records=[
                    PredictionRecord(
                        request_id=str(rid),
                        ts=datetime.fromisoformat(ts),
                        features=dict(features),
                        score=float(score),
                        prediction=int(pred),
                        latency_ms=None if latency is None else float(latency),
                    )
                    for rid, ts, features, score, pred, latency in body["records"]
                ],
            )
        if kind == b"labels":
            return LabelMessage(
                model_id=str(body["model_id"]),
                labels=[(str(rid), int(label)) for rid, label in body["labels"]],
            )
        raise MalformedMessageError(f"unknown message kind {kind!r}")
    except MalformedMessageError:
        raise
    except (KeyError, TypeError, ValueError, orjson.JSONDecodeError) as exc:
        raise MalformedMessageError(f"cannot decode stream entry: {exc}") from exc
