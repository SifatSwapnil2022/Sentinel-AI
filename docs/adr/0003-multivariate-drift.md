# 3. Multivariate drift with a held-out band

Date: 2026-10-24 · Status: accepted

## Context

Per-feature tests miss changes in how features relate. If income and loan amount used to rise
together and no longer do, both distributions can stay identical. NannyML detects this with PCA
reconstruction error: fit PCA on reference data, and watch whether new data reconstructs worse.

## Decision

Use PCA reconstruction error (numeric columns mean-imputed; categoricals one-hot encoded, top 20
per column; everything standardised; components keeping 65% of variance), with two changes:

1. **The band comes from held-out rows.** Half the reference trains the PCA; the other half,
   split into chunks, sets the expected error and its spread. Measuring the band on the rows the
   PCA was fitted to understates normal error, which shows up as false alarms in production.
2. **The band scales with window size.** The chunk-level standard deviation is scaled by
   `sqrt(chunk_size / n)` for a window of `n` rows, as a standard error of a mean should. A
   100-row window gets a wide band; a 10,000-row window a narrow one.

## Consequences

- Tests show the detector catching a correlation break with unchanged marginals and raising at
  most 2 false alarms in 40 clean windows.
- Half the reference is spent on the band, so reference sets need at least about 100 rows; the
  detector refuses to fit on less.
- Results are not numerically identical to NannyML's. That is intended, and no parity test
  covers this detector.
