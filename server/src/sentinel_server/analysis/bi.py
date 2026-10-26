"""Tables for analysis outside Sentinel: the fleet's daily facts, and a star schema for BI tools.

Built from the same documents the dashboard reads, so Power BI, Tableau, a CSV and the dashboard
always show the same numbers. Column names are snake_case, the convention BI tools expect.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from ._json import SCHEMA_VERSION, r


def _drifted_by_date(model_doc: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature in model_doc["features"]:
        for point in feature["series"]:
            counts[point["date"]] = counts.get(point["date"], 0) + int(point["drifted"])
    return counts


def _missing_jump(day: dict[str, Any]) -> float:
    quality = day.get("dataQuality") or {}
    return max((q["nullRate"] - q["referenceNullRate"] for q in quality.values()), default=0.0)


def fleet_daily(model_docs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One row per model per day: the facts slicers, heatmaps and the explore view work from."""
    rows = []
    for doc in model_docs:
        drifted = _drifted_by_date(doc)
        reference = doc["referenceMetrics"]["accuracy"]
        for day in doc["days"]:
            accuracy = day["estimate"]["accuracy"]
            measured = (day["measured"] or {}).get("accuracy")
            rows.append(
                {
                    "modelId": doc["id"],
                    "team": doc["team"],
                    "date": day["date"],
                    "rows": day["rows"],
                    "estimate": accuracy["value"],
                    "lower": accuracy["lower"],
                    "upper": accuracy["upper"],
                    "reference": reference,
                    "measured": measured,
                    "labelCoverage": day["labelCoverage"],
                    "p95LatencyMs": day["p95LatencyMs"],
                    "driftedFeatures": drifted.get(day["date"], 0),
                    "totalFeatures": len(doc["features"]),
                    "multivariateDrifted": day["multivariate"]["drifted"],
                    "conceptFlag": day["conceptFlag"],
                    "missingJump": r(max(_missing_jump(day), 0.0)),
                }
            )
    rows.sort(key=lambda row: (row["date"], row["modelId"]))
    return {"schemaVersion": SCHEMA_VERSION, "rows": rows}


# --------------------------------------------------------------------------- star schema

TABLES = (
    "dim_model",
    "dim_date",
    "fact_model_day",
    "fact_feature_day",
    "fact_segment",
    "fact_incident",
    "fact_incident_signal",
)


def bi_tables(
    fleet: dict[str, Any],
    model_docs: Sequence[dict[str, Any]],
    incidents: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Every table of the star schema; see ``docs/bi.md`` for the column dictionary."""
    summaries = {m["id"]: m for m in fleet["models"]}
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}

    for doc in model_docs:
        summary = summaries.get(doc["id"], {})
        tables["dim_model"].append(
            {
                "model_id": doc["id"],
                "model_name": doc["name"],
                "team": doc["team"],
                "version": doc["version"],
                "description": doc["description"],
                "label_delay_days": doc["labelDelayDays"],
                "reference_rows": doc["referenceRows"],
                "reference_accuracy": doc["referenceMetrics"]["accuracy"],
                "reference_precision": doc["referenceMetrics"]["precision"],
                "reference_recall": doc["referenceMetrics"]["recall"],
                "reference_f1": doc["referenceMetrics"]["f1"],
                "status": summary.get("status", "healthy"),
                "open_incidents": summary.get("openAlerts", 0),
            }
        )
        drifted = _drifted_by_date(doc)
        for day in doc["days"]:
            est = day["estimate"]
            measured = day["measured"] or {}
            tables["fact_model_day"].append(
                {
                    "model_id": doc["id"],
                    "date": day["date"],
                    "predictions": day["rows"],
                    "est_accuracy": est["accuracy"]["value"],
                    "est_accuracy_lower": est["accuracy"]["lower"],
                    "est_accuracy_upper": est["accuracy"]["upper"],
                    "est_precision": est["precision"]["value"],
                    "est_recall": est["recall"]["value"],
                    "est_f1": est["f1"]["value"],
                    "measured_accuracy": measured.get("accuracy"),
                    "measured_precision": measured.get("precision"),
                    "measured_recall": measured.get("recall"),
                    "measured_f1": measured.get("f1"),
                    "label_coverage": day["labelCoverage"],
                    "p95_latency_ms": day["p95LatencyMs"],
                    "multivariate_error": day["multivariate"]["error"],
                    "multivariate_upper": day["multivariate"]["upper"],
                    "multivariate_drifted": day["multivariate"]["drifted"],
                    "concept_flag": day["conceptFlag"],
                    "drifted_features": drifted.get(day["date"], 0),
                    "max_missing_jump": r(max(_missing_jump(day), 0.0)),
                }
            )
        for feature in doc["features"]:
            for point in feature["series"]:
                tables["fact_feature_day"].append(
                    {
                        "model_id": doc["id"],
                        "feature": feature["name"],
                        "date": point["date"],
                        "kind": feature["kind"],
                        "method": feature["method"],
                        "statistic": point["statistic"],
                        "threshold": feature["threshold"],
                        "drifted": point["drifted"],
                        "psi": point["psi"],
                        "null_rate": point["nullRate"],
                        "reference_null_rate": feature["referenceNullRate"],
                    }
                )
        for row in doc["segments"]["rows"]:
            tables["fact_segment"].append(
                {
                    "model_id": doc["id"],
                    "window_end": doc["segments"]["window"]["to"],
                    "feature": row["feature"],
                    "segment": row["value"],
                    "rows_reference": row["nReference"],
                    "rows_current": row["nCurrent"],
                    "share_reference": row["shareReference"],
                    "share_current": row["shareCurrent"],
                    "reference_accuracy": row["referenceAccuracy"],
                    "estimated_accuracy": row["estimatedAccuracy"],
                    "measured_accuracy": row["measuredAccuracy"],
                    "labelled_rows": row["labelled"],
                }
            )

    for incident in incidents:
        top = incident["findings"][0] if incident["findings"] else None
        tables["fact_incident"].append(
            {
                "incident_id": incident["id"],
                "model_id": incident["modelId"],
                "kind": incident["kind"],
                "title": incident["title"],
                "severity": incident["severity"],
                "status": incident["status"],
                "opened_on": incident["openedOn"],
                "resolved_on": incident["resolvedOn"],
                "days_open": _days(incident["openedOn"], incident["resolvedOn"] or fleet["today"]),
                "metric_basis": incident["metric"]["basis"],
                "metric_reference": incident["metric"]["reference"],
                "metric_current": incident["metric"]["current"],
                "top_segment": None
                if top is None
                else " and ".join(f"{c['feature']} = {c['value']}" for c in top["conditions"]),
            }
        )
        for signal in incident["signals"]:
            tables["fact_incident_signal"].append(
                {
                    "incident_id": incident["id"],
                    "kind": signal["kind"],
                    "severity": signal["severity"],
                    "fired_on": signal["firedOn"],
                }
            )

    dates = sorted({row["date"] for row in tables["fact_model_day"]})
    for iso in dates:
        d = date.fromisoformat(iso)
        year, week, weekday = d.isocalendar()
        tables["dim_date"].append(
            {
                "date": iso,
                "year": d.year,
                "month": d.month,
                "month_name": d.strftime("%B"),
                "iso_year": year,
                "iso_week": week,
                "weekday": weekday,
                "weekday_name": d.strftime("%A"),
            }
        )
    return tables


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def to_csv(rows: Iterable[dict[str, Any]]) -> str:
    """RFC 4180 CSV with a header row; empty values for null, true/false for booleans."""
    rows = list(rows)
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {k: ("true" if v is True else "false" if v is False else v) for k, v in row.items()}
        )
    return out.getvalue()
