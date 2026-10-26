"""Accuracy by segment: one row per value of each feature, reference against recent traffic."""

from __future__ import annotations

from typing import Any

import numpy as np

from sentinel_core.slices import correctness, expected_correctness

from ._json import r
from .days import DayData
from .monitors import Monitors

MIN_LABELLED = 30
"""Measured accuracy for a segment is shown once it has this many labelled rows."""


def segment_table(monitors: Monitors, current: DayData) -> dict[str, Any]:
    """Every feature's segments, in the binner's order, with traffic share and accuracy.

    Reference accuracy is measured (the reference is labelled); current accuracy is estimated
    from calibrated confidence, and measured too where enough labels have arrived.
    """
    calibrate = monitors.cbpe.calibrator.transform
    ref_bins = monitors.binner.transform(monitors.ref_frame)
    cur_bins = monitors.binner.transform(current.frame.reset_index(drop=True))
    ref_correct = correctness(monitors.ref_outcome, monitors.ref_pred)
    cur_expected = expected_correctness(calibrate(current.proba), current.pred)
    labelled = current.labelled
    cur_correct = np.full(current.rows, np.nan)
    cur_correct[labelled] = correctness(current.outcome[labelled], current.pred[labelled])

    rows = []
    for feature in ref_bins.columns:
        ref_values = ref_bins[feature].to_numpy()
        cur_values = cur_bins[feature].to_numpy()
        order = list(
            dict.fromkeys([*monitors.binner.bins(feature).labels, *ref_values, *cur_values])
        )
        for value in order:
            in_ref = ref_values == value
            in_cur = cur_values == value
            n_ref, n_cur = int(in_ref.sum()), int(in_cur.sum())
            if n_ref == 0 and n_cur == 0:
                continue
            measured_rows = in_cur & labelled
            n_measured = int(measured_rows.sum())
            rows.append(
                {
                    "feature": feature,
                    "value": str(value),
                    "nReference": n_ref,
                    "nCurrent": n_cur,
                    "shareReference": r(n_ref / max(len(ref_values), 1)),
                    "shareCurrent": r(n_cur / max(len(cur_values), 1)),
                    "referenceAccuracy": r(float(ref_correct[in_ref].mean())) if n_ref else None,
                    "estimatedAccuracy": r(float(cur_expected[in_cur].mean())) if n_cur else None,
                    "measuredAccuracy": r(float(np.nanmean(cur_correct[measured_rows])))
                    if n_measured >= MIN_LABELLED
                    else None,
                    "labelled": n_measured,
                }
            )
    return {
        "window": {
            "to": current.date.isoformat(),
            "rows": current.rows,
        },
        "rows": rows,
    }
