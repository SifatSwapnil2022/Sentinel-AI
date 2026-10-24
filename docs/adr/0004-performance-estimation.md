# 4. Performance estimation and the concept-drift flag

Date: 2026-10-24 · Status: accepted

## Context

Labels often arrive days or weeks after predictions (loan defaults, churn, fraud chargebacks).
Until they do, accuracy is unknown. Confidence-based performance estimation (CBPE, from
NannyML) estimates it from the model's own probabilities.

## Decision

Implement CBPE for binary classification, matching NannyML exactly:

- **Expected confusion matrix.** For a calibrated probability `p` and prediction `ŷ = 1`, the
  row adds `p` to expected TP and `1 − p` to expected FP; for `ŷ = 0`, `p` to FN and `1 − p` to TN.
  Accuracy, precision, recall and F1 follow from the expected counts.
- **Calibration.** Isotonic regression is applied only if it does not raise Expected Calibration
  Error on any of 10 stratified cross-validation folds (NannyML's rule).
- **Sampling error.** NannyML's per-metric components: the standard deviation of row-level
  contributions on reference data, divided by `sqrt(fraction · n)`. The band is ±3 sampling
  errors, clipped to [0, 1].

Parity tests confirm values and sampling errors match NannyML to within 1e-9 for all four
metrics, with and without calibration.

**Addition: the concept-drift flag.** CBPE assumes the relationship between inputs and outcome
is unchanged. When labels arrive, `check_concept_drift` estimates the metric on the *labelled
rows only* and compares it with the realized value on those same rows. If realized falls outside
the band, the relationship has changed. Comparing on the same rows matters: labels often arrive
for some kinds of rows first, and comparing against an all-rows estimate would confuse that
with a model problem.

## Consequences

- Estimated accuracy is available from the first prediction, with an honest band.
- Poorly calibrated models are handled when calibration demonstrably helps, and left alone when
  it doesn't.
- The flag needs labels (default minimum 100 per window), so it lags; the estimate itself does
  not.
- Multiclass CBPE and regression (DLE) are not yet implemented.
