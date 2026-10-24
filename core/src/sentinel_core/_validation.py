"""Input checks shared across modules. Internal: not part of the public API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from sentinel_core.errors import InsufficientDataError, InvalidInputError

ArrayLike = npt.ArrayLike | pd.Series | Sequence[Any]


def as_1d(values: ArrayLike, name: str) -> npt.NDArray[Any]:
    """Return ``values`` as a 1-D NumPy array, rejecting anything with more dimensions."""
    arr = values.to_numpy() if isinstance(values, pd.Series) else np.asarray(values)
    if arr.ndim == 0:
        arr = arr.reshape(1)
    if arr.ndim != 1:
        raise InvalidInputError(f"{name} must be one-dimensional, got shape {arr.shape}")
    return arr


def is_missing(arr: npt.NDArray[Any]) -> npt.NDArray[np.bool_]:
    """Boolean mask of missing entries; works for numeric and object arrays alike."""
    return np.asarray(pd.isna(arr), dtype=bool)


def drop_missing(arr: npt.NDArray[Any]) -> tuple[npt.NDArray[Any], int]:
    """Return ``arr`` without missing entries, and how many were removed."""
    mask = is_missing(arr)
    return arr[~mask], int(mask.sum())


def require_rows(n: int, minimum: int, what: str) -> None:
    """Raise :class:`InsufficientDataError` when fewer than ``minimum`` rows are available."""
    if n < minimum:
        raise InsufficientDataError(f"{what}: need at least {minimum} non-missing rows, got {n}")


def as_probabilities(values: ArrayLike, name: str) -> npt.NDArray[np.float64]:
    """Validate a 1-D array of probabilities in [0, 1] with no missing values."""
    arr = as_1d(values, name).astype(np.float64, copy=False)
    if np.isnan(arr).any():
        raise InvalidInputError(f"{name} contains NaN")
    if arr.size:
        low, high = float(np.min(arr)), float(np.max(arr))
        if low < 0.0 or high > 1.0:
            raise InvalidInputError(f"{name} must lie in [0, 1]; got range [{low}, {high}]")
    return arr


def as_binary(values: ArrayLike, name: str) -> npt.NDArray[np.int64]:
    """Validate a 1-D array of 0/1 labels with no missing values."""
    arr = as_1d(values, name)
    if is_missing(arr).any():
        raise InvalidInputError(f"{name} contains missing values")
    try:
        as_int = arr.astype(np.int64)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"{name} must contain only 0 and 1") from exc
    if not np.isin(as_int, (0, 1)).all() or not np.array_equal(as_int, arr.astype(np.float64)):
        raise InvalidInputError(f"{name} must contain only 0 and 1")
    return as_int
