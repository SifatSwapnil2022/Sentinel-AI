"""One day of predictions, and the document the dashboard shows for it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from sentinel_core.drift import ColumnReference, detect_drift
from sentinel_core.errors import InsufficientDataError
from sentinel_core.performance import Metric, check_concept_drift, realized_confusion
from sentinel_core.slices import format_number

from ._json import r
from .monitors import Monitors

CONCEPT_WINDOW_DAYS = 7
"""The concept check pools labelled rows over a rolling week: a single day's labels are too few
to resolve a 2-3 point gap at 3 sigma, while a week's are not."""

MIN_LABELS_MEASURED = 30
MIN_LABELS_CONCEPT = 300

UNLABELLED = -1


@dataclass(frozen=True)
class DayData:
    """All predictions made on one UTC day, with whatever labels have arrived so far."""

    date: date
    frame: pd.DataFrame
    """Features, already coerced to the version's schema."""
    proba: npt.NDArray[np.float64]
    pred: npt.NDArray[np.int64]
    outcome: npt.NDArray[np.int64]
    """True label per row, or ``UNLABELLED`` (-1) when it hasn't arrived."""
    latency_ms: npt.NDArray[np.float64] | None = None

    def __post_init__(self) -> None:
        n = len(self.frame)
        sizes = {self.proba.size, self.pred.size, self.outcome.size}
        if self.latency_ms is not None:
            sizes.add(self.latency_ms.size)
        if sizes != {n}:
            raise ValueError(f"day {self.date}: arrays disagree on length ({n} rows, {sizes})")

    @property
    def labelled(self) -> npt.NDArray[np.bool_]:
        """Mask of rows whose label has arrived."""
        mask: npt.NDArray[np.bool_] = self.outcome != UNLABELLED
        return mask

    @property
    def rows(self) -> int:
        """Number of predictions."""
        return len(self.frame)


def concat(days: Sequence[DayData]) -> DayData:
    """Pool several days into one, dated by the last."""
    if not days:
        raise ValueError("nothing to concatenate")
    latencies = [d.latency_ms for d in days]
    return DayData(
        date=days[-1].date,
        frame=pd.concat([d.frame for d in days], ignore_index=True),
        proba=np.concatenate([d.proba for d in days]),
        pred=np.concatenate([d.pred for d in days]),
        outcome=np.concatenate([d.outcome for d in days]),
        latency_ms=None
        if any(x is None for x in latencies)
        else np.concatenate([x for x in latencies if x is not None]),
    )


def compute_day(monitors: Monitors, span: Sequence[DayData]) -> dict[str, Any] | None:
    """The dashboard document for the last day in ``span``.

    ``span`` holds up to ``CONCEPT_WINDOW_DAYS`` consecutive days ending at the day being
    computed; the earlier ones feed the rolling label check. Returns None for a day with no
    predictions.
    """
    if not span:
        return None
    day = span[-1]
    if day.rows == 0:
        return None

    estimate = monitors.cbpe.estimate(day.proba, day.pred)
    mv = monitors.pca.score(day.frame)
    check = label_check(monitors, span)
    return {
        "date": day.date.isoformat(),
        "rows": day.rows,
        "estimate": {
            m.value: {"value": r(e.value), "lower": r(e.lower), "upper": r(e.upper)}
            for m, e in estimate.metrics.items()
        },
        "measured": _measured(day),
        "labelCoverage": r(float(day.labelled.mean())),
        "labelCheck": check,
        # One-sided: measured accuracy *below* the estimate's band is a failure to act on;
        # a model doing better than estimated is not. ``labelCheck.flagged`` stays two-sided.
        "conceptFlag": None
        if check is None
        else check["flagged"] and check["measured"] < check["lower"],
        "multivariate": {
            "error": r(mv.reconstruction_error),
            "lower": r(mv.lower),
            "upper": r(mv.upper),
            "drifted": mv.drifted,
        },
        "p95LatencyMs": _p95(day.latency_ms),
        # Kept apart from the drift stats so a day on which a feature is entirely missing,
        # where no drift test can run, still reports it.
        "dataQuality": {
            name: {
                "nullRate": r(float(day.frame[name].isna().mean())),
                "referenceNullRate": r(ref.null_rate),
            }
            for name, ref in monitors.columns.items()
        },
        "features": {
            name: _feature_stats(ref, monitors.ref_frame[name], day.frame[name])
            for name, ref in monitors.columns.items()
        },
    }


def label_check(monitors: Monitors, span: Sequence[DayData]) -> dict[str, Any] | None:
    """The rolling-week comparison of estimated and measured accuracy on labelled rows."""
    pooled = concat(span[-CONCEPT_WINDOW_DAYS:])
    mask = pooled.labelled
    try:
        check = check_concept_drift(
            monitors.cbpe,
            pooled.outcome[mask],
            pooled.proba[mask],
            pooled.pred[mask],
            min_labeled=MIN_LABELS_CONCEPT,
        )
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


def _measured(day: DayData) -> dict[str, float | None] | None:
    mask = day.labelled
    if int(mask.sum()) < MIN_LABELS_MEASURED:
        return None
    confusion = realized_confusion(day.outcome[mask], day.pred[mask])
    return {m.value: r(confusion.metric(m)) for m in Metric}


def _p95(latency: npt.NDArray[np.float64] | None) -> float | None:
    if latency is None:
        return None
    finite = latency[np.isfinite(latency)]
    return None if finite.size == 0 else round(float(np.percentile(finite, 95)), 1)


def _feature_stats(
    ref: ColumnReference, ref_values: pd.Series, values: pd.Series
) -> dict[str, Any] | None:
    try:
        result = detect_drift(ref, values)
    except InsufficientDataError:  # every value missing on this day
        return None
    return {
        "statistic": r(result.statistic, 5),
        "drifted": result.drifted,
        "psi": r(result.psi),
        "nullRate": r(result.current_null_rate),
        "histogram": histogram(ref, ref_values, values),
    }


def histogram(ref: ColumnReference, ref_values: pd.Series, values: pd.Series) -> dict[str, Any]:
    """Share of rows per bin, reference against current, on the reference's own bins."""
    if ref.psi_edges is not None:
        inner = ref.psi_edges[1:-1]
        if inner.size == 0:
            labels = ["all"]
        else:
            labels = [f"< {format_number(inner[0])}"]
            labels += [f"{format_number(a)}–{format_number(b)}" for a, b in pairwise(inner)]
            labels.append(f"≥ {format_number(inner[-1])}")
        ref_counts = np.histogram(ref_values.dropna(), bins=ref.psi_edges)[0]
        cur_counts = np.histogram(values.dropna(), bins=ref.psi_edges)[0]
    else:
        ref_text, cur_text = ref_values.dropna().astype(str), values.dropna().astype(str)
        labels = sorted(set(ref_text) | set(cur_text))
        ref_vc, cur_vc = ref_text.value_counts(), cur_text.value_counts()
        ref_counts = np.array([ref_vc.get(c, 0) for c in labels])
        cur_counts = np.array([cur_vc.get(c, 0) for c in labels])
    return {
        "bins": labels,
        "reference": [r(v) for v in ref_counts / max(int(ref_counts.sum()), 1)],
        "current": [r(v) for v in cur_counts / max(int(cur_counts.sum()), 1)],
    }
