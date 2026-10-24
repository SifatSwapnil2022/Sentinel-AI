"""Parity with the libraries Sentinel's methods come from.

These tests run our implementation and the reference library on identical data and require
the numbers to agree. They need extra packages that pin older pandas, so they run in their own
environment: ``make parity`` locally, the ``parity`` job in CI. Without those packages they are
skipped, never silently passed.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pytest

from sentinel_core.drift import (
    chi_square_p_value,
    jensen_shannon,
    ks_p_value,
    wasserstein_normed,
    z_test_p_value,
)
from sentinel_core.performance import CBPE, Metric, needs_calibration

pytestmark = [
    pytest.mark.parity,
    pytest.mark.filterwarnings("ignore"),  # the reference libraries warn noisily on new pandas
]

os.environ.setdefault("NML_DISABLE_USAGE_LOGGING", "1")  # NannyML phones home by default

evidently_tests = pytest.importorskip("evidently.legacy.calculations.stattests")
nannyml = pytest.importorskip("nannyml")

from evidently.legacy.calculations.stattests import (  # noqa: E402
    chisquare_stattest,
    jensenshannon,
    ks_stattest,
    wasserstein_distance_norm,
    z_stattest,
)
from evidently.legacy.core import ColumnType  # noqa: E402

# ---------------------------------------------------------------------------- Evidently


def _evidently(
    func: Callable[..., tuple[float, bool]], ref: np.ndarray, cur: np.ndarray, kind: Any
) -> float:
    value, _ = func(pd.Series(ref), pd.Series(cur), kind, 0.05)
    return float(value)


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("shift", [0.0, 0.2, 1.0])
def test_ks_and_wasserstein_match(seed: int, shift: float) -> None:
    rng = np.random.default_rng(seed)
    ref, cur = rng.normal(size=800), rng.normal(shift, 1.3, size=600)
    num = ColumnType.Numerical
    assert ks_p_value(ref, cur) == pytest.approx(
        _evidently(ks_stattest._ks_stat_test, ref, cur, num), rel=1e-12
    )
    assert wasserstein_normed(ref, cur) == pytest.approx(
        _evidently(wasserstein_distance_norm._wasserstein_distance_norm, ref, cur, num), rel=1e-12
    )


@pytest.mark.parametrize("seed", range(5))
def test_chi_square_and_jensen_shannon_match(seed: int) -> None:
    rng = np.random.default_rng(seed)
    ref = rng.choice(list("abcde"), 900, p=[0.4, 0.3, 0.15, 0.1, 0.05]).astype(object)
    cur = rng.choice(list("abcde"), 700, p=[0.2, 0.3, 0.25, 0.15, 0.1]).astype(object)
    cat = ColumnType.Categorical
    assert chi_square_p_value(ref, cur) == pytest.approx(
        _evidently(chisquare_stattest._chi_stat_test, ref, cur, cat), rel=1e-9, abs=1e-300
    )
    assert jensen_shannon(ref, cur) == pytest.approx(
        _evidently(jensenshannon._jensenshannon, ref, cur, cat), rel=1e-12
    )


@pytest.mark.parametrize("seed", range(5))
def test_z_test_matches(seed: int) -> None:
    rng = np.random.default_rng(seed)
    ref, cur = rng.binomial(1, 0.3, 700), rng.binomial(1, 0.36, 500)
    assert z_test_p_value(ref, cur) == pytest.approx(
        _evidently(z_stattest._z_stat_test, ref, cur, ColumnType.Categorical), rel=1e-9
    )


# ---------------------------------------------------------------------------- NannyML

_NANNY_METRICS = {
    Metric.ACCURACY: "accuracy",
    Metric.PRECISION: "precision",
    Metric.RECALL: "recall",
    Metric.F1: "f1",
}


def _frame(rng: np.random.Generator, n: int, shift: float, power: float) -> pd.DataFrame:
    x = rng.normal(shift, 1.0, n)
    p_true = 1 / (1 + np.exp(-2 * x))
    y = rng.binomial(1, p_true)
    score = p_true**power  # power != 1 makes the scores miscalibrated
    return pd.DataFrame({"score": score, "pred": (score >= 0.5).astype(int), "y": y})


@pytest.mark.parametrize("power", [1.0, 2.5])
def test_cbpe_matches_nannyml(power: float) -> None:
    rng = np.random.default_rng(7)
    reference = _frame(rng, 6000, 0.0, power)
    analysis = _frame(rng, 6000, 0.8, power)
    chunk = 1000

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nanny = nannyml.CBPE(
            metrics=list(_NANNY_METRICS.values()),
            y_pred_proba="score",
            y_pred="pred",
            y_true="y",
            problem_type="classification_binary",
            chunk_size=chunk,
        ).fit(reference)
        theirs = nanny.estimate(analysis).filter(period="analysis").to_df()

    calibrate = needs_calibration(reference["y"], reference["score"], rule="every_fold")
    ours = CBPE(calibrate=calibrate).fit(reference["y"], reference["score"], reference["pred"])

    for i in range(len(analysis) // chunk):
        window = analysis.iloc[i * chunk : (i + 1) * chunk]
        estimate = ours.estimate(window["score"], window["pred"])
        for metric, name in _NANNY_METRICS.items():
            expected_value = theirs[(name, "value")].iloc[i]
            expected_error = theirs[(name, "sampling_error")].iloc[i]
            assert estimate[metric].value == pytest.approx(expected_value, abs=1e-9), (metric, i)
            assert estimate[metric].sampling_error == pytest.approx(expected_error, rel=1e-9), (
                metric,
                i,
            )
