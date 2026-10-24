"""Turn feature values into human-readable slice labels, with bins fixed from reference data.

Fixing bins on the reference means "income < 20k" means the same thing in every window, so a
slice can be tracked over time and compared with its reference behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Self

import numpy as np
import numpy.typing as npt
import pandas as pd

from sentinel_core.errors import InvalidInputError, NotFittedError

MISSING_LABEL = "missing"
OTHER_LABEL = "other"


@dataclass(frozen=True, slots=True)
class FeatureBins:
    """How one feature is cut into slices."""

    name: str
    edges: npt.NDArray[np.float64] | None
    """Inner bin edges for a numeric feature; ``None`` for a categorical one."""
    categories: tuple[Any, ...] | None
    """Categories kept as their own slice; the rest fall into ``"other"``."""
    labels: tuple[str, ...]

    @property
    def is_numeric(self) -> bool:
        """True when the feature is binned by value ranges."""
        return self.edges is not None


class SliceBinner:
    """Fit slice definitions on reference data and label any later window with them.

    Args:
        n_bins: Quantile bins per continuous numeric feature.
        max_categories: Most frequent categories kept as their own slice. Numeric features
            with at most this many distinct values (codes, counts) are treated as categories.
    """

    def __init__(self, *, n_bins: int = 4, max_categories: int = 10) -> None:
        if n_bins < 2:
            raise InvalidInputError("n_bins must be at least 2")
        if max_categories < 1:
            raise InvalidInputError("max_categories must be at least 1")
        self.n_bins = n_bins
        self.max_categories = max_categories
        self._bins: dict[str, FeatureBins] = {}

    @property
    def features(self) -> list[str]:
        """Features with fitted bins, in fit order."""
        return list(self._bins)

    def bins(self, feature: str) -> FeatureBins:
        """Fitted bins for one feature."""
        try:
            return self._bins[feature]
        except KeyError:
            raise NotFittedError(f"no bins fitted for feature {feature!r}") from None

    def fit(self, reference: pd.DataFrame, features: list[str] | None = None) -> Self:
        """Derive bins for each feature from the reference data."""
        features = features if features is not None else [str(c) for c in reference.columns]
        missing = [f for f in features if f not in reference.columns]
        if missing:
            raise InvalidInputError(f"reference is missing features: {missing}")
        self._bins = {f: self._fit_one(f, reference[f]) for f in features}
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Replace each feature's values with its slice label (string)."""
        if not self._bins:
            raise NotFittedError("SliceBinner is not fitted; call fit() first")
        missing = [f for f in self._bins if f not in frame.columns]
        if missing:
            raise InvalidInputError(f"frame is missing features: {missing}")
        return pd.DataFrame(
            {f: self._label(b, frame[f]) for f, b in self._bins.items()}, index=frame.index
        )

    # ------------------------------------------------------------------ internals

    def _fit_one(self, name: str, values: pd.Series) -> FeatureBins:
        clean = values.dropna()
        is_numeric = pd.api.types.is_numeric_dtype(clean) and not pd.api.types.is_bool_dtype(clean)
        if is_numeric and clean.nunique() > self.max_categories:
            quantiles = np.linspace(0, 1, self.n_bins + 1)[1:-1]
            edges = np.unique(np.quantile(clean.to_numpy(dtype=np.float64), quantiles))
            return FeatureBins(name=name, edges=edges, categories=None, labels=_range_labels(edges))
        top = tuple(clean.value_counts().index[: self.max_categories])
        labels = tuple(_category_label(c) for c in top)
        if clean.nunique() > len(top):
            labels = (*labels, OTHER_LABEL)
        return FeatureBins(name=name, edges=None, categories=top, labels=labels)

    @staticmethod
    def _label(bins: FeatureBins, values: pd.Series) -> pd.Series:
        missing = values.isna().to_numpy()
        if bins.edges is not None:
            numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=np.float64)
            idx = np.searchsorted(bins.edges, numeric, side="right")
            labels = np.asarray(bins.labels, dtype=object)[np.clip(idx, 0, len(bins.labels) - 1)]
        else:
            assert bins.categories is not None
            known = {c: _category_label(c) for c in bins.categories}
            labels = np.array([known.get(v, OTHER_LABEL) for v in values], dtype=object)
        labels[missing] = MISSING_LABEL
        return pd.Series(labels, index=values.index, dtype=object)


def _range_labels(edges: npt.NDArray[np.float64]) -> tuple[str, ...]:
    if edges.size == 0:
        return ("all",)
    # Add significant figures until neighbouring edges stay distinct (e.g. 1.001 vs 1.002).
    for digits in range(3, 16):
        fmt = [format_number(e, digits=digits) for e in edges]
        if len(set(fmt)) == len(fmt):
            break
    labels = [f"< {fmt[0]}"]
    labels += [f"{lo} – {hi}" for lo, hi in pairwise(fmt)]
    labels.append(f"≥ {fmt[-1]}")
    return tuple(labels)


def format_number(value: float, *, digits: int = 3) -> str:
    """Compact, readable number: ``digits`` significant figures with k / M / B suffixes."""
    if not np.isfinite(value):
        return str(value)
    magnitude = abs(value)
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if magnitude >= threshold:
            return f"{value / threshold:.{digits}g}{suffix}"
    return f"{value:.{digits}g}"


def _category_label(value: Any) -> str:
    """How a category reads in a finding: whole floats (a count stored as 3.0) print as 3."""
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer():
        return str(int(value))
    return str(value)
