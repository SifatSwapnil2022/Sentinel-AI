"""Probability calibration for performance estimation.

CBPE is only as good as the model's probabilities. We measure calibration with Expected
Calibration Error (ECE) and, following NannyML, apply isotonic regression only when it lowers
ECE in *every* cross-validation fold; a calibrator that helps on average but hurts on some folds
is more likely fitting noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
) -> bool:
    """True unless isotonic calibration raises ECE on any held-out fold (NannyML's rule).

    The number of folds is reduced when the minority class is small; with fewer than two
    minority rows there is nothing to validate against, so the answer is False.
    """
    y = as_binary(y_true, "y_true")
    p = as_probabilities(y_proba, "y_proba")
    minority = int(min(np.bincount(y, minlength=2)))
    splits = min(n_splits, minority)
    if splits < 2:
        return False

    folds = StratifiedKFold(n_splits=splits, shuffle=True, random_state=random_state)
    for train, test in folds.split(p, y):
        iso = _isotonic().fit(p[train], y[train])
        before = expected_calibration_error(y[test], p[test], n_bins=n_bins)
        after = expected_calibration_error(y[test], iso.predict(p[test]), n_bins=n_bins)
        if after > before:
            return False
    return True


def fit_calibrator(
    y_true: ArrayLike,
    y_proba: ArrayLike,
    *,
    calibrate: bool | None = None,
    n_bins: int = 10,
    random_state: int = 0,
) -> Calibrator:
    """Fit a :class:`Calibrator` on reference data.

    Args:
        y_true: Reference labels (0/1).
        y_proba: Reference positive-class scores.
        calibrate: Force calibration on (True) or off (False); ``None`` decides with
            :func:`needs_calibration`.
        n_bins: ECE bins.
        random_state: Seed for the cross-validation split.
    """
    y = as_binary(y_true, "y_true")
    p = as_probabilities(y_proba, "y_proba")
    ece_before = expected_calibration_error(y, p, n_bins=n_bins)
    if calibrate is None:
        calibrate = needs_calibration(y, p, n_bins=n_bins, random_state=random_state)
    if not calibrate:
        return Calibrator(applied=False, ece_before=ece_before, ece_after=ece_before)

    iso = _isotonic().fit(p, y)
    ece_after = expected_calibration_error(y, iso.predict(p), n_bins=n_bins)
    return Calibrator(applied=True, ece_before=ece_before, ece_after=ece_after, _isotonic=iso)


def _isotonic() -> IsotonicRegression:
    return IsotonicRegression(out_of_bounds="clip", increasing=True, y_min=0.0, y_max=1.0)
