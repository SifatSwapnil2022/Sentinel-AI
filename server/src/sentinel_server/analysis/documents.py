"""Assemble the JSON documents the dashboard reads (see ``web/src/data/schema.ts``).

The demo builder and the API both go through these functions, so the static demo and the live
service cannot disagree about shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from ._json import SCHEMA_VERSION, r
from .monitors import Monitors

SEVERITY_RANK = {"critical": 2, "warning": 1}


@dataclass(frozen=True)
class ModelInfo:
    """What the registry knows about a model and its active version."""

    id: str
    name: str
    version: str
    team: str
    description: str
    label_delay_days: int


def model_document(
    info: ModelInfo,
    monitors: Monitors,
    days: Sequence[dict[str, Any]],
    incident_ids: Sequence[str],
) -> dict[str, Any]:
    """The model page: daily metrics, per-feature drift series, reference facts."""
    if not days:
        raise ValueError(f"model {info.id} has no computed days")
    latest = days[-1]
    features = []
    for name, ref in monitors.columns.items():
        stats = latest["features"].get(name)
        series = [
            {
                "date": d["date"],
                "statistic": s["statistic"],
                "drifted": s["drifted"],
                "psi": s["psi"],
            }
            for d in days
            if (s := d["features"].get(name)) is not None
        ]
        if stats is None or not series:
            continue
        features.append(
            {
                "name": name,
                "kind": ref.kind.value,
                "method": ref.method.value,
                "threshold": ref.threshold,
                "isPValue": ref.method.is_p_value,
                "series": series,
                "latest": {k: stats[k] for k in ("statistic", "drifted", "psi", "nullRate")},
                "histogram": stats["histogram"],
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": info.id,
        "name": info.name,
        "version": info.version,
        "team": info.team,
        "description": info.description,
        "labelDelayDays": info.label_delay_days,
        **monitors.summary(),
        "days": [_public_day(d) for d in days],
        "features": features,
        "alertIds": list(incident_ids),
    }


def model_summary(
    info: ModelInfo,
    monitors: Monitors,
    days: Sequence[dict[str, Any]],
    open_incidents: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """One row of the overview table."""
    latest = days[-1]
    worst = max(open_incidents, key=lambda i: SEVERITY_RANK[i["severity"]], default=None)
    last_week = days[-7:]
    drifted = sum(bool(s and s["drifted"]) for s in latest["features"].values())
    return {
        "id": info.id,
        "name": info.name,
        "version": info.version,
        "team": info.team,
        "status": worst["severity"] if worst else "healthy",
        "statusReason": worst["title"] if worst else "No open alerts",
        "referenceAccuracy": r(monitors.reference_accuracy),
        "estimate": latest["estimate"]["accuracy"],
        "measured": {
            **_latest_measured(days),
            "coverage": r(float(np.mean([d["labelCoverage"] for d in last_week]))),
        },
        "predictionsPerDay": int(np.mean([d["rows"] for d in last_week])),
        "p95LatencyMs": latest["p95LatencyMs"] or 0,
        "driftedFeatures": drifted,
        "totalFeatures": len(monitors.columns),
        "multivariateDrifted": latest["multivariate"]["drifted"],
        "openAlerts": len(open_incidents),
        "trend": [d["estimate"]["accuracy"]["value"] for d in days[-14:]],
    }


def incident_document(
    *,
    incident_id: str,
    model_id: str,
    signals: Sequence[Any],
    lead: Any,
    opened_on: date,
    window_from: date,
    window_to: date,
    investigation: dict[str, Any],
    latest_day: dict[str, Any],
    monitors: Monitors,
) -> dict[str, Any]:
    """An incident page: what fired, its investigation, and features drifting now."""
    severity = "critical" if any(s.severity == "critical" for s in signals) else lead.severity
    # Iterate in the schema's column order: ``latest_day`` may have been through a store that
    # doesn't keep key order.
    drifted = [
        {
            "name": name,
            "method": ref.method.value,
            "statistic": stats["statistic"],
            "threshold": ref.threshold,
            "isPValue": ref.method.is_p_value,
            "psi": stats["psi"],
        }
        for name, ref in monitors.columns.items()
        if (stats := latest_day["features"].get(name)) is not None and stats["drifted"]
    ]
    return {
        "id": incident_id,
        "modelId": model_id,
        "kind": lead.kind.value,
        "title": lead.title,
        "severity": severity,
        "openedOn": opened_on.isoformat(),
        **investigation,
        "window": {
            "from": window_from.isoformat(),
            "to": window_to.isoformat(),
            "rows": investigation["window"]["rows"],
        },
        "signals": [s.to_json() for s in sorted(signals, key=lambda s: s.fired_on)],
        "driftedFeatures": drifted,
    }


def incident_ref(incident: dict[str, Any]) -> dict[str, Any]:
    """The short form listed on the overview."""
    return {k: incident[k] for k in ("id", "modelId", "kind", "title", "severity", "openedOn")}


def fleet_document(
    today: date,
    window_days: int,
    summaries: Sequence[dict[str, Any]],
    open_incidents: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The overview: every model and every open incident, critical first."""
    refs = sorted(
        (incident_ref(i) for i in open_incidents),
        key=lambda a: (a["severity"] != "critical", a["openedOn"], a["id"]),
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "today": today.isoformat(),
        "windowDays": window_days,
        "models": list(summaries),
        "alerts": refs,
    }


def _public_day(day: dict[str, Any]) -> dict[str, Any]:
    """A day document without the per-feature detail, which the model page serves separately."""
    out = {k: v for k, v in day.items() if k != "features"}
    if out.get("p95LatencyMs") is None:
        out["p95LatencyMs"] = 0
    return out


def _latest_measured(days: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Most recent day whose labels are at least half in, so the figure is trustworthy."""
    for d in reversed(days):
        if d["measured"] is not None and d["labelCoverage"] >= 0.5:
            return {"value": d["measured"]["accuracy"], "asOf": d["date"]}
    return {"value": None, "asOf": None}
