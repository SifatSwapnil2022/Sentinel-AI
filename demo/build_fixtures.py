"""Build the dashboard's demo data by running synthetic production traffic through sentinel_core.

Every number the dashboard shows comes from the real engine: drift statistics, multivariate
drift, CBPE estimates, concept-drift checks and slice root cause. Only the traffic is synthetic.

Usage:
    uv run python demo/build_fixtures.py [--out web/public/data]

The output is deterministic for a given seed, so the committed JSON only changes when the
engine or the scenarios change.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from scenarios import MODELS, ModelSpec, intensity, sample
from sentinel_core.drift import ColumnReference, PCAReconstructionDrift, detect_drift
from sentinel_core.errors import InsufficientDataError
from sentinel_core.performance import (
    CBPE,
    Metric,
    check_concept_drift,
    realized_confusion,
)
from sentinel_core.slices import (
    SliceBinner,
    correctness,
    expected_correctness,
    explain_change,
    format_number,
)

TODAY = date(2026, 10, 24)
DAYS = 30
SEED = 20261024
REFERENCE_ROWS = 6_000
TRAIN_ROWS = 8_000
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------- helpers


def r(x: float | None, digits: int = 4) -> float | None:
    """Round for JSON, mapping NaN to null."""
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), digits)


def day_date(i: int) -> date:
    return TODAY - timedelta(days=DAYS - 1 - i)


@dataclass
class Window:
    day: int
    frame: pd.DataFrame
    outcome: np.ndarray
    proba: np.ndarray
    pred: np.ndarray
    labelled: np.ndarray
    """Mask of rows whose label has arrived by TODAY."""


@dataclass
class Fitted:
    spec: ModelSpec
    model: Pipeline
    ref_frame: pd.DataFrame
    ref_outcome: np.ndarray
    ref_proba: np.ndarray
    ref_pred: np.ndarray
    cbpe: CBPE
    columns: dict[str, ColumnReference]
    pca: PCAReconstructionDrift
    binner: SliceBinner


def train(spec: ModelSpec, rng: np.random.Generator) -> Fitted:
    """Train the 'deployed' model on clean data and fit every monitor on a held-out reference."""
    x_train, y_train = sample(spec, rng, TRAIN_ROWS, 0.0)
    categorical = list(spec.categorical)
    encoder = ColumnTransformer(
        [
            (
                "cat",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                categorical,
            )
        ],
        remainder="passthrough",
    )
    model = Pipeline(
        [
            ("encode", encoder),
            (
                "gbm",
                HistGradientBoostingClassifier(
                    max_iter=150,
                    learning_rate=0.08,
                    categorical_features=list(range(len(categorical))),
                    random_state=0,
                ),
            ),
        ]
    ).fit(x_train.astype(dict.fromkeys(categorical, str)), y_train)

    ref_frame, ref_outcome = sample(spec, rng, REFERENCE_ROWS, 0.0)
    ref_proba = predict(model, ref_frame, spec)
    ref_pred = (ref_proba >= 0.5).astype(np.int64)
    return Fitted(
        spec=spec,
        model=model,
        ref_frame=ref_frame,
        ref_outcome=ref_outcome,
        ref_proba=ref_proba,
        ref_pred=ref_pred,
        cbpe=CBPE().fit(ref_outcome, ref_proba, ref_pred),
        columns={c: ColumnReference.fit(ref_frame[c], c) for c in ref_frame.columns},
        pca=PCAReconstructionDrift().fit(ref_frame),
        binner=SliceBinner().fit(ref_frame),
    )


def predict(model: Pipeline, frame: pd.DataFrame, spec: ModelSpec) -> np.ndarray:
    prepared = frame.astype(dict.fromkeys(spec.categorical, str))
    return np.asarray(model.predict_proba(prepared)[:, 1], dtype=np.float64)


def simulate(fitted: Fitted, rng: np.random.Generator) -> list[Window]:
    spec = fitted.spec
    windows = []
    for day in range(DAYS):
        n = int(spec.daily_rows * rng.uniform(0.88, 1.12))
        frame, outcome = sample(spec, rng, n, intensity(spec, day))
        proba = predict(fitted.model, frame, spec)
        age = DAYS - 1 - day  # days since this window's predictions were made
        lag = rng.uniform(1, spec.label_delay_days, n)
        windows.append(
            Window(
                day=day,
                frame=frame,
                outcome=outcome,
                proba=proba,
                pred=(proba >= 0.5).astype(np.int64),
                labelled=lag <= age,
            )
        )
    return windows


# ---------------------------------------------------------------------------- per-day metrics


def estimate_block(fitted: Fitted, w: Window) -> dict[str, Any]:
    est = fitted.cbpe.estimate(w.proba, w.pred)
    return {
        m.value: {"value": r(e.value), "lower": r(e.lower), "upper": r(e.upper)}
        for m, e in est.metrics.items()
    }


def measured_block(w: Window) -> dict[str, Any] | None:
    if w.labelled.sum() < 30:
        return None
    conf = realized_confusion(w.outcome[w.labelled], w.pred[w.labelled])
    return {m.value: r(conf.metric(m)) for m in Metric}


CONCEPT_WINDOW_DAYS = 7
"""The concept check pools labelled rows over a rolling week: a single day's labels are too few
to resolve a 2-3 point gap at 3 sigma, while a week's are not."""


def label_check(fitted: Fitted, windows: list[Window], day: int) -> dict[str, Any] | None:
    """The rolling-week comparison the concept-drift signal uses, exactly as the engine ran it."""
    span = windows[max(0, day - CONCEPT_WINDOW_DAYS + 1) : day + 1]
    mask = np.concatenate([w.labelled for w in span])
    outcome = np.concatenate([w.outcome for w in span])[mask]
    proba = np.concatenate([w.proba for w in span])[mask]
    pred = np.concatenate([w.pred for w in span])[mask]
    try:
        check = check_concept_drift(fitted.cbpe, outcome, proba, pred, min_labeled=300)
    except InsufficientDataError:
        return None
    return {
        "estimated": r(check.estimated),
        "lower": r(check.lower),
        "upper": r(check.upper),
        "measured": r(check.realized),
        "labelled": check.n_labeled,
        "flagged": check.flagged,
    }


def histogram(ref: ColumnReference, ref_values: pd.Series, cur_values: pd.Series) -> dict[str, Any]:
    if ref.psi_edges is not None:
        inner = ref.psi_edges[1:-1]
        labels = [f"< {format_number(inner[0])}"]
        labels += [f"{format_number(a)}–{format_number(b)}" for a, b in pairwise(inner)]
        labels.append(f"≥ {format_number(inner[-1])}")
        ref_counts = np.histogram(ref_values.dropna(), bins=ref.psi_edges)[0]
        cur_counts = np.histogram(cur_values.dropna(), bins=ref.psi_edges)[0]
    else:
        cats = sorted(set(ref_values.dropna().astype(str)) | set(cur_values.dropna().astype(str)))
        labels = cats
        ref_vc = ref_values.dropna().astype(str).value_counts()
        cur_vc = cur_values.dropna().astype(str).value_counts()
        ref_counts = np.array([ref_vc.get(c, 0) for c in cats])
        cur_counts = np.array([cur_vc.get(c, 0) for c in cats])
    return {
        "bins": labels,
        "reference": [r(v) for v in ref_counts / max(ref_counts.sum(), 1)],
        "current": [r(v) for v in cur_counts / max(cur_counts.sum(), 1)],
    }


# ---------------------------------------------------------------------------- alerts


PRIORITY = ("concept_drift", "estimate_drop", "multivariate", "input_drift")
"""Which signal leads an incident: the one that says most about what to do."""


@dataclass
class AlertRule:
    kind: str
    title: str
    severity: str


def first_sustained(flags: list[bool], run: int = 2) -> int | None:
    """Index of the first day that completes ``run`` consecutive True values."""
    streak = 0
    for i, f in enumerate(flags):
        streak = streak + 1 if f else 0
        if streak >= run:
            return i
    return None


def detect_alerts(
    fitted: Fitted, days: list[dict[str, Any]], features: list[dict[str, Any]]
) -> list[tuple[AlertRule, int]]:
    ref_acc = fitted.cbpe.reference_metrics[Metric.ACCURACY]
    found: list[tuple[AlertRule, int]] = []

    est_drop = [d["estimate"]["accuracy"]["upper"] < ref_acc for d in days]
    if (i := first_sustained(est_drop)) is not None:
        worst = min(d["estimate"]["accuracy"]["value"] for d in days[i:])
        severity = "critical" if worst < ref_acc - 0.05 else "warning"
        found.append((AlertRule("estimate_drop", "Estimated accuracy dropped", severity), i))

    concept = [bool(d["conceptFlag"]) for d in days]
    if (i := first_sustained(concept)) is not None:
        found.append(
            (
                AlertRule(
                    "concept_drift", "Measured accuracy fell outside the estimate", "critical"
                ),
                i,
            )
        )

    multi = [d["multivariate"]["drifted"] for d in days]
    if (i := first_sustained(multi)) is not None:
        found.append((AlertRule("multivariate", "Feature relationships changed", "warning"), i))

    drifted_counts = [sum(f["series"][k]["drifted"] for f in features) for k in range(len(days))]
    if (i := first_sustained([c >= 2 for c in drifted_counts])) is not None:
        found.append((AlertRule("input_drift", "Input distributions shifted", "warning"), i))
    return found


def investigate(
    fitted: Fitted, windows: list[Window], rule: AlertRule, opened: int, alert_id: str
) -> dict[str, Any]:
    spec = fitted.spec
    start = max(opened - 1, 0)
    span = windows[start:]
    frame = pd.concat([w.frame for w in span], ignore_index=True)
    proba = np.concatenate([w.proba for w in span])
    pred = np.concatenate([w.pred for w in span])
    outcome = np.concatenate([w.outcome for w in span])
    labelled = np.concatenate([w.labelled for w in span])

    calibrate = fitted.cbpe.calibrator.transform
    if rule.kind == "concept_drift":
        basis = "measured"
        ref_scores = correctness(fitted.ref_outcome, fitted.ref_pred)
        cur_frame = frame[labelled].reset_index(drop=True)
        cur_scores = correctness(outcome[labelled], pred[labelled])
        cur_proba, cur_pred = proba[labelled], pred[labelled]
        cur_outcome: np.ndarray | None = outcome[labelled]
    else:
        basis = "estimated"
        ref_scores = expected_correctness(calibrate(fitted.ref_proba), fitted.ref_pred)
        cur_frame = frame
        cur_scores = expected_correctness(calibrate(proba), pred)
        cur_proba, cur_pred = proba, pred
        cur_outcome = np.where(labelled, outcome, -1)

    report = explain_change(
        fitted.binner.transform(fitted.ref_frame),
        ref_scores,
        fitted.binner.transform(cur_frame),
        cur_scores,
        min_slice_size=60,
        max_findings=6,
    )
    # Summarise with the partition that explains most: the top finding's when a concentrated
    # slice exists; otherwise the one with the largest traffic-mix effect (a broad shift).
    if report.findings:
        lead = report.findings[0].features
        top_partition = next(p for p in report.partitions if p.features == lead)
    else:
        top_partition = min(report.partitions, key=lambda p: p.mix_effect, default=None)

    ref_bins = fitted.binner.transform(fitted.ref_frame)
    cur_bins = fitted.binner.transform(cur_frame)
    mix_shifts = []
    for feature in ref_bins.columns:
        ref_share = ref_bins[feature].value_counts(normalize=True)
        cur_share = cur_bins[feature].value_counts(normalize=True)
        for value in set(ref_share.index) | set(cur_share.index):
            before, after = float(ref_share.get(value, 0.0)), float(cur_share.get(value, 0.0))
            mix_shifts.append(
                {
                    "feature": feature,
                    "value": str(value),
                    "reference": r(before),
                    "current": r(after),
                }
            )
    mix_shifts.sort(key=lambda m: -abs(m["current"] - m["reference"]))
    mix_shifts = mix_shifts[:6]
    findings = [
        {
            "conditions": [
                {"feature": f, "value": v} for f, v in zip(x.features, x.values, strict=True)
            ],
            "nReference": x.n_reference,
            "nCurrent": x.n_current,
            "shareReference": r(x.share_reference),
            "shareCurrent": r(x.share_current),
            "metricReference": r(x.metric_reference),
            "metricCurrent": r(x.metric_current),
            "contribution": r(x.contribution, 5),
            "shareOfDrop": r(x.share_of_drop),
        }
        for x in report.findings
    ]

    sample_rows: dict[str, Any] = {"columns": list(frame.columns), "rows": []}
    if report.findings:
        worst = report.findings[0]
        labels = fitted.binner.transform(cur_frame)
        mask = np.ones(len(cur_frame), dtype=bool)
        for f, v in zip(worst.features, worst.values, strict=True):
            mask &= labels[f].to_numpy() == v
        idx = np.flatnonzero(mask)[:12]
        for i in idx:
            row = cur_frame.iloc[i]
            sample_rows["rows"].append(
                {
                    "values": [_jsonable(row[c]) for c in cur_frame.columns],
                    "score": r(float(cur_proba[i]), 3),
                    "prediction": int(cur_pred[i]),
                    "outcome": None
                    if cur_outcome is None or cur_outcome[i] < 0
                    else int(cur_outcome[i]),
                }
            )

    correlations: list[dict[str, Any]] = []
    if rule.kind == "multivariate":
        numeric = [c for c in frame.columns if c not in spec.categorical]
        ref_corr = fitted.ref_frame[numeric].corr()
        cur_corr = frame[numeric].corr()
        correlations = [
            {
                "a": a,
                "b": b,
                "reference": r(ref_corr.loc[a, b], 3),
                "current": r(cur_corr.loc[a, b], 3),
            }
            for a, b in combinations(numeric, 2)
        ]
        correlations.sort(key=lambda c: -abs((c["current"] or 0) - (c["reference"] or 0)))
        correlations = correlations[:5]

    return {
        "id": alert_id,
        "modelId": spec.id,
        "kind": rule.kind,
        "title": rule.title,
        "severity": rule.severity,
        "openedOn": day_date(opened).isoformat(),
        "window": {
            "from": day_date(start).isoformat(),
            "to": TODAY.isoformat(),
            "rows": len(cur_frame),
        },
        "metric": {
            "name": "accuracy",
            "basis": basis,
            "reference": r(report.metric_reference),
            "current": r(report.metric_current),
            "performanceEffect": r(top_partition.performance_effect, 5) if top_partition else None,
            "mixEffect": r(top_partition.mix_effect, 5) if top_partition else None,
            "partition": list(top_partition.features) if top_partition else [],
        },
        "findings": findings,
        "sampleRows": sample_rows,
        "correlationChanges": correlations,
        "mixShifts": mix_shifts,
    }


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return r(float(v), 3)
    return str(v)


# ---------------------------------------------------------------------------- assembly


def build_model(spec: ModelSpec, rng: np.random.Generator) -> tuple[dict, dict, list[dict]]:
    fitted = train(spec, rng)
    windows = simulate(fitted, rng)

    days = []
    for w in windows:
        mv = fitted.pca.score(w.frame)
        days.append(
            {
                "date": day_date(w.day).isoformat(),
                "rows": len(w.frame),
                "estimate": estimate_block(fitted, w),
                "measured": measured_block(w),
                "labelCoverage": r(float(w.labelled.mean())),
                "labelCheck": (check := label_check(fitted, windows, w.day)),
                "conceptFlag": None if check is None else check["flagged"],
                "multivariate": {
                    "error": r(mv.reconstruction_error),
                    "lower": r(mv.lower),
                    "upper": r(mv.upper),
                    "drifted": mv.drifted,
                },
                "p95LatencyMs": round(
                    float(rng.lognormal(np.log(38), 0.08))
                    * (1.6 if spec.id == "fraud-screen" else 1.0)
                ),
            }
        )

    features = []
    for name, ref in fitted.columns.items():
        series = []
        for w in windows:
            res = detect_drift(ref, w.frame[name])
            series.append(
                {
                    "date": day_date(w.day).isoformat(),
                    "statistic": r(res.statistic, 5),
                    "drifted": res.drifted,
                    "psi": r(res.psi),
                }
            )
        latest = windows[-1].frame[name]
        last = detect_drift(ref, latest)
        features.append(
            {
                "name": name,
                "kind": ref.kind.value,
                "method": ref.method.value,
                "threshold": ref.threshold,
                "isPValue": ref.method.is_p_value,
                "series": series,
                "latest": {
                    "statistic": r(last.statistic, 5),
                    "drifted": last.drifted,
                    "psi": r(last.psi),
                    "nullRate": r(last.current_null_rate),
                },
                "histogram": histogram(ref, fitted.ref_frame[name], latest),
            }
        )

    # Signals on one model form one incident: the earliest signal leads (ties go to the most
    # specific), the rest are listed inside it, and the window starts at the earliest signal.
    signals = detect_alerts(fitted, days, features)
    alerts = []
    if signals:
        primary, _ = min(signals, key=lambda s: (s[1], PRIORITY.index(s[0].kind)))
        opened = min(day for _, day in signals)
        incident = investigate(fitted, windows, primary, opened, f"{spec.id}-1")
        incident["signals"] = [
            {
                "kind": rule.kind,
                "title": rule.title,
                "severity": rule.severity,
                "firedOn": day_date(day).isoformat(),
            }
            for rule, day in sorted(signals, key=lambda s: s[1])
        ]
        if any(rule.severity == "critical" for rule, _ in signals):
            incident["severity"] = "critical"
        incident["driftedFeatures"] = [
            {
                "name": f["name"],
                "method": f["method"],
                "statistic": f["latest"]["statistic"],
                "threshold": f["threshold"],
                "isPValue": f["isPValue"],
                "psi": f["latest"]["psi"],
            }
            for f in features
            if f["latest"]["drifted"]
        ]
        alerts.append(incident)

    ref = fitted.cbpe.reference_metrics
    model_doc = {
        "schemaVersion": SCHEMA_VERSION,
        "id": spec.id,
        "name": spec.name,
        "version": spec.version,
        "team": spec.team,
        "description": spec.description,
        "labelDelayDays": spec.label_delay_days,
        "referenceRows": REFERENCE_ROWS,
        "referenceMetrics": {m.value: r(v) for m, v in ref.items()},
        "calibration": {
            "applied": fitted.cbpe.calibrator.applied,
            "eceBefore": r(fitted.cbpe.calibrator.ece_before),
            "eceAfter": r(fitted.cbpe.calibrator.ece_after),
        },
        "days": days,
        "features": features,
        "alertIds": [a["id"] for a in alerts],
    }

    rank = {"critical": 2, "warning": 1}
    worst = max(alerts, key=lambda a: rank[a["severity"]], default=None)
    last = days[-1]
    summary = {
        "id": spec.id,
        "name": spec.name,
        "version": spec.version,
        "team": spec.team,
        "status": worst["severity"] if worst else "healthy",
        "statusReason": worst["title"] if worst else "No open alerts",
        "referenceAccuracy": r(ref[Metric.ACCURACY]),
        "estimate": last["estimate"]["accuracy"],
        "measured": {
            **_latest_measured(days),
            "coverage": r(float(np.mean([d["labelCoverage"] for d in days[-7:]]))),
        },
        "predictionsPerDay": int(np.mean([d["rows"] for d in days[-7:]])),
        "p95LatencyMs": last["p95LatencyMs"],
        "driftedFeatures": sum(f["latest"]["drifted"] for f in features),
        "totalFeatures": len(features),
        "multivariateDrifted": last["multivariate"]["drifted"],
        "openAlerts": len(alerts),
        "trend": [d["estimate"]["accuracy"]["value"] for d in days[-14:]],
    }
    return summary, model_doc, alerts


def _latest_measured(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Most recent day whose labels are at least half in, so the figure is trustworthy."""
    for d in reversed(days):
        if d["measured"] is not None and d["labelCoverage"] >= 0.5:
            return {"value": d["measured"]["accuracy"], "asOf": d["date"]}
    return {"value": None, "asOf": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("web/public/data"))
    args = parser.parse_args()
    out: Path = args.out
    (out / "models").mkdir(parents=True, exist_ok=True)
    (out / "alerts").mkdir(parents=True, exist_ok=True)

    summaries, alert_index = [], []
    for k, spec in enumerate(MODELS):
        rng = np.random.default_rng(SEED + k)
        summary, model_doc, alerts = build_model(spec, rng)
        summaries.append(summary)
        _write(out / "models" / f"{spec.id}.json", model_doc)
        for a in alerts:
            _write(out / "alerts" / f"{a['id']}.json", a)
            alert_index.append(
                {
                    "id": a["id"],
                    "modelId": a["modelId"],
                    "kind": a["kind"],
                    "title": a["title"],
                    "severity": a["severity"],
                    "openedOn": a["openedOn"],
                }
            )
        print(f"{spec.id}: {summary['status']:<8} alerts={len(alerts)}")

    alert_index.sort(key=lambda a: (a["severity"] != "critical", a["openedOn"]))
    _write(
        out / "fleet.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "today": TODAY.isoformat(),
            "windowDays": DAYS,
            "models": summaries,
            "alerts": alert_index,
        },
    )


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
