"""Explain a change in a metric by data slice, separating "got worse" from "traffic changed".

For any partition of rows into slices ``s`` (e.g. by income band), the change in a mean metric
splits exactly into two parts (a shift-share decomposition)::

    Δ = Σ_s w_cur(s) · (m_cur(s) − m_ref(s))     performance effect: the model got worse in s
      + Σ_s (w_cur(s) − w_ref(s)) · m_ref(s)      mix effect: more traffic from harder slices

where ``w`` is a slice's share of rows and ``m`` its mean metric. Slices are ranked by their
performance-effect term, so the alert can say *where* the model degraded, while a shift in who
is sending traffic is reported separately instead of being blamed on the model.

The metric must be a mean of per-row scores: correctness for realized accuracy
(:func:`correctness`), or expected correctness for estimated accuracy
(:func:`expected_correctness`). Slices seen only in the current window take the overall
reference mean as ``m_ref``; the identity above still holds exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import numpy.typing as npt
import pandas as pd

from sentinel_core._validation import ArrayLike, as_1d, as_binary, as_probabilities, require_rows
from sentinel_core.errors import InvalidInputError

_SCORE = "__score__"


@dataclass(frozen=True, slots=True)
class SliceFinding:
    """One slice's contribution to a metric change."""

    features: tuple[str, ...]
    values: tuple[str, ...]
    n_reference: int
    n_current: int
    share_reference: float
    share_current: float
    metric_reference: float
    metric_current: float
    contribution: float
    """Performance-effect term ``w_cur · (m_cur − m_ref)``; negative pulled the metric down."""
    share_of_drop: float
    """``contribution`` as a share of its partition's total performance effect (NaN if no drop)."""

    @property
    def label(self) -> str:
        """Readable slice name, e.g. ``"income: < 20k · region: C"``."""
        return " · ".join(f"{f}: {v}" for f, v in zip(self.features, self.values, strict=True))


@dataclass(frozen=True, slots=True)
class PartitionSummary:
    """Decomposition of the metric change for one way of slicing the data."""

    features: tuple[str, ...]
    performance_effect: float
    mix_effect: float


@dataclass(frozen=True, slots=True)
class RootCauseReport:
    """Ranked slices behind a metric change."""

    metric_reference: float
    metric_current: float
    findings: tuple[SliceFinding, ...]
    """Slices that pulled the metric down, most harmful first."""
    partitions: tuple[PartitionSummary, ...]
    """Every partition examined, ordered by performance effect (most negative first)."""

    @property
    def delta(self) -> float:
        """Change in the metric, current minus reference."""
        return self.metric_current - self.metric_reference


def correctness(y_true: ArrayLike, y_pred: ArrayLike) -> npt.NDArray[np.float64]:
    """Per-row 1/0 correctness; its mean is realized accuracy."""
    y = as_binary(y_true, "y_true")
    pred = as_binary(y_pred, "y_pred")
    if y.size != pred.size:
        raise InvalidInputError("y_true and y_pred must have the same length")
    return np.asarray(y == pred, dtype=np.float64)


def expected_correctness(y_proba: ArrayLike, y_pred: ArrayLike) -> npt.NDArray[np.float64]:
    """Per-row probability of being correct; its mean is CBPE's estimated accuracy.

    ``y_proba`` must already be calibrated (see :class:`~sentinel_core.performance.CBPE`).
    """
    p = as_probabilities(y_proba, "y_proba")
    pred = as_binary(y_pred, "y_pred")
    if p.size != pred.size:
        raise InvalidInputError("y_proba and y_pred must have the same length")
    return np.asarray(np.where(pred == 1, p, 1 - p), dtype=np.float64)


def explain_change(
    reference_slices: pd.DataFrame,
    reference_scores: ArrayLike,
    current_slices: pd.DataFrame,
    current_scores: ArrayLike,
    *,
    min_slice_size: int = 50,
    include_pairs: bool = True,
    pair_features: int = 10,
    max_findings: int = 10,
    specificity: float = 0.8,
    min_concentration: float = 1.5,
) -> RootCauseReport:
    """Rank slices by how much they pulled a mean metric down between two windows.

    Args:
        reference_slices: Slice labels per reference row (e.g. from ``SliceBinner.transform``).
        reference_scores: Per-row metric scores for the reference rows.
        current_slices: Slice labels per current row, same columns as the reference.
        current_scores: Per-row metric scores for the current rows.
        min_slice_size: Slices need at least this many rows in *both* windows to be reported,
            so small, noisy slices cannot top the list.
        include_pairs: Also examine pairs of features.
        pair_features: Pairs are formed among this many single features with the most
            harmful slices, which bounds the search to ``k·(k−1)/2`` partitions.
        max_findings: Longest list of findings returned.
        specificity: A single-feature slice is dropped when one pair slice inside it accounts
            for at least this share of its contribution. "region: C" adds nothing once
            "region: C · income: < 14k" explains 80% of its drop; the narrower slice is the
            more useful answer.
        min_concentration: A slice must have worsened at least this many times more than the
            rows of its partition did on average. Without it, a slice holding 95% of traffic
            "explains" 95% of any drop while saying nothing about where the drop is. 0 turns
            the check off.

    Raises:
        InvalidInputError: Columns or lengths do not line up, or scores are not finite.
        InsufficientDataError: Either window is empty.
    """
    features = [str(c) for c in reference_slices.columns]
    if [str(c) for c in current_slices.columns] != features:
        raise InvalidInputError("reference and current slices must have the same columns")
    if not features:
        raise InvalidInputError("no slice features given")
    ref = _with_scores(reference_slices, reference_scores, "reference")
    cur = _with_scores(current_slices, current_scores, "current")
    m_ref, m_cur = float(ref[_SCORE].mean()), float(cur[_SCORE].mean())

    summaries: list[PartitionSummary] = []
    findings: list[SliceFinding] = []
    worst_single: dict[str, float] = {}
    for feature in features:
        summary, found = _partition((feature,), ref, cur, m_ref, min_slice_size, min_concentration)
        summaries.append(summary)
        findings.extend(found)
        if found:
            worst_single[feature] = min(f.contribution for f in found)

    if not 0 < specificity <= 1:
        raise InvalidInputError("specificity must be in (0, 1]")
    if min_concentration < 0:
        raise InvalidInputError("min_concentration must be non-negative")

    if include_pairs and len(worst_single) >= 2:
        candidates = sorted(worst_single, key=worst_single.__getitem__)[:pair_features]
        for pair in combinations(sorted(candidates, key=features.index), 2):
            summary, found = _partition(pair, ref, cur, m_ref, min_slice_size, min_concentration)
            summaries.append(summary)
            findings.extend(found)

    findings = _prefer_specific(findings, specificity)
    findings.sort(key=lambda f: f.contribution)
    summaries.sort(key=lambda s: s.performance_effect)
    return RootCauseReport(
        metric_reference=m_ref,
        metric_current=m_cur,
        findings=tuple(findings[:max_findings]),
        partitions=tuple(summaries),
    )


# ---------------------------------------------------------------------------- internals


def _prefer_specific(findings: list[SliceFinding], specificity: float) -> list[SliceFinding]:
    """Drop single-feature findings that a narrower pair finding already explains."""
    pairs = [f for f in findings if len(f.features) == 2]
    if not pairs:
        return findings

    def explained(single: SliceFinding) -> bool:
        part = (single.features[0], single.values[0])
        return any(
            part in zip(p.features, p.values, strict=True)
            and p.contribution / single.contribution >= specificity
            for p in pairs
        )

    return [f for f in findings if len(f.features) != 1 or not explained(f)]


def _with_scores(slices: pd.DataFrame, scores: ArrayLike, which: str) -> pd.DataFrame:
    values = as_1d(scores, f"{which}_scores").astype(np.float64)
    require_rows(values.size, 1, f"{which} window")
    if values.size != len(slices):
        raise InvalidInputError(f"{which}: {len(slices)} slice rows but {values.size} scores")
    if not np.isfinite(values).all():
        raise InvalidInputError(f"{which}_scores must be finite")
    frame = slices.astype(str).reset_index(drop=True)
    frame.columns = [str(c) for c in frame.columns]
    frame[_SCORE] = values
    return frame


def _partition(
    features: Sequence[str],
    ref: pd.DataFrame,
    cur: pd.DataFrame,
    m_ref_overall: float,
    min_slice_size: int,
    min_concentration: float,
) -> tuple[PartitionSummary, list[SliceFinding]]:
    keys = list(features)
    r = ref.groupby(keys, dropna=False)[_SCORE].agg(["size", "mean"])
    c = cur.groupby(keys, dropna=False)[_SCORE].agg(["size", "mean"])
    r.columns, c.columns = ["size_ref", "mean_ref"], ["size_cur", "mean_cur"]
    table = r.join(c, how="outer")

    n_r = table["size_ref"].fillna(0).to_numpy(dtype=np.float64)
    n_c = table["size_cur"].fillna(0).to_numpy(dtype=np.float64)
    m_r = table["mean_ref"].fillna(m_ref_overall).to_numpy(dtype=np.float64)
    m_c = table["mean_cur"].to_numpy(dtype=np.float64)
    w_r, w_c = n_r / n_r.sum(), n_c / n_c.sum()

    perf = np.where(n_c > 0, w_c * (np.nan_to_num(m_c) - m_r), 0.0)
    mix = (w_c - w_r) * m_r
    perf_total, mix_total = float(perf.sum()), float(mix.sum())
    summary = PartitionSummary(
        features=tuple(keys), performance_effect=perf_total, mix_effect=mix_total
    )

    # perf_total is the row-weighted average within-slice change; a cause must be worse than that.
    change = np.where(n_c > 0, np.nan_to_num(m_c) - m_r, 0.0)
    concentrated = change <= min_concentration * perf_total if perf_total < 0 else change < 0
    eligible = (n_r >= min_slice_size) & (n_c >= min_slice_size) & (perf < 0) & concentrated
    findings = []
    for i in np.flatnonzero(eligible):
        key = table.index[int(i)]
        values = tuple(str(v) for v in (key if isinstance(key, tuple) else (key,)))
        findings.append(
            SliceFinding(
                features=tuple(keys),
                values=values,
                n_reference=int(n_r[i]),
                n_current=int(n_c[i]),
                share_reference=float(w_r[i]),
                share_current=float(w_c[i]),
                metric_reference=float(m_r[i]),
                metric_current=float(m_c[i]),
                contribution=float(perf[i]),
                share_of_drop=float(perf[i] / perf_total) if perf_total < 0 else float("nan"),
            )
        )
    return summary, findings
