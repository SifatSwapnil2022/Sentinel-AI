"""Per-feature drift detection with automatic method selection.

Method choice follows Evidently's documented defaults, so every decision has a public reference:

=================  =========================  ==============================
Column kind        Reference ≤ 1,000 rows      Reference > 1,000 rows
=================  =========================  ==============================
numeric            KS test (p < 0.05)          normed Wasserstein (≥ 0.1)
categorical        chi-square (p < 0.05)       Jensen–Shannon distance (≥ 0.1)
binary             two-proportion Z (p < 0.05) Jensen–Shannon distance (≥ 0.1)
=================  =========================  ==============================

With large samples, p-values flag tiny shifts that do not matter, so above 1,000 rows we switch
to distances that measure *how much* the distribution moved.

PSI is computed for every column as a familiar secondary number. It uses bins fixed from the
reference (deciles for numeric columns), so a column's histograms stay comparable across
windows. This differs from Evidently, which re-derives bins from reference + current each time;
see ``docs/adr/0002-drift-methods.md``.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats
from scipy.spatial import distance

from sentinel_core._validation import ArrayLike, as_1d, drop_missing, require_rows
from sentinel_core.errors import InvalidInputError

SMALL_SAMPLE_LIMIT: Final = 1_000
"""References with at most this many rows use hypothesis tests; larger ones use distances."""

NUMERIC_MIN_UNIQUE: Final = 5
"""A numeric column needs more than this many distinct values to be treated as continuous."""

PSI_BINS: Final = 10
_WASSERSTEIN_MIN_NORM: Final = 0.001


class ColumnKind(StrEnum):
    """How a column's values are compared."""

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    BINARY = "binary"


class DriftMethod(StrEnum):
    """Supported drift statistics."""

    KS = "ks"
    CHI_SQUARE = "chisquare"
    Z_TEST = "z"
    WASSERSTEIN = "wasserstein"
    JENSEN_SHANNON = "jensenshannon"
    PSI = "psi"

    @property
    def is_p_value(self) -> bool:
        """True when the statistic is a p-value (small means drift)."""
        return self in _P_VALUE_METHODS


_P_VALUE_METHODS: Final = frozenset({DriftMethod.KS, DriftMethod.CHI_SQUARE, DriftMethod.Z_TEST})

DEFAULT_THRESHOLDS: Final[dict[DriftMethod, float]] = {
    DriftMethod.KS: 0.05,
    DriftMethod.CHI_SQUARE: 0.05,
    DriftMethod.Z_TEST: 0.05,
    DriftMethod.WASSERSTEIN: 0.1,
    DriftMethod.JENSEN_SHANNON: 0.1,
    DriftMethod.PSI: 0.1,
}

_ALLOWED: Final[dict[ColumnKind, frozenset[DriftMethod]]] = {
    ColumnKind.NUMERIC: frozenset({DriftMethod.KS, DriftMethod.WASSERSTEIN, DriftMethod.PSI}),
    ColumnKind.CATEGORICAL: frozenset(
        {DriftMethod.CHI_SQUARE, DriftMethod.JENSEN_SHANNON, DriftMethod.PSI}
    ),
    ColumnKind.BINARY: frozenset(
        {DriftMethod.Z_TEST, DriftMethod.CHI_SQUARE, DriftMethod.JENSEN_SHANNON, DriftMethod.PSI}
    ),
}


# --------------------------------------------------------------------------- column kinds


def infer_kind(values: ArrayLike) -> ColumnKind:
    """Classify a column as numeric, categorical or binary from its non-missing values.

    Two or fewer distinct values is binary whatever the dtype; a numeric dtype with more than
    :data:`NUMERIC_MIN_UNIQUE` distinct values is numeric; everything else is categorical.
    """
    clean, _ = drop_missing(as_1d(values, "values"))
    n_unique = len(pd.unique(clean))
    if n_unique <= 2:
        return ColumnKind.BINARY
    is_numeric = clean.dtype.kind in "iuf"
    if is_numeric and n_unique > NUMERIC_MIN_UNIQUE:
        return ColumnKind.NUMERIC
    return ColumnKind.CATEGORICAL


def select_method(kind: ColumnKind, n_reference: int) -> DriftMethod:
    """Pick the default drift method for a column kind and reference size."""
    small = n_reference <= SMALL_SAMPLE_LIMIT
    if kind is ColumnKind.NUMERIC:
        return DriftMethod.KS if small else DriftMethod.WASSERSTEIN
    if kind is ColumnKind.BINARY:
        return DriftMethod.Z_TEST if small else DriftMethod.JENSEN_SHANNON
    return DriftMethod.CHI_SQUARE if small else DriftMethod.JENSEN_SHANNON


# --------------------------------------------------------------------------- reference profile


@dataclass(frozen=True, slots=True, eq=False)
class ColumnReference:
    """Everything needed to test one column for drift, fitted once from reference data.

    Build it with :meth:`fit`. The raw reference sample is capped at ``max_sample`` rows to
    bound memory; the method is still chosen from the full reference size.
    """

    name: str
    kind: ColumnKind
    method: DriftMethod
    threshold: float
    n_rows: int
    null_rate: float
    sample: npt.NDArray[Any] = field(repr=False)
    psi_edges: npt.NDArray[np.float64] | None = field(repr=False)

    @classmethod
    def fit(
        cls,
        values: ArrayLike,
        name: str = "",
        *,
        kind: ColumnKind | None = None,
        method: DriftMethod | None = None,
        threshold: float | None = None,
        max_sample: int = 10_000,
        random_state: int = 0,
    ) -> ColumnReference:
        """Profile a reference column.

        Args:
            values: Reference values; missing entries are excluded and counted.
            name: Column name, carried into results.
            kind: Override the inferred column kind.
            method: Override the default method for this kind and size.
            threshold: Override the method's default threshold.
            max_sample: Largest reference sample kept for tests that need raw values.
            random_state: Seed for the deterministic subsample.

        Raises:
            InsufficientDataError: The column has no non-missing values.
            InvalidInputError: ``method`` is not valid for the column kind.
        """
        raw = as_1d(values, f"reference[{name}]")
        clean, n_missing = drop_missing(raw)
        require_rows(clean.size, 1, f"reference column {name!r}")

        kind = kind or infer_kind(clean)
        if kind is ColumnKind.NUMERIC:
            try:
                clean = clean.astype(np.float64)
            except (TypeError, ValueError) as exc:
                raise InvalidInputError(f"column {name!r} is not numeric") from exc
        method = method or select_method(kind, clean.size)
        _check_allowed(kind, method, name)

        sample = clean
        if clean.size > max_sample:
            rng = np.random.default_rng(random_state)
            sample = rng.choice(clean, size=max_sample, replace=False)

        edges = _decile_edges(clean) if kind is ColumnKind.NUMERIC else None
        return cls(
            name=name,
            kind=kind,
            method=method,
            threshold=DEFAULT_THRESHOLDS[method] if threshold is None else threshold,
            n_rows=int(clean.size),
            null_rate=n_missing / raw.size,
            sample=sample,
            psi_edges=edges,
        )


@dataclass(frozen=True, slots=True)
class DriftResult:
    """Outcome of comparing one column's current window with its reference."""

    column: str
    method: DriftMethod
    statistic: float
    """p-value for KS / chi-square / Z, distance for Wasserstein / Jensen–Shannon / PSI."""
    threshold: float
    drifted: bool
    psi: float
    n_reference: int
    n_current: int
    current_null_rate: float


def detect_drift(
    reference: ColumnReference,
    current: ArrayLike,
    *,
    method: DriftMethod | None = None,
    threshold: float | None = None,
) -> DriftResult:
    """Test a window of current values against a fitted :class:`ColumnReference`.

    Raises:
        InsufficientDataError: The current window has no non-missing values.
        InvalidInputError: ``method`` is not valid for the reference column kind.
    """
    raw = as_1d(current, f"current[{reference.name}]")
    clean, n_missing = drop_missing(raw)
    require_rows(clean.size, 1, f"current column {reference.name!r}")
    if reference.kind is ColumnKind.NUMERIC:
        try:
            clean = clean.astype(np.float64)
        except (TypeError, ValueError) as exc:
            raise InvalidInputError(f"current column {reference.name!r} is not numeric") from exc

    method = method or reference.method
    _check_allowed(reference.kind, method, reference.name)
    if threshold is None:
        threshold = (
            reference.threshold if method is reference.method else DEFAULT_THRESHOLDS[method]
        )

    psi_value = psi(reference.sample, clean, edges=reference.psi_edges)
    statistic = psi_value if method is DriftMethod.PSI else _STAT_FUNCS[method](reference, clean)
    drifted = statistic < threshold if method.is_p_value else statistic >= threshold

    return DriftResult(
        column=reference.name,
        method=method,
        statistic=float(statistic),
        threshold=float(threshold),
        drifted=bool(drifted),
        psi=float(psi_value),
        n_reference=reference.n_rows,
        n_current=int(clean.size),
        current_null_rate=n_missing / raw.size,
    )


# --------------------------------------------------------------------------- statistics


def ks_p_value(reference: npt.NDArray[np.float64], current: npt.NDArray[np.float64]) -> float:
    """Two-sample Kolmogorov–Smirnov p-value.

    On degenerate inputs (e.g. near-constant samples) SciPy's exact method can fail and fall back
    to the asymptotic one with a RuntimeWarning. The fallback result is valid and callers cannot
    act on the warning, so only that warning is silenced.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"ks_2samp: Exact calculation unsuccessful", category=RuntimeWarning
        )
        return float(stats.ks_2samp(reference, current).pvalue)


def wasserstein_normed(
    reference: npt.NDArray[np.float64], current: npt.NDArray[np.float64]
) -> float:
    """First Wasserstein distance divided by the reference standard deviation.

    The divisor is floored at 0.001 so a constant reference column does not divide by zero.
    """
    norm = max(float(np.std(reference)), _WASSERSTEIN_MIN_NORM)
    return float(stats.wasserstein_distance(reference, current)) / norm


def jensen_shannon(reference: npt.NDArray[Any], current: npt.NDArray[Any]) -> float:
    """Jensen–Shannon distance (natural log) between category frequencies."""
    ref_p, cur_p = _category_proportions(reference, current)
    return float(distance.jensenshannon(ref_p, cur_p))


def chi_square_p_value(reference: npt.NDArray[Any], current: npt.NDArray[Any]) -> float:
    """Chi-square goodness-of-fit p-value of current counts against scaled reference counts.

    A category that appears in the current window but never in the reference makes the
    expected count zero; that is unambiguous drift, so the p-value is 0.
    """
    keys = _union_keys(reference, current)
    if len(keys) < 2:
        return 1.0
    ref_counts = _counts(reference, keys)
    cur_counts = _counts(current, keys)
    expected = ref_counts * (current.size / reference.size)
    if np.any((expected == 0) & (cur_counts > 0)):
        return 0.0
    keep = expected > 0
    return float(stats.chisquare(cur_counts[keep], expected[keep]).pvalue)


def z_test_p_value(reference: npt.NDArray[Any], current: npt.NDArray[Any]) -> float:
    """Two-sided, pooled two-proportion Z-test p-value for a binary column."""
    keys = _union_keys(reference, current)
    if len(keys) < 2:
        return 1.0
    first = keys[0]
    ref_hits = np.asarray(reference != first, dtype=np.float64)
    cur_hits = np.asarray(current != first, dtype=np.float64)
    n1, n2 = ref_hits.size, cur_hits.size
    p1, p2 = ref_hits.mean(), cur_hits.mean()
    pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
    denom = np.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if denom == 0:
        return 1.0
    z = (p1 - p2) / denom
    return float(2 * (1 - stats.norm.cdf(abs(z))))


def psi(
    reference: npt.NDArray[Any],
    current: npt.NDArray[Any],
    *,
    edges: npt.NDArray[np.float64] | None = None,
) -> float:
    """Population Stability Index.

    Numeric columns use the given bin ``edges`` (outer edges are ±inf so every value lands in
    a bin); without edges, values are treated as categories. Empty bins are filled with a small
    epsilon before taking logs.
    """
    if edges is not None:
        ref_p = np.histogram(reference, bins=edges)[0] / reference.size
        cur_p = np.histogram(current, bins=edges)[0] / current.size
    else:
        ref_p, cur_p = _category_proportions(reference, current)
    ref_p, cur_p = _fill_zeros(ref_p), _fill_zeros(cur_p)
    return float(np.sum((cur_p - ref_p) * np.log(cur_p / ref_p)))


# --------------------------------------------------------------------------- helpers


def _check_allowed(kind: ColumnKind, method: DriftMethod, name: str) -> None:
    if method not in _ALLOWED[kind]:
        allowed = ", ".join(sorted(m.value for m in _ALLOWED[kind]))
        raise InvalidInputError(
            f"method {method.value!r} is not valid for {kind.value} column {name!r}; "
            f"use one of: {allowed}"
        )


def _decile_edges(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    inner = np.unique(np.quantile(values, np.linspace(0, 1, PSI_BINS + 1)[1:-1]))
    return np.concatenate(([-np.inf], inner, [np.inf]))


def _union_keys(reference: npt.NDArray[Any], current: npt.NDArray[Any]) -> list[Any]:
    keys: list[Any] = list(pd.unique(np.concatenate([reference, current])))
    try:
        keys.sort()
    except TypeError:  # mixed types, e.g. str and int
        keys.sort(key=str)
    return keys


def _counts(values: npt.NDArray[Any], keys: list[Any]) -> npt.NDArray[np.float64]:
    counts = pd.Series(values).value_counts()
    return np.array([counts.get(k, 0) for k in keys], dtype=np.float64)


def _category_proportions(
    reference: npt.NDArray[Any], current: npt.NDArray[Any]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    keys = _union_keys(reference, current)
    return _counts(reference, keys) / reference.size, _counts(current, keys) / current.size


def _fill_zeros(p: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    nonzero = p[p > 0]
    if nonzero.size == 0:  # pragma: no cover - callers guarantee at least one row
        return p
    smallest = float(np.min(nonzero))
    eps = smallest / 1e6 if smallest <= 1e-4 else 1e-4
    return np.where(p == 0, eps, p)


_StatFunc = Callable[[ColumnReference, npt.NDArray[Any]], float]

_STAT_FUNCS: Final[dict[DriftMethod, _StatFunc]] = {
    DriftMethod.KS: lambda ref, cur: ks_p_value(ref.sample, cur),
    DriftMethod.WASSERSTEIN: lambda ref, cur: wasserstein_normed(ref.sample, cur),
    DriftMethod.JENSEN_SHANNON: lambda ref, cur: jensen_shannon(ref.sample, cur),
    DriftMethod.CHI_SQUARE: lambda ref, cur: chi_square_p_value(ref.sample, cur),
    DriftMethod.Z_TEST: lambda ref, cur: z_test_p_value(ref.sample, cur),
}
