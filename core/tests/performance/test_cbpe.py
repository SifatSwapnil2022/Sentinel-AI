from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from sentinel_core.errors import InsufficientDataError, InvalidInputError, NotFittedError
from sentinel_core.performance import (
    CBPE,
    Confusion,
    Metric,
    check_concept_drift,
    expected_confusion,
    realized_confusion,
)

MakeScores = Callable[..., tuple[np.ndarray, np.ndarray]]


@pytest.fixture
def fitted(calibrated_scores: MakeScores) -> CBPE:
    p, y = calibrated_scores(10_000)
    return CBPE().fit(y, p)


# ---------------------------------------------------------------------------- confusion maths


def test_expected_confusion_hand_example() -> None:
    p = np.array([0.9, 0.6, 0.2, 0.1])
    pred = np.array([1, 1, 0, 0])
    c = expected_confusion(p, pred)
    assert (c.tp, c.fp, c.fn, c.tn) == pytest.approx((1.5, 0.5, 0.3, 1.7))
    assert c.metric(Metric.ACCURACY) == pytest.approx(3.2 / 4)
    assert c.metric(Metric.PRECISION) == pytest.approx(1.5 / 2.0)
    assert c.metric(Metric.RECALL) == pytest.approx(1.5 / 1.8)
    assert c.metric(Metric.F1) == pytest.approx(3.0 / (3.0 + 0.5 + 0.3))


def test_realized_confusion_counts() -> None:
    c = realized_confusion([1, 0, 1, 0, 1], [1, 1, 0, 0, 1])
    assert (c.tp, c.fp, c.fn, c.tn) == (2, 1, 1, 1)


@pytest.mark.parametrize("metric", [Metric.PRECISION, Metric.RECALL, Metric.F1])
def test_undefined_metrics_are_nan(metric: Metric) -> None:
    assert np.isnan(Confusion(tp=0, fp=0, fn=0, tn=5).metric(metric))


def test_accuracy_of_empty_confusion_is_nan() -> None:
    assert np.isnan(Confusion(0, 0, 0, 0).metric(Metric.ACCURACY))


# ---------------------------------------------------------------------------- estimation quality


def test_estimate_tracks_realized_under_covariate_shift(
    fitted: CBPE, calibrated_scores: MakeScores
) -> None:
    for shift in (-1.0, 0.0, 1.0, 2.0):
        p, y = calibrated_scores(20_000, shift=shift)
        estimate = fitted.estimate(p)
        realized = realized_confusion(y, (p >= 0.5).astype(int))
        for metric in Metric:
            assert estimate[metric].value == pytest.approx(realized.metric(metric), abs=0.015)


@pytest.mark.slow
def test_band_covers_realized_accuracy_at_nominal_rate(
    fitted: CBPE, calibrated_scores: MakeScores
) -> None:
    covered = 0
    trials = 300
    for _ in range(trials):
        p, y = calibrated_scores(500)
        est = fitted.estimate(p)[Metric.ACCURACY]
        realized = realized_confusion(y, (p >= 0.5).astype(int)).metric(Metric.ACCURACY)
        covered += est.lower <= realized <= est.upper
    assert covered / trials >= 0.97  # 3-sigma band should cover ~99.7%


def test_band_shrinks_with_window_size(fitted: CBPE, calibrated_scores: MakeScores) -> None:
    small = fitted.estimate(calibrated_scores(100)[0])[Metric.ACCURACY]
    large = fitted.estimate(calibrated_scores(10_000)[0])[Metric.ACCURACY]
    assert small.sampling_error == pytest.approx(large.sampling_error * 10, rel=1e-9)


def test_band_is_clipped_to_unit_interval(fitted: CBPE) -> None:
    est = fitted.estimate(np.full(3, 0.999))[Metric.ACCURACY]
    assert 0.0 <= est.lower <= est.value <= est.upper <= 1.0


def test_uses_given_predictions_instead_of_threshold(fitted: CBPE) -> None:
    p = np.array([0.9, 0.9])
    flipped = fitted.estimate(p, y_pred=[0, 0])
    assert flipped[Metric.ACCURACY].value == pytest.approx(0.1)


def test_custom_threshold_changes_predictions(calibrated_scores: MakeScores) -> None:
    p, y = calibrated_scores(5000)
    loose = CBPE(decision_threshold=0.2).fit(y, p).estimate(p)
    strict = CBPE(decision_threshold=0.8).fit(y, p).estimate(p)
    assert loose[Metric.RECALL].value > strict[Metric.RECALL].value
    assert loose[Metric.PRECISION].value < strict[Metric.PRECISION].value


def test_metric_subset_and_reference_metrics(calibrated_scores: MakeScores) -> None:
    p, y = calibrated_scores(2000)
    estimator = CBPE(metrics=[Metric.F1, Metric.F1]).fit(y, p)
    assert estimator.metrics == (Metric.F1,)
    assert set(estimator.estimate(p).metrics) == {Metric.F1}
    assert set(estimator.reference_metrics) == {Metric.F1}


def test_calibration_is_applied_to_window(calibrated_scores: MakeScores) -> None:
    p, y = calibrated_scores(20_000)
    distorted = p**3
    estimator = CBPE().fit(y, distorted)
    assert estimator.calibrator.applied
    p2, y2 = calibrated_scores(20_000)
    realized = realized_confusion(y2, (p2**3 >= 0.5).astype(int)).metric(Metric.ACCURACY)
    assert estimator.estimate(p2**3)[Metric.ACCURACY].value == pytest.approx(realized, abs=0.02)


# ---------------------------------------------------------------------------- concept drift


def test_concept_drift_flagged_when_labels_flip(
    fitted: CBPE, calibrated_scores: MakeScores
) -> None:
    p, y = calibrated_scores(1000)
    check = check_concept_drift(fitted, 1 - y, p)
    assert check.flagged
    assert check.realized < check.lower


def test_no_concept_drift_under_pure_covariate_shift(
    fitted: CBPE, calibrated_scores: MakeScores
) -> None:
    flags = 0
    for _ in range(30):
        p, y = calibrated_scores(400, shift=1.0)
        flags += check_concept_drift(fitted, y, p).flagged
    assert flags <= 1


def test_concept_drift_needs_enough_labels(fitted: CBPE) -> None:
    with pytest.raises(InsufficientDataError):
        check_concept_drift(fitted, [0, 1], [0.2, 0.8])


def test_concept_drift_rejects_unconfigured_metric(calibrated_scores: MakeScores) -> None:
    p, y = calibrated_scores(500)
    estimator = CBPE(metrics=[Metric.ACCURACY]).fit(y, p)
    with pytest.raises(InvalidInputError, match="f1"):
        check_concept_drift(estimator, y, p, metric=Metric.F1)


# ---------------------------------------------------------------------------- errors


def test_unfitted_estimator() -> None:
    estimator = CBPE()
    with pytest.raises(NotFittedError):
        estimator.estimate([0.5])
    with pytest.raises(NotFittedError):
        _ = estimator.reference_metrics


def test_single_class_reference() -> None:
    with pytest.raises(InsufficientDataError, match="one class"):
        CBPE().fit(np.zeros(100), np.linspace(0, 1, 100))


def test_too_small_reference() -> None:
    with pytest.raises(InsufficientDataError):
        CBPE().fit([0, 1] * 10, [0.2, 0.8] * 10)


def test_empty_window(fitted: CBPE) -> None:
    with pytest.raises(InsufficientDataError):
        fitted.estimate([])


@pytest.mark.parametrize(
    "kwargs",
    [{"metrics": []}, {"decision_threshold": 1.0}, {"decision_threshold": 0.0}, {"n_sigma": -1}],
)
def test_invalid_parameters(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidInputError):
        CBPE(**kwargs)  # type: ignore[arg-type]


def test_length_mismatch(fitted: CBPE) -> None:
    with pytest.raises(InvalidInputError, match="length"):
        fitted.estimate([0.2, 0.8], y_pred=[1])
    with pytest.raises(InvalidInputError, match="length"):
        CBPE().fit([0, 1] * 50, [0.5] * 99)
