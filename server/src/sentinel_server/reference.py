"""Parse and validate an uploaded reference dataset.

The API runs this on upload, so a bad file is rejected with a precise message straight away;
the worker runs it again before fitting.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from sentinel_server.analysis import FeatureSchema
from sentinel_server.analysis.monitors import MIN_REFERENCE_ROWS

MAX_FEATURES = 500


class ReferenceError(ValueError):
    """The upload can't be used as reference data; ``problems`` says why, one item per issue."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Reference:
    """A validated reference dataset."""

    features: pd.DataFrame
    outcome: npt.NDArray[np.int64]
    score: npt.NDArray[np.float64]
    prediction: npt.NDArray[np.int64] | None
    schema: FeatureSchema


def parse_reference(
    data: bytes,
    *,
    score_column: str,
    label_column: str,
    prediction_column: str | None = None,
) -> Reference:
    """Read a CSV with one row per scored request: features, score, label, optional prediction.

    Raises:
        ReferenceError: The file is unreadable or fails any check; every problem is listed.
    """
    try:
        header = pd.read_csv(io.BytesIO(data), nrows=0).columns.tolist()
        frame = pd.read_csv(io.BytesIO(data), low_memory=False)
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ReferenceError([f"not a readable CSV file: {exc}"]) from exc

    problems: list[str] = []
    duplicates = sorted({c for c in header if header.count(c) > 1})
    if duplicates:
        problems.append(f"duplicate column names: {', '.join(duplicates)}")
    special = [score_column, label_column] + ([prediction_column] if prediction_column else [])
    missing = [c for c in special if c not in frame.columns]
    if missing:
        problems.append(f"missing column(s): {', '.join(missing)}")
    if len(frame) < MIN_REFERENCE_ROWS:
        problems.append(f"needs at least {MIN_REFERENCE_ROWS} rows, got {len(frame)}")
    features = frame.drop(columns=[c for c in special if c in frame.columns])
    if features.shape[1] == 0:
        problems.append("no feature columns besides score and label")
    if features.shape[1] > MAX_FEATURES:
        problems.append(f"at most {MAX_FEATURES} features, got {features.shape[1]}")
    if problems:
        raise ReferenceError(problems)

    outcome = _binary(frame[label_column], label_column, problems)
    prediction = (
        _binary(frame[prediction_column], prediction_column, problems)
        if prediction_column
        else None
    )
    score = pd.to_numeric(frame[score_column], errors="coerce").to_numpy(dtype=np.float64)
    bad = ~np.isfinite(score) | (score < 0) | (score > 1)
    if bad.any():
        problems.append(
            f"{score_column}: {int(bad.sum())} value(s) are missing or outside [0, 1] "
            f"(first at row {int(np.flatnonzero(bad)[0]) + 1})"
        )
    if outcome is not None and len(np.unique(outcome)) < 2:
        problems.append(f"{label_column}: needs both outcomes (0 and 1) to estimate performance")
    if problems:
        raise ReferenceError(problems)
    assert outcome is not None
    return Reference(
        features=features,
        outcome=outcome,
        score=score,
        prediction=prediction,
        schema=FeatureSchema.infer(features),
    )


def _binary(column: pd.Series, name: str, problems: list[str]) -> npt.NDArray[np.int64] | None:
    values = pd.to_numeric(column, errors="coerce")
    bad = ~values.isin([0, 1])
    if bad.any():
        problems.append(
            f"{name}: {int(bad.sum())} value(s) are not 0 or 1 "
            f"(first at row {int(np.flatnonzero(bad.to_numpy())[0]) + 1})"
        )
        return None
    return values.to_numpy(dtype=np.int64)
