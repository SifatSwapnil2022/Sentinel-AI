"""Multivariate drift via PCA reconstruction error.

A PCA model fitted on reference data captures how features move together. If a later window
reconstructs worse than reference data does, the relationships between features have changed,
even when every feature still looks normal on its own.

Two deliberate differences from NannyML's version (see ``docs/adr/0003-multivariate-drift.md``):

1. **Held-out band.** The expected-error band comes from reference rows the PCA was *not*
   fitted on. Measuring on the training rows understates normal error and causes false alarms.
2. **Band scaled to window size, with the reference's own uncertainty.** The row-level spread
   is estimated from many small chunks of held-out rows. A window of ``n`` rows gets the band
   ``mean ± n_sigma · s · sqrt(1/n + 1/n_holdout)``: the first term is the window's sampling error,
   the second the error in the reference mean itself, which is comparable when the holdout is
   about the size of a day's traffic. Leaving the second term out gave a 6.5% daily false-alarm
   rate on realistic data instead of the nominal 0.3%.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from sentinel_core._validation import require_rows
from sentinel_core.errors import InvalidInputError, NotFittedError

MIN_CHUNKS = 5
MIN_REFERENCE_ROWS = 100
DEFAULT_CHUNKS = 50
"""Chunks the holdout is split into by default; more chunks give a steadier spread estimate."""


@dataclass(frozen=True, slots=True)
class MultivariateDriftResult:
    """Reconstruction error of one window and the band it is expected to fall in."""

    reconstruction_error: float
    lower: float
    upper: float
    drifted: bool
    n_rows: int


@dataclass(frozen=True, slots=True)
class _Band:
    mean: float
    row_std: float
    """Spread of single-row error, inferred from chunk means (chunk std * sqrt(chunk size))."""
    n_holdout: int


class PCAReconstructionDrift:
    """Detect changes in the joint distribution of features.

    Args:
        variance_to_keep: Fraction of variance the PCA keeps (0-1).
        chunk_size: Rows per reference chunk used to estimate the band's spread; defaults to a
            fiftieth of the held-out rows, at least 20.
        n_sigma: Band half-width in standard errors.
        holdout_fraction: Share of reference rows held out from PCA fitting to set the band.
        max_categories: Most frequent categories one-hot encoded per categorical column; the
            rest share one "infrequent" column.
        random_state: Seed for the reference shuffle.
    """

    def __init__(
        self,
        *,
        variance_to_keep: float = 0.65,
        chunk_size: int | None = None,
        n_sigma: float = 3.0,
        holdout_fraction: float = 0.5,
        max_categories: int = 20,
        random_state: int = 0,
    ) -> None:
        if not 0 < variance_to_keep < 1:
            raise InvalidInputError("variance_to_keep must be between 0 and 1 (exclusive)")
        if not 0 < holdout_fraction < 1:
            raise InvalidInputError("holdout_fraction must be between 0 and 1 (exclusive)")
        if n_sigma <= 0:
            raise InvalidInputError("n_sigma must be positive")
        if chunk_size is not None and chunk_size < 2:
            raise InvalidInputError("chunk_size must be at least 2")
        self.variance_to_keep = variance_to_keep
        self.chunk_size = chunk_size
        self.n_sigma = n_sigma
        self.holdout_fraction = holdout_fraction
        self.max_categories = max_categories
        self.random_state = random_state
        self._pipeline: Pipeline | None = None
        self._columns: list[str] = []
        self._band: _Band | None = None

    # ------------------------------------------------------------------ public API

    @property
    def feature_names(self) -> list[str]:
        """Columns the detector was fitted on, in order."""
        return list(self._columns)

    @property
    def n_components(self) -> int:
        """Number of principal components kept."""
        pca = self._fitted_pipeline().named_steps["pca"]
        return int(pca.n_components_)

    def fit(self, reference: pd.DataFrame) -> Self:
        """Fit the PCA on part of ``reference`` and derive the error band from the rest.

        Raises:
            InsufficientDataError: Too few rows to fit and to form at least five chunks.
            InvalidInputError: ``reference`` is empty of columns.
        """
        if reference.shape[1] == 0:
            raise InvalidInputError("reference has no columns")
        require_rows(len(reference), MIN_REFERENCE_ROWS, "multivariate drift reference")

        shuffled = reference.sample(frac=1.0, random_state=self.random_state)
        n_holdout = round(len(shuffled) * self.holdout_fraction)
        fit_part, holdout = shuffled.iloc[n_holdout:], shuffled.iloc[:n_holdout]

        chunk_size = self.chunk_size or max(len(holdout) // DEFAULT_CHUNKS, 20)
        n_chunks = len(holdout) // chunk_size
        if n_chunks < MIN_CHUNKS:
            require_rows(len(holdout), MIN_CHUNKS * chunk_size, "multivariate drift holdout")

        self._columns = [str(c) for c in reference.columns]
        self._pipeline = self._build_pipeline(reference).fit(
            fit_part.astype(_object_for_categories(fit_part))
        )

        errors = [
            float(self._row_errors(holdout.iloc[i * chunk_size : (i + 1) * chunk_size]).mean())
            for i in range(n_chunks)
        ]
        self._band = _Band(
            mean=float(np.mean(errors)),
            row_std=float(np.std(errors, ddof=1) * np.sqrt(chunk_size)),
            n_holdout=n_chunks * chunk_size,
        )
        return self

    def score(self, current: pd.DataFrame) -> MultivariateDriftResult:
        """Compute the window's mean reconstruction error and compare it with the band.

        Raises:
            InsufficientDataError: ``current`` has no rows.
            InvalidInputError: Columns the detector was fitted on are missing.
            NotFittedError: :meth:`fit` has not been called.
        """
        band = self._fitted_band()
        require_rows(len(current), 1, "multivariate drift window")
        missing = [c for c in self._columns if c not in current.columns]
        if missing:
            raise InvalidInputError(f"current window is missing columns: {missing}")

        error = float(self._row_errors(current[self._columns]).mean())
        half_width = self.n_sigma * band.row_std * np.sqrt(1 / len(current) + 1 / band.n_holdout)
        lower, upper = band.mean - half_width, band.mean + half_width
        return MultivariateDriftResult(
            reconstruction_error=error,
            lower=float(lower),
            upper=float(upper),
            drifted=bool(error > upper or error < lower),
            n_rows=len(current),
        )

    # ------------------------------------------------------------------ internals

    def _build_pipeline(self, reference: pd.DataFrame) -> Pipeline:
        numeric = [
            c
            for c in reference.columns
            if pd.api.types.is_numeric_dtype(reference[c])
            and not pd.api.types.is_bool_dtype(reference[c])
        ]
        categorical = [c for c in reference.columns if c not in numeric]
        transformers = []
        if numeric:
            transformers.append(
                ("num", SimpleImputer(strategy="mean", keep_empty_features=True), numeric)
            )
        if categorical:
            transformers.append(
                (
                    "cat",
                    Pipeline(
                        [
                            (
                                "impute",
                                SimpleImputer(
                                    strategy="constant",
                                    fill_value="__missing__",
                                    keep_empty_features=True,
                                ),
                            ),
                            (
                                "onehot",
                                OneHotEncoder(
                                    handle_unknown="infrequent_if_exist",
                                    max_categories=self.max_categories,
                                    sparse_output=False,
                                ),
                            ),
                        ]
                    ),
                    categorical,
                )
            )
        return Pipeline(
            [
                ("encode", ColumnTransformer(transformers)),
                ("scale", StandardScaler()),
                ("pca", PCA(n_components=self.variance_to_keep, svd_solver="full")),
            ]
        )

    def _row_errors(self, frame: pd.DataFrame) -> npt.NDArray[np.float64]:
        pipeline = self._fitted_pipeline()
        prepared = pipeline[:-1].transform(frame.astype(_object_for_categories(frame)))
        pca = pipeline.named_steps["pca"]
        reconstructed = pca.inverse_transform(pca.transform(prepared))
        return np.asarray(np.linalg.norm(prepared - reconstructed, axis=1), dtype=np.float64)

    def _fitted_pipeline(self) -> Pipeline:
        if self._pipeline is None:
            raise NotFittedError("PCAReconstructionDrift is not fitted; call fit() first")
        return self._pipeline

    def _fitted_band(self) -> _Band:
        if self._band is None:
            raise NotFittedError("PCAReconstructionDrift is not fitted; call fit() first")
        return self._band


def _object_for_categories(frame: pd.DataFrame) -> dict[str, type]:
    """Cast non-numeric columns to ``object`` so the imputer accepts mixed category types."""
    return {
        str(c): object
        for c in frame.columns
        if not pd.api.types.is_numeric_dtype(frame[c]) or pd.api.types.is_bool_dtype(frame[c])
    }
