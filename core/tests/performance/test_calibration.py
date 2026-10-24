from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from sentinel_core.errors import InvalidInputError
from sentinel_core.performance import (
    ece_noise_floor,
    expected_calibration_error,
    fit_calibrator,
    needs_calibration,
)


def test_ece_hand_example() -> None:
    # Bin [0.0, 0.1): p=0.05 twice, labels 0,0 -> gap 0.05 * 2 rows
    # Bin [0.9, 1.0]: p=0.95 twice, labels 1,0 -> |0.95 - 0.5| * 2 rows
    y = np.array([0, 0, 1, 0])
    p = np.array([0.05, 0.05, 0.95, 0.95])
    assert expected_calibration_error(y, p) == pytest.approx((0.05 * 2 + 0.45 * 2) / 4)


def test_ece_probability_one_lands_in_last_bin() -> None:
    assert expected_calibration_error([1], [1.0]) == 0.0


def test_ece_empty_is_zero() -> None:
    assert expected_calibration_error([], []) == 0.0


@pytest.mark.parametrize(
    ("y", "p", "message"),
    [
        ([0, 1], [0.2], "same length"),
        ([0, 2], [0.2, 0.3], "only 0 and 1"),
        ([0, 1], [0.2, 1.3], r"\[0, 1\]"),
        ([0, 1], [0.2, np.nan], "NaN"),
        ([0, None], [0.2, 0.3], "missing"),
    ],
)
def test_ece_rejects_bad_input(y: list[object], p: list[float], message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        expected_calibration_error(y, p)


def test_ece_rejects_zero_bins() -> None:
    with pytest.raises(InvalidInputError):
        expected_calibration_error([0], [0.1], n_bins=0)


def test_well_calibrated_scores_are_left_alone(
    calibrated_scores: Callable[..., tuple[np.ndarray, np.ndarray]],
) -> None:
    p, y = calibrated_scores(20_000)
    assert expected_calibration_error(y, p) < 0.02
    calibrator = fit_calibrator(y, p)
    assert not calibrator.applied
    np.testing.assert_array_equal(calibrator.transform(p), p)


def test_overconfident_scores_get_calibrated(
    calibrated_scores: Callable[..., tuple[np.ndarray, np.ndarray]],
) -> None:
    p, y = calibrated_scores(20_000)
    distorted = np.where(p > 0.5, 1 - (1 - p) ** 3, p**3)  # pushed towards 0 and 1
    assert needs_calibration(y, distorted)
    calibrator = fit_calibrator(y, distorted)
    assert calibrator.applied
    assert calibrator.ece_after < calibrator.ece_before
    calibrated = calibrator.transform(distorted)
    assert calibrated.min() >= 0.0
    assert calibrated.max() <= 1.0


def test_forced_choices_are_respected(
    calibrated_scores: Callable[..., tuple[np.ndarray, np.ndarray]],
) -> None:
    p, y = calibrated_scores(2000)
    assert fit_calibrator(y, p, calibrate=True).applied
    distorted = p**3
    assert not fit_calibrator(y, distorted, calibrate=False).applied


def test_tiny_minority_class_skips_calibration() -> None:
    y = np.array([0] * 99 + [1])
    p = np.linspace(0.01, 0.99, 100)
    assert not needs_calibration(y, p)


def test_pooled_rule_calibrates_mild_overconfidence_every_fold_misses() -> None:
    # Mild overconfidence on a 6,000-row reference: real, but small enough that one of ten
    # 600-row folds can get noisier after isotonic calibration.
    rng = np.random.default_rng(3)
    true_p = rng.beta(2, 2, 6000)
    y = rng.binomial(1, true_p)
    scores = np.clip(0.5 + 1.25 * (true_p - 0.5), 0, 1)
    assert needs_calibration(y, scores, rule="pooled")
    oof_says = [needs_calibration(y, scores, rule="every_fold", random_state=s) for s in range(10)]
    assert not all(oof_says)  # the stricter rule vetoes on at least some splits


def test_unknown_rule_is_rejected() -> None:
    with pytest.raises(InvalidInputError, match="unknown calibration rule"):
        needs_calibration([0, 1] * 10, [0.2, 0.8] * 10, rule="sometimes")  # type: ignore[arg-type]


def test_noise_floor_matches_simulation() -> None:
    # Average ECE of genuinely calibrated scores should sit close to the analytic floor.
    rng = np.random.default_rng(11)
    p = rng.uniform(0, 1, 2000)
    simulated = np.mean([expected_calibration_error(rng.binomial(1, p), p) for _ in range(300)])
    assert ece_noise_floor(p) == pytest.approx(simulated, rel=0.15)


def test_noise_floor_shrinks_with_more_rows() -> None:
    rng = np.random.default_rng(0)
    small, large = rng.uniform(0, 1, 500), rng.uniform(0, 1, 50_000)
    assert ece_noise_floor(large) < ece_noise_floor(small) / 5
    assert ece_noise_floor([]) == 0.0
