"""Assemble the JSON documents the dashboard reads (see ``web/src/data/schema.ts``).

The demo builder and the API both go through these functions, so the static demo and the live
service cannot disagree about shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from ._json import SCHEMA_VERSION, r
from .days import DayData
from .incidents import MISSING_JUMP, Episode, investigate
from .monitors import Monitors

INVESTIGATION_MAX_DAYS = 14
"""An incident's investigation covers at most this many days, ending on its last bad day."""

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
    segments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The model page: daily metrics, per-feature drift and missing values, segments."""
    if not days:
        raise ValueError(f"model {info.id} has no computed days")
    latest = days[-1]
    features = []
    for name, ref in monitors.columns.items():
        series = [
            {
                "date": d["date"],
                "statistic": None if s is None else s["statistic"],
                "drifted": False if s is None else s["drifted"],
                "psi": None if s is None else s["psi"],
                "nullRate": _null_rate(d, name),
            }
            for d in days
            for s in [d["features"].get(name)]
        ]
        # The latest day a drift test could run; a feature missing entirely today keeps its
        # last statistics and shows today's missing share.
        stats = next((d["features"][name] for d in reversed(days) if d["features"].get(name)), None)
        if stats is None:
            continue
        features.append(
            {
                "name": name,
                "kind": ref.kind.value,
                "method": ref.method.value,
                "threshold": ref.threshold,
                "isPValue": ref.method.is_p_value,
                "series": series,
                "latest": {
                    "statistic": stats["statistic"],
                    "drifted": stats["drifted"],
                    "psi": stats["psi"],
                    "nullRate": _null_rate(latest, name) or 0.0,
                },
                "referenceNullRate": r(ref.null_rate),
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
        "segments": segments or {"window": {"to": latest["date"], "rows": 0}, "rows": []},
        "alertIds": list(incident_ids),
    }


def _missing_features(day: dict[str, Any], monitors: Monitors) -> list[dict[str, Any]]:
    """Features missing well above their reference rate on ``day``, worst first."""
    quality = day.get("dataQuality") or {}
    rows = [
        {"name": name, "nullRate": q["nullRate"], "referenceNullRate": q["referenceNullRate"]}
        for name in monitors.columns
        if (q := quality.get(name)) is not None
        and q["nullRate"] - q["referenceNullRate"] > MISSING_JUMP
    ]
    return sorted(rows, key=lambda q: q["referenceNullRate"] - q["nullRate"])


def _null_rate(day: dict[str, Any], name: str) -> float | None:
    quality = (day.get("dataQuality") or {}).get(name)
    return None if quality is None else quality["nullRate"]


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
    resolved_on: date | None = None,
) -> dict[str, Any]:
    """An incident page: what fired, its investigation, and the features drifting at its end."""
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
        "status": "open" if resolved_on is None else "resolved",
        "openedOn": opened_on.isoformat(),
        "resolvedOn": None if resolved_on is None else resolved_on.isoformat(),
        **investigation,
        "window": {
            "from": window_from.isoformat(),
            "to": window_to.isoformat(),
            "rows": investigation["window"]["rows"],
        },
        "signals": [s.to_json() for s in sorted(signals, key=lambda s: s.fired_on)],
        "driftedFeatures": drifted,
        "missingFeatures": _missing_features(latest_day, monitors),
    }


def investigation_window(episode: Episode) -> tuple[date, date]:
    """Days an incident's investigation covers.

    From the day before it opened to its last day of trouble, at most
    ``INVESTIGATION_MAX_DAYS`` long.
    """
    end = episode.last_day
    start = max(
        episode.opened_on - timedelta(days=1), end - timedelta(days=INVESTIGATION_MAX_DAYS - 1)
    )
    return start, end


def episode_document(
    incident_id: str,
    model_id: str,
    episode: Episode,
    span: DayData,
    day_docs: dict[str, dict[str, Any]],
    monitors: Monitors,
) -> dict[str, Any]:
    """The incident page for an episode.

    ``span`` holds the predictions of its investigation window; ``day_docs`` the day
    documents by ISO date.
    """
    start, end = investigation_window(episode)
    return incident_document(
        incident_id=incident_id,
        model_id=model_id,
        signals=episode.signals,
        lead=episode.lead,
        opened_on=episode.opened_on,
        window_from=start,
        window_to=end,
        investigation=investigate(monitors, episode.lead.kind, span),
        latest_day=day_docs[end.isoformat()],
        monitors=monitors,
        resolved_on=episode.resolved_on,
    )


def incident_ref(incident: dict[str, Any]) -> dict[str, Any]:
    """The short form listed on the overview."""
    keys = ("id", "modelId", "kind", "title", "severity", "status", "openedOn", "resolvedOn")
    return {k: incident[k] for k in keys}


def fleet_document(
    today: date,
    window_days: int,
    summaries: Sequence[dict[str, Any]],
    open_incidents: Sequence[dict[str, Any]],
    resolved_incidents: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """The overview: every model, open incidents (critical first) and recently resolved ones."""
    refs = sorted(
        (incident_ref(i) for i in open_incidents),
        key=lambda a: (a["severity"] != "critical", a["openedOn"], a["id"]),
    )
    resolved = sorted(
        (incident_ref(i) for i in resolved_incidents),
        key=lambda a: (a["resolvedOn"], a["id"]),
        reverse=True,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "today": today.isoformat(),
        "windowDays": window_days,
        "models": sorted(summaries, key=lambda m: (m["team"], m["id"])),
        "alerts": refs,
        "resolved": resolved,
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
