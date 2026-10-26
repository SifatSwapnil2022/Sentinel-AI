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


MISSING_JUMP = 0.05
"""A feature whose share of missing values rises this far above its reference rate (5 points)
fails the data-quality rule."""

MISSING_CRITICAL = 0.25
"""Missing values this far above reference make the data-quality signal critical."""


class SignalKind(StrEnum):
    """The ways a model can go wrong that Sentinel detects."""

    CONCEPT_DRIFT = "concept_drift"
    DATA_QUALITY = "data_quality"
    ESTIMATE_DROP = "estimate_drop"
    MULTIVARIATE = "multivariate"
    INPUT_DRIFT = "input_drift"


TITLES = {
    SignalKind.CONCEPT_DRIFT: "Measured accuracy fell outside the estimate",
    SignalKind.DATA_QUALITY: "Feature values went missing",
    SignalKind.ESTIMATE_DROP: "Estimated accuracy dropped",
    SignalKind.MULTIVARIATE: "Feature relationships changed",
    SignalKind.INPUT_DRIFT: "Input distributions shifted",
}

PRIORITY = (
    SignalKind.CONCEPT_DRIFT,
    SignalKind.DATA_QUALITY,
    SignalKind.ESTIMATE_DROP,
    SignalKind.MULTIVARIATE,
    SignalKind.INPUT_DRIFT,
)
"""Tie-break for which signal leads an incident: the one that says most about what to do. A
data-quality problem leads an accuracy drop it causes, because fixing the pipeline is the fix."""


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


def missing_jump(day: dict[str, Any]) -> float:
    """The largest rise in a feature's share of missing values over its reference rate."""
    quality = day.get("dataQuality") or {}
    return max(
        (q["nullRate"] - q["referenceNullRate"] for q in quality.values()),
        default=0.0,
    )


def rules_holding(reference_accuracy: float, day: dict[str, Any]) -> set[SignalKind]:
    """Which alert rules' conditions hold on one day, before the sustained-days check."""
    held: set[SignalKind] = set()
    upper = day["estimate"]["accuracy"]["upper"]
    if upper is not None and upper < reference_accuracy:
        held.add(SignalKind.ESTIMATE_DROP)
    if day["conceptFlag"] is True:
        held.add(SignalKind.CONCEPT_DRIFT)
    if day["multivariate"]["drifted"]:
        held.add(SignalKind.MULTIVARIATE)
    if sum(bool(f and f["drifted"]) for f in day["features"].values()) >= 2:
        held.add(SignalKind.INPUT_DRIFT)
    if missing_jump(day) > MISSING_JUMP:
        held.add(SignalKind.DATA_QUALITY)
    return held


def rule_holds(reference_accuracy: float, day: dict[str, Any]) -> bool:
    """Whether any alert rule's condition holds on one day."""
    return bool(rules_holding(reference_accuracy, day))


def detect_signals(reference_accuracy: float, days: Sequence[dict[str, Any]]) -> list[Signal]:
    """Every rule that fired in ``days`` (day documents in date order), with when it first did."""
    held = [rules_holding(reference_accuracy, d) for d in days]
    found: list[Signal] = []
    for kind in PRIORITY:
        i = _first_sustained([kind in h for h in held])
        if i is None:
            continue
        rest = days[i:]
        if kind is SignalKind.ESTIMATE_DROP:
            worst = min(d["estimate"]["accuracy"]["value"] for d in rest)
            severity = "critical" if worst < reference_accuracy - CRITICAL_DROP else "warning"
        elif kind is SignalKind.DATA_QUALITY:
            severity = "critical" if max(map(missing_jump, rest)) > MISSING_CRITICAL else "warning"
        elif kind is SignalKind.CONCEPT_DRIFT:
            severity = "critical"
        else:
            severity = "warning"
        found.append(Signal(kind, severity, date.fromisoformat(days[i]["date"])))
    return found


@dataclass(frozen=True)
class Episode:
    """A stretch of trouble: the signals that fired, when it began, and when it ended if it has."""

    signals: list[Signal]
    lead: Signal
    opened_on: date
    resolved_on: date | None
    """First day of the closing quiet run, once it has lasted ``QUIET_DAYS_TO_RESOLVE`` days."""
    last_day: date
    """Last day of the episode's trouble: the day before ``resolved_on``, or the latest day."""

    @property
    def severity(self) -> str:
        """Critical if any of its signals is."""
        return "critical" if any(s.severity == "critical" for s in self.signals) else "warning"


def episodes(reference_accuracy: float, days: Sequence[dict[str, Any]]) -> list[Episode]:
    """Split a model's days into episodes of trouble, oldest first.

    An episode opens on the day some rule has held for ``SUSTAINED_DAYS`` consecutive days and
    resolves after ``QUIET_DAYS_TO_RESOLVE`` consecutive days on which no rule holds. The result
    depends only on the day documents, so the worker and the demo builder agree, and replaying
    history (a backfill, late labels) reproduces it.
    """
    held = [rules_holding(reference_accuracy, d) for d in days]
    dates = [date.fromisoformat(d["date"]) for d in days]
    spans: list[tuple[int, int | None]] = []
    start: int | None = None
    quiet = 0
    for i, rules in enumerate(held):
        if start is None:
            if i >= SUSTAINED_DAYS - 1 and set.intersection(*held[i - SUSTAINED_DAYS + 1 : i + 1]):
                start, quiet = i, 0
        elif rules:
            quiet = 0
        else:
            quiet += 1
            if quiet >= QUIET_DAYS_TO_RESOLVE:
                spans.append((start, i - quiet + 1))
                start, quiet = None, 0
    if start is not None:
        spans.append((start, None))

    out = []
    for begin, end in spans:
        stop = len(days) if end is None else end
        window = days[max(0, begin - SUSTAINED_DAYS + 1) : stop]
        signals = [
            s for s in detect_signals(reference_accuracy, window) if s.fired_on >= dates[begin]
        ]
        if not signals:  # cannot happen: the opening day completed a sustained run
            continue
        out.append(
            Episode(
                signals=signals,
                lead=lead_signal(signals),
                opened_on=dates[begin],
                resolved_on=None if end is None else dates[end],
                last_day=dates[stop - 1] if end is None else dates[end - 1],
            )
        )
    return out


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
