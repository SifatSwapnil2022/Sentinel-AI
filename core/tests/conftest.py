"""Shared fixtures and synthetic-data builders.

Every random draw goes through a seeded generator, so a failing test fails the same way on
every machine.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci", max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.register_profile("dev", max_examples=50, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def rng() -> np.random.Generator:
    """Fresh, seeded generator per test."""
    return np.random.default_rng(20261024)


Scores = tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]


@pytest.fixture
def calibrated_scores(rng: np.random.Generator) -> Callable[..., Scores]:
    """Build (probabilities, labels) where labels are drawn from the probabilities.

    ``shift`` moves the input distribution (covariate shift); the labels stay consistent with
    the probabilities, which is exactly the situation CBPE is designed for.
    """

    def make(n: int, *, shift: float = 0.0, slope: float = 2.0) -> Scores:
        x = rng.normal(shift, 1.0, n)
        p = 1.0 / (1.0 + np.exp(-slope * x))
        y = rng.binomial(1, p).astype(np.int64)
        return p, y

    return make
