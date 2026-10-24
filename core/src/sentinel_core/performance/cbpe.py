"""Confidence-based performance estimation (CBPE) for binary classifiers.

Given calibrated probabilities ``p`` and predicted labels ``ŷ``, each row's chance of being a
true positive is ``p`` when ``ŷ = 1``; its chance of being a false positive is ``1 - p``; and so
on. Summing those chances gives the *expected* confusion matrix of a window, from which any
metric can be estimated without a single label.

Sampling-error components follow NannyML so bands are directly comparable: for each metric, the
standard deviation of its row-level contributions on reference data, divided by
``sqrt(fraction * n)`` where ``fraction`` is the share of rows that contribute to it.

Two assumptions to keep in mind (``docs/adr/0004-performance-estimation.md``):

* Probabilities must be calibrated; :class:`CBPE` checks and calibrates when it helps.
* Only covariate shift is handled. If the relationship between inputs and outcome changes
  (concept drift), estimates are wrong. :func:`check_concept_drift` turns that limitation into a
  signal by comparing estimates with realized metrics once labels arrive.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

import numpy as np
import numpy.typing as npt

from sentinel_core._validation import ArrayLike, as_binary, as_probabilities, require_rows
from sentinel_core.errors import InsufficientDataError, InvalidInputError, NotFittedError
from sentinel_core.performance.calibration import CalibrationRule, Calibrator, fit_calibrator

MIN_REFERENCE_ROWS = 50


class Metric(StrEnum):
    """Binary classification metrics CBPE can estimate."""

    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"


ALL_METRICS: tuple[Metric, ...] = tuple(Metric)


@dataclass(frozen=True, slots=True)
class Confusion:
    """Confusion-matrix counts; expected (fractional) or realized (whole)."""

    tp: float
    fp: float
    fn: float
    tn: float

    @property
    def n(self) -> float:
        """Total rows."""
        return self.tp + self.fp + self.fn + self.tn

    def metric(self, metric: Metric) -> float:
        """Metric value from these counts; NaN when its denominator is zero."""
        if metric is Metric.ACCURACY:
            return _ratio(self.tp + self.tn, self.n)
        if metric is Metric.PRECISION:
            return _ratio(self.tp, self.tp + self.fp)
        if metric is Metric.RECALL:
            return _ratio(self.tp, self.tp + self.fn)
        return _ratio(2 * self.tp, 2 * self.tp + self.fp + self.fn)


def expected_confusion(y_proba: ArrayLike, y_pred: ArrayLike) -> Confusion:
    """Expected confusion matrix from calibrated probabilities and predicted labels."""
    p = as_probabilities(y_proba, "y_proba")
    pred = as_binary(y_pred, "y_pred")
    _same_length(p, pred)
    positive = pred == 1
    return Confusion(
        tp=float(p[positive].sum()),
        fp=float((1 - p[positive]).sum()),
        fn=float(p[~positive].sum()),
        tn=float((1 - p[~positive]).sum()),
    )


def realized_confusion(y_true: ArrayLike, y_pred: ArrayLike) -> Confusion:
    """Confusion matrix from true labels."""
    y = as_binary(y_true, "y_true")
    pred = as_binary(y_pred, "y_pred")
    _same_length(y, pred)
    return Confusion(
        tp=float(np.sum((y == 1) & (pred == 1))),
        fp=float(np.sum((y == 0) & (pred == 1))),
        fn=float(np.sum((y == 1) & (pred == 0))),
        tn=float(np.sum((y == 0) & (pred == 0))),
    )


@dataclass(frozen=True, slots=True)
class MetricEstimate:
    """One estimated metric with its sampling error and confidence band."""

    metric: Metric
    value: float
    sampling_error: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class Estimate:
    """Estimated metrics for one window."""

    n_rows: int
    confusion: Confusion
    metrics: dict[Metric, MetricEstimate]

    def __getitem__(self, metric: Metric) -> MetricEstimate:
        return self.metrics[metric]


@dataclass(frozen=True, slots=True)
class _ErrorComponent:
    std: float
    fraction: float

    def sampling_error(self, n: int) -> float:
        denom = self.fraction * n
        if denom <= 0 or np.isnan(self.std):
            return float("nan")
        return float(self.std / np.sqrt(denom))


class CBPE:
    """Estimate binary classification metrics from model scores alone.

    Args:
        metrics: Metrics to estimate.
        decision_threshold: Score at or above which a row is predicted positive, used when
            ``y_pred`` is not passed.
        n_sigma: Band half-width in sampling errors (NannyML uses 3).
        calibrate: Force calibration on/off; ``None`` lets cross-validation decide.
        calibration_rule: How cross-validation decides (see ``calibration.needs_calibration``).
        random_state: Seed for the calibration cross-validation.
    """

    def __init__(
        self,
        *,
        metrics: Iterable[Metric] = ALL_METRICS,
        decision_threshold: float = 0.5,
        n_sigma: float = 3.0,
        calibrate: bool | None = None,
        calibration_rule: CalibrationRule = "pooled",
        random_state: int = 0,
    ) -> None:
        self.metrics = tuple(dict.fromkeys(metrics))
        if not self.metrics:
            raise InvalidInputError("at least one metric is required")
        if not 0 < decision_threshold < 1:
            raise InvalidInputError("decision_threshold must be between 0 and 1 (exclusive)")
        if n_sigma <= 0:
            raise InvalidInputError("n_sigma must be positive")
        self.decision_threshold = decision_threshold
        self.n_sigma = n_sigma
        self.calibrate = calibrate
        self.calibration_rule: CalibrationRule = calibration_rule
        self.random_state = random_state
        self._calibrator: Calibrator | None = None
        self._components: dict[Metric, _ErrorComponent] = {}
        self._reference_metrics: dict[Metric, float] = {}
        self._n_reference = 0

    # ------------------------------------------------------------------ fitting

    def fit(self, y_true: ArrayLike, y_proba: ArrayLike, y_pred: ArrayLike | None = None) -> Self:
        """Fit calibration and sampling-error components on labelled reference data.

        Raises:
            InsufficientDataError: Fewer than 50 rows, or only one class present.
            InvalidInputError: Shapes or values are invalid.
        """
        y = as_binary(y_true, "y_true")
        p = as_probabilities(y_proba, "y_proba")
        pred = self._predictions(p, y_pred)
        _same_length(y, p)
        require_rows(y.size, MIN_REFERENCE_ROWS, "CBPE reference")
        if np.unique(y).size < 2:
            raise InsufficientDataError("CBPE reference labels contain only one class")

        self._calibrator = fit_calibrator(
            y,
            p,
            calibrate=self.calibrate,
            rule=self.calibration_rule,
            random_state=self.random_state,
        )
        self._components = {m: _component(m, y, pred) for m in self.metrics}
        realized = realized_confusion(y, pred)
        self._reference_metrics = {m: realized.metric(m) for m in self.metrics}
        self._n_reference = int(y.size)
        return self

    @property
    def calibrator(self) -> Calibrator:
        """The calibrator chosen during :meth:`fit`."""
        if self._calibrator is None:
            raise NotFittedError("CBPE is not fitted; call fit() first")
        return self._calibrator

    def sampling_error(self, metric: Metric, n_rows: int) -> float:
        """Sampling error of ``metric`` for a window of ``n_rows`` (NaN when undefined)."""
        self._require_fitted()
        if metric not in self._components:
            raise InvalidInputError(f"estimator was not configured for {metric.value}")
        return self._components[metric].sampling_error(n_rows)

    @property
    def n_reference(self) -> int:
        """Rows in the reference data the estimator was fitted on."""
        self._require_fitted()
        return self._n_reference

    @property
    def reference_metrics(self) -> dict[Metric, float]:
        """Realized metrics on the reference data."""
        self._require_fitted()
        return dict(self._reference_metrics)

    # ------------------------------------------------------------------ estimating

    def estimate(self, y_proba: ArrayLike, y_pred: ArrayLike | None = None) -> Estimate:
        """Estimate metrics for a window of raw model scores.

        Raises:
            InsufficientDataError: The window is empty.
            NotFittedError: :meth:`fit` has not been called.
        """
        calibrator = self.calibrator
        raw = as_probabilities(y_proba, "y_proba")
        require_rows(raw.size, 1, "CBPE window")
        pred = self._predictions(raw, y_pred)
        confusion = expected_confusion(calibrator.transform(raw), pred)

        estimates: dict[Metric, MetricEstimate] = {}
        for metric in self.metrics:
            value = confusion.metric(metric)
            error = self._components[metric].sampling_error(raw.size)
            half = self.n_sigma * error
            estimates[metric] = MetricEstimate(
                metric=metric,
                value=value,
                sampling_error=error,
                lower=max(value - half, 0.0),
                upper=min(value + half, 1.0),
            )
        return Estimate(n_rows=int(raw.size), confusion=confusion, metrics=estimates)

    # ------------------------------------------------------------------ helpers

    def _predictions(
        self, p: npt.NDArray[np.float64], y_pred: ArrayLike | None
    ) -> npt.NDArray[np.int64]:
        if y_pred is None:
            return (p >= self.decision_threshold).astype(np.int64)
        pred = as_binary(y_pred, "y_pred")
        _same_length(p, pred)
        return pred

    def _require_fitted(self) -> None:
        if self._calibrator is None:
            raise NotFittedError("CBPE is not fitted; call fit() first")


@dataclass(frozen=True, slots=True)
class ConceptDriftCheck:
    """Estimated vs realized metric on the labelled rows of one window."""

    metric: Metric
    estimated: float
    realized: float
    lower: float
    upper: float
    n_labeled: int
    flagged: bool
    """True when the realized value falls outside the estimate's band."""


def check_concept_drift(
    estimator: CBPE,
    y_true: ArrayLike,
    y_proba: ArrayLike,
    y_pred: ArrayLike | None = None,
    *,
    metric: Metric = Metric.ACCURACY,
    min_labeled: int = 100,
    include_reference_error: bool = True,
) -> ConceptDriftCheck:
    """Compare the estimate with the realized metric on the *same* labelled rows.

    Comparing against an estimate computed over all rows would mix in the effect of which rows
    happened to get labels first. Restricting both sides to labelled rows isolates the one thing
    CBPE cannot see: a change in how inputs relate to outcomes.

    The band combines two independent errors in quadrature: the window's sampling error, and the
    reference's, because calibration was learned from a finite reference sample. The second is
    negligible for a single small window but dominates once many labelled rows are pooled; leaving
    it out makes large pooled windows flag ordinary calibration noise as concept drift.

    Raises:
        InsufficientDataError: Fewer than ``min_labeled`` labelled rows.
        InvalidInputError: ``metric`` was not fitted on ``estimator``.
    """
    if metric not in estimator.metrics:
        raise InvalidInputError(f"estimator was not configured for {metric.value}")
    y = as_binary(y_true, "y_true")
    require_rows(y.size, min_labeled, "concept drift check")
    p = as_probabilities(y_proba, "y_proba")
    _same_length(y, p)
    pred = estimator._predictions(p, y_pred)

    estimate = estimator.estimate(p, pred)[metric]
    error = estimate.sampling_error
    if include_reference_error:
        reference_error = estimator.sampling_error(metric, estimator.n_reference)
        error = float(np.hypot(error, reference_error))
    half = estimator.n_sigma * error
    lower, upper = max(estimate.value - half, 0.0), min(estimate.value + half, 1.0)
    realized = realized_confusion(y, pred).metric(metric)
    outside = realized < lower or realized > upper
    return ConceptDriftCheck(
        metric=metric,
        estimated=estimate.value,
        realized=realized,
        lower=lower,
        upper=upper,
        n_labeled=int(y.size),
        flagged=bool(outside),
    )


# ---------------------------------------------------------------------------- internals


def _component(
    metric: Metric, y: npt.NDArray[np.int64], pred: npt.NDArray[np.int64]
) -> _ErrorComponent:
    """Row-level contributions to a metric on reference data (NannyML's formulation)."""
    n = y.size
    tp = (y == 1) & (pred == 1)
    fp = (y == 0) & (pred == 1)
    fn = (y == 1) & (pred == 0)
    if metric is Metric.ACCURACY:
        return _ErrorComponent(std=float(np.std(y == pred)), fraction=1.0)
    if metric is Metric.PRECISION:
        rows = np.concatenate([np.ones(tp.sum()), np.zeros(fp.sum())])
        return _ErrorComponent(std=_std(rows), fraction=float(pred.sum() / n))
    if metric is Metric.RECALL:
        rows = np.concatenate([np.ones(tp.sum()), np.zeros(fn.sum())])
        return _ErrorComponent(std=_std(rows), fraction=float(y.sum() / n))
    rows = np.concatenate([np.ones(tp.sum()), np.zeros(fn.sum() + fp.sum())])
    if rows.size == 0:
        return _ErrorComponent(std=float("nan"), fraction=0.0)
    correction = rows.size / (0.5 * (fn.sum() + fp.sum()) + tp.sum())
    return _ErrorComponent(std=_std(rows * correction), fraction=float(rows.size / n))


def _std(values: npt.NDArray[np.float64]) -> float:
    return float(np.std(values)) if values.size else float("nan")


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else float("nan")


def _same_length(a: npt.NDArray[np.generic], b: npt.NDArray[np.generic]) -> None:
    if a.size != b.size:
        raise InvalidInputError(f"length mismatch: {a.size} vs {b.size}")
