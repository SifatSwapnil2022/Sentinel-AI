from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sentinel_core.drift import (
    DEFAULT_THRESHOLDS,
    ColumnKind,
    ColumnReference,
    DriftMethod,
    chi_square_p_value,
    detect_drift,
    infer_kind,
    jensen_shannon,
    psi,
    select_method,
    wasserstein_normed,
    z_test_p_value,
)
from sentinel_core.errors import InsufficientDataError, InvalidInputError

# ---------------------------------------------------------------------------- kinds & methods


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (np.arange(100, dtype=float), ColumnKind.NUMERIC),
        (np.arange(6), ColumnKind.NUMERIC),
        (np.arange(5), ColumnKind.CATEGORICAL),  # 5 distinct is not enough to be continuous
        ([0, 1, 1, 0], ColumnKind.BINARY),
        ([True, False, True], ColumnKind.BINARY),
        (["a", "b", "c"], ColumnKind.CATEGORICAL),
        (["a", "b", None, "a"], ColumnKind.BINARY),  # missing values are not a category
        ([7.0, 7.0, np.nan], ColumnKind.BINARY),
    ],
)
def test_infer_kind(values: object, expected: ColumnKind) -> None:
    assert infer_kind(values) is expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "n", "expected"),
    [
        (ColumnKind.NUMERIC, 1000, DriftMethod.KS),
        (ColumnKind.NUMERIC, 1001, DriftMethod.WASSERSTEIN),
        (ColumnKind.CATEGORICAL, 1000, DriftMethod.CHI_SQUARE),
        (ColumnKind.CATEGORICAL, 1001, DriftMethod.JENSEN_SHANNON),
        (ColumnKind.BINARY, 1000, DriftMethod.Z_TEST),
        (ColumnKind.BINARY, 1001, DriftMethod.JENSEN_SHANNON),
    ],
)
def test_select_method_follows_evidently_defaults(
    kind: ColumnKind, n: int, expected: DriftMethod
) -> None:
    assert select_method(kind, n) is expected


def test_fit_picks_method_from_full_size_not_sample(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=5000), "x", max_sample=500)
    assert ref.method is DriftMethod.WASSERSTEIN
    assert ref.n_rows == 5000
    assert ref.sample.size == 500


def test_subsample_is_deterministic(rng: np.random.Generator) -> None:
    values = rng.normal(size=3000)
    a = ColumnReference.fit(values, max_sample=100, random_state=7)
    b = ColumnReference.fit(values, max_sample=100, random_state=7)
    np.testing.assert_array_equal(a.sample, b.sample)


def test_fit_records_null_rate() -> None:
    ref = ColumnReference.fit([1.0, np.nan, 3.0, np.nan], "x")
    assert ref.null_rate == 0.5
    assert ref.n_rows == 2


@pytest.mark.parametrize("values", [[], [np.nan, np.nan], [None]])
def test_fit_rejects_empty_columns(values: list[object]) -> None:
    with pytest.raises(InsufficientDataError):
        ColumnReference.fit(values, "empty")


def test_fit_rejects_method_invalid_for_kind() -> None:
    with pytest.raises(InvalidInputError, match="not valid for categorical"):
        ColumnReference.fit(["a", "b", "c"], "c", method=DriftMethod.KS)


def test_fit_rejects_forced_numeric_on_text() -> None:
    with pytest.raises(InvalidInputError, match="not numeric"):
        ColumnReference.fit(["a", "b", "c"], "c", kind=ColumnKind.NUMERIC)


def test_fit_rejects_two_dimensional_input() -> None:
    with pytest.raises(InvalidInputError, match="one-dimensional"):
        ColumnReference.fit(np.zeros((3, 2)), "x")


# ---------------------------------------------------------------------------- detection


@pytest.mark.parametrize("n", [500, 5000])  # both the test regime and the distance regime
def test_numeric_no_drift_on_same_distribution(rng: np.random.Generator, n: int) -> None:
    ref = ColumnReference.fit(rng.normal(size=n), "x")
    result = detect_drift(ref, rng.normal(size=n))
    assert not result.drifted
    assert result.psi < 0.1


@pytest.mark.parametrize("n", [500, 5000])
def test_numeric_detects_mean_shift(rng: np.random.Generator, n: int) -> None:
    ref = ColumnReference.fit(rng.normal(size=n), "x")
    result = detect_drift(ref, rng.normal(0.5, 1.0, size=n))
    assert result.drifted
    assert result.psi > 0.1


@pytest.mark.parametrize("n", [500, 5000])
def test_categorical_detects_mix_change(rng: np.random.Generator, n: int) -> None:
    ref = ColumnReference.fit(rng.choice(list("abc"), n, p=[0.6, 0.3, 0.1]), "c")
    same = detect_drift(ref, rng.choice(list("abc"), n, p=[0.6, 0.3, 0.1]))
    moved = detect_drift(ref, rng.choice(list("abc"), n, p=[0.2, 0.3, 0.5]))
    assert not same.drifted
    assert moved.drifted


@pytest.mark.parametrize("n", [500, 5000])
def test_binary_detects_rate_change(rng: np.random.Generator, n: int) -> None:
    ref = ColumnReference.fit(rng.binomial(1, 0.3, n), "flag")
    assert ref.kind is ColumnKind.BINARY
    assert not detect_drift(ref, rng.binomial(1, 0.3, n)).drifted
    assert detect_drift(ref, rng.binomial(1, 0.6, n)).drifted


def test_result_reports_counts_and_null_rate(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=200), "x")
    current = np.concatenate([rng.normal(size=75), [np.nan] * 25])
    result = detect_drift(ref, current)
    assert (result.n_reference, result.n_current) == (200, 75)
    assert result.current_null_rate == 0.25
    assert result.column == "x"


def test_detect_rejects_all_missing_window(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=50), "x")
    with pytest.raises(InsufficientDataError):
        detect_drift(ref, [np.nan, np.nan])


def test_detect_rejects_text_for_numeric_reference(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=50), "x")
    with pytest.raises(InvalidInputError, match="not numeric"):
        detect_drift(ref, ["a", "b"])


def test_method_override_uses_that_methods_default_threshold(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=5000), "x", threshold=0.5)
    result = detect_drift(ref, rng.normal(size=500), method=DriftMethod.KS)
    assert result.method is DriftMethod.KS
    assert result.threshold == DEFAULT_THRESHOLDS[DriftMethod.KS]


def test_psi_method_returns_psi_as_statistic(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=2000), "x", method=DriftMethod.PSI)
    result = detect_drift(ref, rng.normal(1.0, 1.0, size=2000))
    assert result.statistic == result.psi
    assert result.drifted


def test_explicit_threshold_wins(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(rng.normal(size=2000), "x")
    result = detect_drift(ref, rng.normal(0.3, 1.0, size=2000), threshold=10.0)
    assert not result.drifted
    assert result.threshold == 10.0


# ---------------------------------------------------------------------------- statistics


def test_wasserstein_is_normalised_by_reference_std() -> None:
    ref = np.array([0.0, 2.0, 4.0, 6.0])  # population std = sqrt(5)
    cur = ref + 1.0  # every point moves by exactly 1
    assert wasserstein_normed(ref, cur) == pytest.approx(1.0 / math.sqrt(5.0))


def test_wasserstein_constant_reference_does_not_divide_by_zero() -> None:
    value = wasserstein_normed(np.full(10, 3.0), np.full(10, 3.001))
    assert value == pytest.approx(1.0)  # 0.001 / floor of 0.001


def test_chi_square_new_category_is_definite_drift() -> None:
    assert chi_square_p_value(np.array(["a", "b"] * 50), np.array(["a", "b", "z"] * 20)) == 0.0


def test_chi_square_single_category_is_no_drift() -> None:
    assert chi_square_p_value(np.array(["a"] * 10), np.array(["a"] * 5)) == 1.0


def test_chi_square_category_missing_from_current_is_fine() -> None:
    p = chi_square_p_value(np.array(list("aabbc") * 40), np.array(list("aabb") * 40))
    assert 0.0 <= p < 0.05


def test_z_test_single_value_on_both_sides_is_no_drift() -> None:
    assert z_test_p_value(np.zeros(20), np.zeros(30)) == 1.0


def test_z_test_matches_hand_calculation() -> None:
    ref = np.array([1] * 30 + [0] * 70)
    cur = np.array([1] * 50 + [0] * 50)
    pooled = 0.4
    z = (0.3 - 0.5) / math.sqrt(pooled * (1 - pooled) * (2 / 100))
    expected = math.erfc(abs(z) / math.sqrt(2))
    assert z_test_p_value(ref, cur) == pytest.approx(expected)


def test_mixed_type_categories_are_supported() -> None:
    ref = ColumnReference.fit(np.array(["a", 1, "b", 2, "a"] * 20, dtype=object), "mixed")
    result = detect_drift(ref, np.array(["a", 1, "b", 2, 3] * 20, dtype=object))
    assert result.drifted  # category 3 is new


def test_psi_identical_is_zero() -> None:
    values = np.arange(1000, dtype=float)
    edges = np.concatenate(([-np.inf], np.quantile(values, np.linspace(0.1, 0.9, 9)), [np.inf]))
    assert psi(values, values, edges=edges) == pytest.approx(0.0, abs=1e-12)


def test_psi_handles_empty_bins_with_epsilon() -> None:
    value = psi(np.array(["a"] * 100), np.array(["b"] * 100))
    assert np.isfinite(value)
    assert value > 1.0


def test_detect_accepts_pandas_series(rng: np.random.Generator) -> None:
    ref = ColumnReference.fit(pd.Series(rng.normal(size=300)), "x")
    assert detect_drift(ref, pd.Series(rng.normal(size=300))).n_current == 300


# ---------------------------------------------------------------------------- properties

floats = st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False)
categories = st.sampled_from(["a", "b", "c", "d"])


@given(
    st.lists(categories, min_size=1, max_size=200), st.lists(categories, min_size=1, max_size=200)
)
def test_js_is_bounded_and_symmetric(ref: list[str], cur: list[str]) -> None:
    a, b = np.array(ref, dtype=object), np.array(cur, dtype=object)
    forward, backward = jensen_shannon(a, b), jensen_shannon(b, a)
    assert 0.0 <= forward <= math.sqrt(math.log(2)) + 1e-12
    assert forward == pytest.approx(backward)


@given(
    st.lists(categories, min_size=1, max_size=200), st.lists(categories, min_size=1, max_size=200)
)
def test_psi_is_never_negative(ref: list[str], cur: list[str]) -> None:
    assert psi(np.array(ref, dtype=object), np.array(cur, dtype=object)) >= -1e-12


@given(st.lists(floats, min_size=2, max_size=200), st.lists(floats, min_size=2, max_size=200))
def test_numeric_statistics_stay_in_range(ref: list[float], cur: list[float]) -> None:
    reference = ColumnReference.fit(np.array(ref), "x", kind=ColumnKind.NUMERIC)
    for method in (DriftMethod.KS, DriftMethod.WASSERSTEIN, DriftMethod.PSI):
        result = detect_drift(reference, np.array(cur), method=method)
        if method.is_p_value:
            assert 0.0 <= result.statistic <= 1.0
        else:
            assert result.statistic >= -1e-12


@given(st.lists(floats, min_size=2, max_size=200))
def test_identical_windows_never_drift(values: list[float]) -> None:
    arr = np.array(values)
    reference = ColumnReference.fit(arr, "x", kind=ColumnKind.NUMERIC)
    for method in (DriftMethod.KS, DriftMethod.WASSERSTEIN, DriftMethod.PSI):
        assert not detect_drift(reference, arr, method=method).drifted


def test_ks_degenerate_samples_fall_back_quietly() -> None:
    # SciPy's exact KS fails here and switches method; the result must still be a p-value.
    p = detect_drift(
        ColumnReference.fit(np.zeros(5), "x", kind=ColumnKind.NUMERIC),
        [0.0, 0.0, 0.0, 0.0, 1.0],
        method=DriftMethod.KS,
    ).statistic
    assert 0.0 <= p <= 1.0
