from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sentinel_core.drift import PCAReconstructionDrift
from sentinel_core.errors import InsufficientDataError, InvalidInputError, NotFittedError


def correlated_frame(rng: np.random.Generator, n: int, *, rho: float = 0.9) -> pd.DataFrame:
    a = rng.normal(size=n)
    b = rho * a + np.sqrt(1 - rho**2) * rng.normal(size=n)
    c = 0.5 * a + rng.normal(scale=0.5, size=n)
    return pd.DataFrame({"a": a, "b": b, "c": c, "segment": rng.choice(["x", "y", "z"], n)})


@pytest.fixture
def detector(rng: np.random.Generator) -> PCAReconstructionDrift:
    return PCAReconstructionDrift().fit(correlated_frame(rng, 6000))


def test_same_distribution_rarely_alarms(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    alarms = sum(detector.score(correlated_frame(rng, 500)).drifted for _ in range(40))
    assert alarms <= 2  # 3-sigma band: expect ~0 false alarms out of 40


def test_detects_broken_correlation_with_unchanged_marginals(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    window = correlated_frame(rng, 1000)
    window["b"] = rng.permutation(window["b"].to_numpy())  # same distribution, link destroyed
    result = detector.score(window)
    assert result.drifted
    assert result.reconstruction_error > result.upper


def test_detects_reversed_correlation(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    assert detector.score(correlated_frame(rng, 1000, rho=-0.9)).drifted


def test_band_narrows_as_window_grows(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    small = detector.score(correlated_frame(rng, 100))
    large = detector.score(correlated_frame(rng, 5000))
    assert (large.upper - large.lower) < (small.upper - small.lower)
    ratio = (small.upper - small.lower) / (large.upper - large.lower)
    assert ratio == pytest.approx(np.sqrt(50), rel=1e-9)


def test_handles_missing_values_and_unseen_categories(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    window = correlated_frame(rng, 300)
    window.loc[window.index[:30], "a"] = np.nan
    window.loc[window.index[:10], "segment"] = "never-seen"
    result = detector.score(window)
    assert np.isfinite(result.reconstruction_error)


def test_extra_columns_in_window_are_ignored(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    window = correlated_frame(rng, 300).assign(extra=1.0)
    assert detector.score(window).n_rows == 300


def test_column_order_in_window_does_not_matter(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    window = correlated_frame(rng, 300)
    shuffled = window[list(reversed(window.columns))]
    assert detector.score(window) == detector.score(shuffled)


def test_reports_fitted_shape(detector: PCAReconstructionDrift) -> None:
    assert detector.feature_names == ["a", "b", "c", "segment"]
    assert 1 <= detector.n_components < 6


def test_numeric_only_and_boolean_columns(rng: np.random.Generator) -> None:
    frame = correlated_frame(rng, 1000).drop(columns="segment").assign(flag=rng.random(1000) > 0.5)
    result = PCAReconstructionDrift().fit(frame).score(frame.iloc[:200])
    assert np.isfinite(result.reconstruction_error)


def test_missing_column_in_window(
    rng: np.random.Generator, detector: PCAReconstructionDrift
) -> None:
    with pytest.raises(InvalidInputError, match="missing columns"):
        detector.score(correlated_frame(rng, 50).drop(columns="b"))


def test_empty_window(detector: PCAReconstructionDrift) -> None:
    with pytest.raises(InsufficientDataError):
        detector.score(pd.DataFrame(columns=["a", "b", "c", "segment"]))


def test_unfitted_detector() -> None:
    detector = PCAReconstructionDrift()
    with pytest.raises(NotFittedError):
        detector.score(pd.DataFrame({"a": [1.0]}))
    with pytest.raises(NotFittedError):
        _ = detector.n_components


def test_too_little_reference(rng: np.random.Generator) -> None:
    with pytest.raises(InsufficientDataError):
        PCAReconstructionDrift().fit(correlated_frame(rng, 99))
    with pytest.raises(InsufficientDataError):
        PCAReconstructionDrift(chunk_size=200).fit(correlated_frame(rng, 1000))


def test_reference_without_columns() -> None:
    with pytest.raises(InvalidInputError, match="no columns"):
        PCAReconstructionDrift().fit(pd.DataFrame(index=range(200)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"variance_to_keep": 0.0},
        {"variance_to_keep": 1.0},
        {"holdout_fraction": 1.0},
        {"n_sigma": 0.0},
        {"chunk_size": 1},
    ],
)
def test_rejects_invalid_parameters(kwargs: dict[str, float]) -> None:
    with pytest.raises(InvalidInputError):
        PCAReconstructionDrift(**kwargs)  # type: ignore[arg-type]
