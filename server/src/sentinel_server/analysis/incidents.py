"""Alert rules over day documents, and the investigation behind an incident."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from itertools import combinations
from typing import Any

import numpy as np

from sentinel_core.slices import (
    PartitionSummary,
    correctness,
    expected_correctness,
    explain_change,
)

from ._json import jsonable, r
from .days import DayData
from .monitors import Monitors

SUSTAINED_DAYS = 2
"""A rule must hold on this many consecutive days to fire, so one noisy day doesn't page anyone."""

CRITICAL_DROP = 0.05
"""An estimated drop of more than this (5 points) below reference makes the signal critical."""

QUIET_DAYS_TO_RESOLVE = 7
"""An incident resolves after this many consecutive days on which no rule holds. A week is the
label check's window: by then every label it pools post-dates the problem, so a quiet week is
evidence of recovery rather than of labels not having arrived yet. Opening takes two days and
resolving seven, so an effect near the detection limit doesn't open and close repeatedly."""


class SignalKind(StrEnum):
    """The four ways a model can go wrong that Sentinel detects."""

    CONCEPT_DRIFT = "concept_drift"
    ESTIMATE_DROP = "estimate_drop"
    MULTIVARIATE = "multivariate"
    INPUT_DRIFT = "input_drift"


TITLES = {
    SignalKind.CONCEPT_DRIFT: "Measured accuracy fell outside the estimate",
    SignalKind.ESTIMATE_DROP: "Estimated accuracy dropped",
    SignalKind.MULTIVARIATE: "Feature relationships changed",
    SignalKind.INPUT_DRIFT: "Input distributions shifted",
}

PRIORITY = (
    SignalKind.CONCEPT_DRIFT,
    SignalKind.ESTIMATE_DROP,
    SignalKind.MULTIVARIATE,
    SignalKind.INPUT_DRIFT,
)
"""Tie-break for which signal leads an incident: the one that says most about what to do."""


@dataclass(frozen=True)
class Signal:
    """A rule that held for ``SUSTAINED_DAYS`` days, firing on ``fired_on``."""

    kind: SignalKind
    severity: str
    fired_on: date

    @property
    def title(self) -> str:
        """Human-readable name."""
        return TITLES[self.kind]

    def to_json(self) -> dict[str, str]:
        """Serialisable form."""
        return {
            "kind": self.kind.value,
            "title": self.title,
            "severity": self.severity,
            "firedOn": self.fired_on.isoformat(),
        }


def rule_holds(reference_accuracy: float, day: dict[str, Any]) -> bool:
    """Whether any alert rule's condition holds on one day (before the sustained-days check)."""
    upper = day["estimate"]["accuracy"]["upper"]
    drifted = sum(bool(f and f["drifted"]) for f in day["features"].values())
    return (
        (upper is not None and upper < reference_accuracy)
        or day["conceptFlag"] is True
        or bool(day["multivariate"]["drifted"])
        or drifted >= 2
    )


def detect_signals(reference_accuracy: float, days: Sequence[dict[str, Any]]) -> list[Signal]:
    """Every rule that fired in ``days`` (day documents in date order), with when it fired."""
    found: list[Signal] = []
    dates = [date.fromisoformat(d["date"]) for d in days]

    upper = [d["estimate"]["accuracy"]["upper"] for d in days]
    if (
        i := _first_sustained([u is not None and u < reference_accuracy for u in upper])
    ) is not None:
        values = [d["estimate"]["accuracy"]["value"] for d in days[i:]]
        worst = min(v for v in values if v is not None)
        severity = "critical" if worst < reference_accuracy - CRITICAL_DROP else "warning"
        found.append(Signal(SignalKind.ESTIMATE_DROP, severity, dates[i]))

    if (i := _first_sustained([d["conceptFlag"] is True for d in days])) is not None:
        found.append(Signal(SignalKind.CONCEPT_DRIFT, "critical", dates[i]))

    if (i := _first_sustained([d["multivariate"]["drifted"] for d in days])) is not None:
        found.append(Signal(SignalKind.MULTIVARIATE, "warning", dates[i]))

    drifted = [sum(bool(f and f["drifted"]) for f in d["features"].values()) for d in days]
    if (i := _first_sustained([c >= 2 for c in drifted])) is not None:
        found.append(Signal(SignalKind.INPUT_DRIFT, "warning", dates[i]))
    return found


@dataclass(frozen=True)
class Episode:
    """A stretch of trouble: the signals that fired, and when it ended if it has."""

    signals: list[Signal]
    lead: Signal
    opened_on: date
    resolved_on: date | None
    """First day of the closing quiet run, once it has lasted ``QUIET_DAYS_TO_RESOLVE`` days."""


def evaluate(reference_accuracy: float, days: Sequence[dict[str, Any]]) -> Episode | None:
    """The episode in ``days`` (those since the previous incident resolved), if any rule fired.

    Shared by the worker and the demo builder, so they open and resolve incidents identically.
    """
    signals = detect_signals(reference_accuracy, days)
    if not signals:
        return None
    opened = min(s.fired_on for s in signals)
    quiet = 0
    for day in reversed(days):
        if date.fromisoformat(day["date"]) <= opened or rule_holds(reference_accuracy, day):
            break
        quiet += 1
    resolved = date.fromisoformat(days[-quiet]["date"]) if quiet >= QUIET_DAYS_TO_RESOLVE else None
    return Episode(signals, lead_signal(signals), opened, resolved)


def lead_signal(signals: Sequence[Signal]) -> Signal:
    """The signal an incident is named after: the earliest, ties going to the most specific."""
    return min(signals, key=lambda s: (s.fired_on, PRIORITY.index(s.kind)))


def investigate(
    monitors: Monitors,
    lead: SignalKind,
    current: DayData,
    *,
    min_slice_size: int = 60,
    max_findings: int = 6,
    sample_rows: int = 12,
) -> dict[str, Any]:
    """Where a change comes from: decomposition, ranked segments, examples, traffic shifts.

    Concept drift is investigated on measured accuracy over labelled rows; everything else on
    estimated accuracy over all rows, since labels may not exist yet.
    """
    calibrate = monitors.cbpe.calibrator.transform
    labelled = current.labelled
    if lead is SignalKind.CONCEPT_DRIFT:
        basis = "measured"
        ref_scores = correctness(monitors.ref_outcome, monitors.ref_pred)
        frame = current.frame[labelled].reset_index(drop=True)
        scores = correctness(current.outcome[labelled], current.pred[labelled])
        proba, pred, outcome = (
            current.proba[labelled],
            current.pred[labelled],
            current.outcome[labelled],
        )
    else:
        basis = "estimated"
        ref_scores = expected_correctness(calibrate(monitors.ref_proba), monitors.ref_pred)
        frame = current.frame.reset_index(drop=True)
        scores = expected_correctness(calibrate(current.proba), current.pred)
        proba, pred, outcome = current.proba, current.pred, current.outcome

    ref_bins = monitors.binner.transform(monitors.ref_frame)
    cur_bins = monitors.binner.transform(frame)
    report = explain_change(
        ref_bins,
        ref_scores,
        cur_bins,
        scores,
        min_slice_size=min_slice_size,
        max_findings=max_findings,
    )
    # Summarise with the partition that explains most: the top finding's when a concentrated
    # slice exists; otherwise the one with the largest traffic-mix effect (a broad shift).
    if report.findings:
        lead_features = report.findings[0].features
        partition: PartitionSummary | None = next(
            p for p in report.partitions if p.features == lead_features
        )
    else:
        partition = min(report.partitions, key=lambda p: p.mix_effect, default=None)

    examples: list[dict[str, Any]] = []
    if report.findings:
        top = report.findings[0]
        mask = np.ones(len(frame), dtype=bool)
        for feature, value in zip(top.features, top.values, strict=True):
            mask &= cur_bins[feature].to_numpy() == value
        for i in np.flatnonzero(mask)[:sample_rows]:
            row = frame.iloc[i]
            examples.append(
                {
                    "values": [jsonable(row[c]) for c in frame.columns],
                    "score": r(float(proba[i]), 3),
                    "prediction": int(pred[i]),
                    "outcome": None if outcome[i] < 0 else int(outcome[i]),
                }
            )

    return {
        "window": {"rows": len(frame)},
        "metric": {
            "name": "accuracy",
            "basis": basis,
            "reference": r(report.metric_reference),
            "current": r(report.metric_current),
            "performanceEffect": r(partition.performance_effect, 5) if partition else None,
            "mixEffect": r(partition.mix_effect, 5) if partition else None,
            "partition": list(partition.features) if partition else [],
        },
        "findings": [
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
        ],
        "sampleRows": {"columns": list(frame.columns), "rows": examples},
        "correlationChanges": _correlation_changes(monitors, current)
        if lead is SignalKind.MULTIVARIATE
        else [],
        "mixShifts": _mix_shifts(ref_bins, cur_bins),
    }


def _first_sustained(flags: Sequence[bool], run: int = SUSTAINED_DAYS) -> int | None:
    """Index of the first day that completes ``run`` consecutive True values."""
    streak = 0
    for i, flag in enumerate(flags):
        streak = streak + 1 if flag else 0
        if streak >= run:
            return i
    return None


def _correlation_changes(
    monitors: Monitors, current: DayData, top: int = 5
) -> list[dict[str, Any]]:
    numeric = [c for c in monitors.schema.names if c not in monitors.schema.categorical]
    if len(numeric) < 2:
        return []
    ref_corr = monitors.ref_frame[numeric].corr().to_numpy(dtype=np.float64)
    cur_corr = current.frame[numeric].corr().to_numpy(dtype=np.float64)
    found: list[tuple[str, str, float, float]] = []
    for (i, a), (j, b) in combinations(enumerate(numeric), 2):
        before, after = r(float(ref_corr[i, j]), 3), r(float(cur_corr[i, j]), 3)
        if before is not None and after is not None:  # constant columns have no correlation
            found.append((a, b, before, after))
    found.sort(key=lambda p: -abs(p[3] - p[2]))
    return [{"a": a, "b": b, "reference": x, "current": y} for a, b, x, y in found[:top]]


def _mix_shifts(ref_bins: Any, cur_bins: Any, top: int = 6) -> list[dict[str, Any]]:
    shifts: list[dict[str, Any]] = []
    for feature in ref_bins.columns:
        ref_share = ref_bins[feature].value_counts(normalize=True)
        cur_share = cur_bins[feature].value_counts(normalize=True)
        shifts.extend(
            {
                "feature": feature,
                "value": str(value),
                "reference": r(float(ref_share.get(value, 0.0))),
                "current": r(float(cur_share.get(value, 0.0))),
            }
            for value in set(ref_share.index) | set(cur_share.index)
        )
    shifts.sort(key=lambda s: (-abs(s["current"] - s["reference"]), s["feature"], s["value"]))
    return shifts[:top]
