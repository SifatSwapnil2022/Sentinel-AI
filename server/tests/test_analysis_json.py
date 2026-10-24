from __future__ import annotations

import math

import numpy as np
import pytest

from sentinel_server.analysis._json import jsonable, r


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (math.nan, None), (math.inf, None), (np.float32(0.123456), 0.1235), (2, 2.0)],
)
def test_r(value: float | None, expected: float | None) -> None:
    assert r(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (np.bool_(True), True),
        (np.int64(7), 7),
        (np.float64(1.23456), 1.235),
        (math.nan, None),
        ("Dhaka", "Dhaka"),
        (np.datetime64("2026-10-24"), "2026-10-24"),
    ],
)
def test_jsonable(value: object, expected: object) -> None:
    out = jsonable(value)
    assert out == expected
    assert type(out) is type(expected)
