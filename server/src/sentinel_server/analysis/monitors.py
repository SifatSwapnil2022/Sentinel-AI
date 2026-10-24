"""Everything fitted once from a model version's labelled reference data."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import joblib
import numpy as np
import numpy.typing as npt
import pandas as pd

import sentinel_core
from sentinel_core.drift import ColumnReference, PCAReconstructionDrift
from sentinel_core.errors import InvalidInputError
from sentinel_core.performance import CBPE, Metric
from sentinel_core.slices import SliceBinner

from .features import FeatureSchema

REFERENCE_SAMPLE_ROWS = 10_000
"""Reference rows kept for histograms, slice baselines and correlations after fitting."""

MIN_REFERENCE_ROWS = 200


@dataclass(eq=False)
class Monitors:
    """Fitted drift detectors, performance estimator and slice bins for one model version."""

    schema: FeatureSchema
    decision_threshold: float
    columns: dict[str, ColumnReference]
    pca: PCAReconstructionDrift
    cbpe: CBPE
    binner: SliceBinner
    ref_frame: pd.DataFrame = field(repr=False)
    ref_outcome: npt.NDArray[np.int64] = field(repr=False)
    ref_proba: npt.NDArray[np.float64] = field(repr=False)
    ref_pred: npt.NDArray[np.int64] = field(repr=False)
    n_reference: int = 0
    core_version: str = sentinel_core.__version__

    @classmethod
    def fit(
        cls,
        features: pd.DataFrame,
        outcome: npt.ArrayLike,
        score: npt.ArrayLike,
        prediction: npt.ArrayLike | None = None,
        *,
        decision_threshold: float = 0.5,
        schema: FeatureSchema | None = None,
        random_state: int = 0,
    ) -> Monitors:
        """Fit every monitor from labelled reference rows.

        Args:
            features: One column per feature.
            outcome: True labels (0/1).
            score: The model's positive-class probability for each row.
            prediction: The model's predicted label; derived from ``decision_threshold`` if absent.
            decision_threshold: Score at or above which a row is predicted positive.
            schema: Feature kinds; inferred from ``features`` when not given.
            random_state: Seed for subsampling and cross-validation.

        Raises:
            InvalidInputError: Lengths differ or the reference is too small to fit on.
        """
        if len(features) < MIN_REFERENCE_ROWS:
            raise InvalidInputError(
                f"reference data needs at least {MIN_REFERENCE_ROWS} rows, got {len(features)}"
            )
        schema = schema or FeatureSchema.infer(features)
        frame = schema.coerce(features).reset_index(drop=True)
        y = np.asarray(outcome, dtype=np.int64)
        p = np.asarray(score, dtype=np.float64)
        pred = (
            (p >= decision_threshold).astype(np.int64)
            if prediction is None
            else np.asarray(prediction, dtype=np.int64)
        )
        if not (len(frame) == y.size == p.size == pred.size):
            raise InvalidInputError("features, outcome, score and prediction lengths differ")

        cbpe = CBPE(decision_threshold=decision_threshold, random_state=random_state).fit(
            y, p, pred
        )
        sample = (
            np.random.default_rng(random_state).choice(
                len(frame), REFERENCE_SAMPLE_ROWS, replace=False
            )
            if len(frame) > REFERENCE_SAMPLE_ROWS
            else np.arange(len(frame))
        )
        return cls(
            schema=schema,
            decision_threshold=decision_threshold,
            columns={c: ColumnReference.fit(frame[c], c) for c in schema.names},
            pca=PCAReconstructionDrift(random_state=random_state).fit(frame),
            cbpe=cbpe,
            binner=SliceBinner().fit(frame),
            ref_frame=frame.iloc[sample].reset_index(drop=True),
            ref_outcome=y[sample],
            ref_proba=p[sample],
            ref_pred=pred[sample],
            n_reference=len(frame),
        )

    @property
    def reference_accuracy(self) -> float:
        """Accuracy on the full reference data."""
        return self.cbpe.reference_metrics[Metric.ACCURACY]

    def summary(self) -> dict[str, Any]:
        """Reference facts shown on the model page."""
        calibrator = self.cbpe.calibrator
        return {
            "referenceRows": self.n_reference,
            "referenceMetrics": {
                m.value: _round(v) for m, v in self.cbpe.reference_metrics.items()
            },
            "calibration": {
                "applied": calibrator.applied,
                "eceBefore": _round(calibrator.ece_before),
                "eceAfter": _round(calibrator.ece_after),
            },
        }

    def to_bytes(self) -> bytes:
        """Serialise for storage. Only ever loaded from Sentinel's own database."""
        buffer = io.BytesIO()
        joblib.dump(self, buffer, compress=3)
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> Monitors:
        """Inverse of :meth:`to_bytes`.

        joblib uses pickle, which can run code on load, so this must only receive bytes this
        service wrote itself (``model_versions.artifacts``), never user uploads.
        """
        loaded = joblib.load(io.BytesIO(data))
        if not isinstance(loaded, cls):
            raise TypeError(f"stored artifacts are a {type(loaded).__name__}, not Monitors")
        return loaded


def _round(x: float | None, digits: int = 4) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), digits)
