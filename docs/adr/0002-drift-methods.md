# 2. Drift methods and fixed PSI bins

Date: 2026-10-24 · Status: accepted

## Context

There is no single best drift statistic. Hypothesis tests (KS, chi-square) answer "is there any
difference?", and with tens of thousands of rows the answer is almost always yes, even for
shifts that do not matter. Distances (Wasserstein, Jensen–Shannon) answer "how big is the
difference?", which is what an alert should depend on, but they are noisy on small samples.

## Decision

Choose the method from column type and reference size, using Evidently's documented defaults:

| Column | ≤ 1,000 reference rows | > 1,000 reference rows |
| --- | --- | --- |
| numeric (more than 5 distinct values) | KS, p < 0.05 | Wasserstein / std of reference, ≥ 0.1 |
| categorical | chi-square, p < 0.05 | Jensen–Shannon distance, ≥ 0.1 |
| binary | two-proportion Z, p < 0.05 | Jensen–Shannon distance, ≥ 0.1 |

Using a published default means every choice has a reference, and parity tests prove the
numbers match Evidently's.

**One deliberate difference: PSI bins.** Evidently re-derives PSI bins from reference *and*
current data on every call. Sentinel fixes bins once, at reference deciles, and stores them.
That keeps a feature's histogram comparable from one window to the next, which a time-series
chart needs.

**Edge cases decided explicitly:**

- A category present in the current window but absent from the reference makes chi-square's
  expected count zero; Sentinel returns p = 0 (definite drift) rather than a division error.
- A constant reference column floors the Wasserstein divisor at 0.001, as Evidently does.
- SciPy's exact KS method sometimes fails on degenerate samples and falls back with a warning;
  that one warning is silenced because the fallback result is valid.

## Consequences

- Alerts on large samples measure effect size, not just significance.
- PSI is not numerically identical to Evidently's PSI; parity tests cover the other five
  statistics, and PSI is checked against hand-computed values instead.
