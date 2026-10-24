"""Probability calibration for performance estimation.

CBPE is only as good as the model's probabilities. Calibration is measured with Expected
Calibration Error (ECE) and isotonic regression is applied when cross-validation shows it helps.

Two decision rules are available (``docs/adr/0005-calibration-rule.md``):

* ``"pooled"`` (default): calibrate when the raw ECE is clearly above the level sampling noise
  alone produces for perfectly calibrated scores (1.5x the noise floor), *and* pooled
  out-of-fold isotonic predictions have lower ECE than the raw scores.
* ``"every_fold"``: NannyML's rule; calibrate only if no single fold gets worse. With small
  folds one noisy fold can veto a clearly needed correction, so this is kept for parity tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import StratifiedKFold

from sentinel_core._validation import ArrayLike, as_binary, as_probabilities
from sentinel_core.errors import InvalidInputError


def expected_calibration_error(y_true: ArrayLike, y_proba: ArrayLike, *, n_bins: int = 10) -> float:
    """Expected Calibration Error with equal-width probability bins.

    ECE is the row-weighted mean, over bins, of |mean predicted probability - observed rate|.
    """
    if n_bins < 1:
        raise InvalidInputError("n_bins must be at least 1")
    y = as_binary(y_true, "y_true").astype(np.float64)
    p = as_probabilities(y_proba, "y_proba")
    if y.size != p.size:
        raise InvalidInputError("y_true and y_proba must have the same length")
    if y.size == 0:
        return 0.0
    bin_ids = np.minimum((p * n_bins).astype(np.int64), n_bins - 1)
    counts = np.bincount(bin_ids, minlength=n_bins)
    sum_p = np.bincount(bin_ids, weights=p, minlength=n_bins)
    sum_y = np.bincount(bin_ids, weights=y, minlength=n_bins)
    occupied = counts > 0
    gaps = np.abs(sum_p[occupied] - sum_y[occupied])  # = count * |mean_p - mean_y|
    return float(gaps.sum() / y.size)


CalibrationRule = Literal["pooled", "every_fold"]

NOISE_MARGIN = 1.5
"""Raw ECE must exceed this multiple of the noise floor before calibration is considered."""


def ece_noise_floor(y_proba: ArrayLike, *, n_bins: int = 10) -> float:
    """ECE expected from sampling noise alone if ``y_proba`` were perfectly calibrated.

    In a bin with ``n`` rows and mean probability ``p``, the observed rate of perfectly
    calibrated scores has standard deviation ``sqrt(p(1-p)/n)``, so its expected absolute gap is
    ``sqrt(2/pi) * sqrt(p(1-p)/n)`` (normal approximation). The floor is the row-weighted mean.
    """
    p = as_probabilities(y_proba, "y_proba")
    if p.size == 0:
        return 0.0
    bin_ids = np.minimum((p * n_bins).astype(np.int64), n_bins - 1)
    counts = np.bincount(bin_ids, minlength=n_bins).astype(np.float64)
    means = np.bincount(bin_ids, weights=p, minlength=n_bins) / np.maximum(counts, 1)
    occupied = counts > 0
    gap = np.sqrt(2 / np.pi) * np.sqrt(means[occupied] * (1 - means[occupied]) / counts[occupied])
    return float(np.sum(gap * counts[occupied]) / p.size)


@dataclass(frozen=True, slots=True, eq=False)
class Calibrator:
    """Maps raw model scores to calibrated probabilities (identity when not needed)."""

    applied: bool
    ece_before: float
    ece_after: float
    _isotonic: IsotonicRegression | None = field(default=None, repr=False)

    def transform(self, y_proba: ArrayLike) -> npt.NDArray[np.float64]:
        """Return calibrated probabilities for raw scores."""
        p = as_probabilities(y_proba, "y_proba")
        if self._isotonic is None:
            return p
        return np.asarray(self._isotonic.predict(p), dtype=np.float64)


def needs_calibration(
    y_true: ArrayLike,
    y_proba: ArrayLike,
    *,
    n_splits: int = 10,
    n_bins: int = 10,
    random_state: int = 0,
    rule: CalibrationRule = "pooled",
) -> bool:
    """Decide with cross-validation whether isotonic calibration improves the scores.

    The number of folds is reduced when the minority class is small; with fewer than two
    minority rows there is nothing to validate against, so the answer is False.
    """
    if rule not in ("pooled", "every_fold"):
        raise InvalidInputError(f"unknown calibration rule {rule!r}")
    y = as_binary(y_true, "y_true")
    p = as_probabilities(y_proba, "y_proba")
    minority = int(min(np.bincount(y, minlength=2)))
    splits = min(n_splits, minority)
    if splits < 2:
        return False

    folds = StratifiedKFold(n_splits=splits, shuffle=True, random_state=random_state)
    out_of_fold = np.empty_like(p)
    for train, test in folds.split(p, y):
        out_of_fold[test] = _isotonic().fit(p[train], y[train]).predict(p[test])
        if rule == "every_fold":
            before = expected_calibration_error(y[test], p[test], n_bins=n_bins)
            after = expected_calibration_error(y[test], out_of_fold[test], n_bins=n_bins)
            if after > before:
                return False
    if rule == "every_fold":
        return True
    raw = expected_calibration_error(y, p, n_bins=n_bins)
    if raw <= NOISE_MARGIN * ece_noise_floor(p, n_bins=n_bins):
        return False
    return expected_calibration_error(y, out_of_fold, n_bins=n_bins) < raw


def fit_calibrator(
    y_true: ArrayLike,
    y_proba: ArrayLike,
    *,
    calibrate: bool | None = None,
    rule: CalibrationRule = "pooled",
    n_bins: int = 10,
    random_state: int = 0,
) -> Calibrator:
    """Fit a :class:`Calibrator` on reference data.

    Args:
        y_true: Reference labels (0/1).
        y_proba: Reference positive-class scores.
        calibrate: Force calibration on (True) or off (False); ``None`` decides with
            :func:`needs_calibration`.
        rule: Decision rule used when ``calibrate`` is ``None``.
        n_bins: ECE bins.
        random_state: Seed for the cross-validation split.
    """
    y = as_binary(y_true, "y_true")
    p = as_probabilities(y_proba, "y_proba")
    ece_before = expected_calibration_error(y, p, n_bins=n_bins)
    if calibrate is None:
        calibrate = needs_calibration(y, p, n_bins=n_bins, random_state=random_state, rule=rule)
    if not calibrate:
        return Calibrator(applied=False, ece_before=ece_before, ece_after=ece_before)

    iso = _isotonic().fit(p, y)
    ece_after = expected_calibration_error(y, iso.predict(p), n_bins=n_bins)
    return Calibrator(applied=True, ece_before=ece_before, ece_after=ece_after, _isotonic=iso)


def _isotonic() -> IsotonicRegression:
    return IsotonicRegression(out_of_bounds="clip", increasing=True, y_min=0.0, y_max=1.0)
