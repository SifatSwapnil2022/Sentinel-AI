# 5. Calibration rule, concept-drift band, and slice concentration

Date: 2026-10-24 · Status: accepted · Amends [4](0004-performance-estimation.md)

## Context

Running realistic traffic through the engine for the dashboard demo exposed three problems that
unit tests on clean synthetic data had not.

1. **Calibration was skipped when it was needed.** A gradient-boosted credit model had an
   Expected Calibration Error of 0.036 on a 6,000-row reference. NannyML's rule calibrates only if
   isotonic regression helps on *every* one of 10 folds; with 600-row folds one noisy fold vetoed
   it. Estimated accuracy then ran 1.5 points above measured accuracy on clean data, and the
   concept-drift check raised a false alarm three weeks before anything changed.
2. **The concept-drift band ignored the reference's own error.** Pooling a week of labels (needed
   to resolve 2–3 point gaps) narrowed the window's sampling error until a residual calibration
   error of about 1.5 points looked significant. The estimate is only as precise as the reference
   it was calibrated on, and the band did not say so.
3. **Root cause reported slices that cover most of the traffic.** "is_international = False"
   (95% of rows) "explained" 89% of a fraud model's drop, because any slice that large carries
   most of any change. It said nothing about where the drop was.

## Decisions

**Pooled calibration rule (default).** Calibrate when (a) raw ECE exceeds 1.5× the ECE that
sampling noise alone produces for perfectly calibrated scores, and (b) pooled out-of-fold
isotonic predictions have lower ECE than the raw scores. The noise floor is computed per bin as
`sqrt(2/π) · sqrt(p(1−p)/n)`, row-weighted; a test checks it against simulation. NannyML's rule
remains available as `rule="every_fold"` and the parity tests use it.

**Reference error in the concept-drift band.** `check_concept_drift` widens its band to
`3 · sqrt(se_window² + se_reference²)`. CBPE's own estimate bands are unchanged and still match
NannyML exactly.

**Slice concentration.** A slice is reported only if its metric worsened at least 1.5× as much
as its partition did on average (`min_concentration`, 0 turns it off). When nothing qualifies,
the honest answer is "the drop is broad", and the dashboard shows the largest traffic-mix shifts
instead.

## Consequences

- On the demo data: no false alarm on clean days; credit-risk's real concept drift is caught
  five days after it starts and traced to one division; fraud-screen's broad shift reports no
  culprit slice, and shows large payments doubling their share of traffic.
- Calibration decisions can differ from NannyML's on borderline references. Estimates then differ
  too, by design.
- The concept-drift check needs more labelled rows to fire than before. The demo pools 7 days.
