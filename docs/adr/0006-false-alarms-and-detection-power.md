# 6. False alarms and detection power: the multivariate band, confident segments, reference size

Date: 2026-10-24 · Status: accepted · Amends [3](0003-multivariate-drift.md), [5](0005-calibration-and-concept-band.md)

## Context

Moving the analysis behind a service meant running it every day, for weeks, on every model. That
turns a per-check error rate into an operating cost, so I measured the rates directly instead of
reasoning about them. Three problems came out.

1. **The multivariate detector alarmed on 6.5% of clean days.** Its band was the spread of
   reconstruction error across equal chunks of the held-out reference, used as is. A day's
   window is usually larger than a chunk, so its error varies less than a chunk's, and the band
   was the wrong width for it. On a 3-sigma band the nominal rate is 0.3%; with two sustained
   days required to open an incident, 6.5% still produces several false incidents a year per
   model.
2. **Segment ranking rewarded noise.** Findings were ranked by their contribution to the drop
   (share of traffic × change in the metric). On the credit-risk demo, a 348-row credit-limit
   band with a 10.6-point drop outranked the actual cause, a 198-row division with an 18.6-point
   drop. Their point contributions were nearly equal, but the first was partly noise and the
   second was not.
3. **A real effect sat at the detection limit.** With a 6,000-row reference, credit-risk's concept
   drift was detected in only some random seeds. The reference's own sampling error is part of
   the concept band (ADR 5), so a small reference widens it for every window.

## Decisions

**Scale the multivariate band to the window.** From the chunk spread, infer the spread of a
single row's reconstruction error (`chunk std × √chunk size`). The band for a window of `n` rows
is then `3 · row_std · √(1/n + 1/n_holdout)`. It narrows as windows grow, and never below the
uncertainty of the held-out mean itself. Over ten independent references, 400 clean days each,
the daily false-alarm rate averages 0.55% (worst reference 2.25%), against 6.5% before. The spread
between references is the reference's own sampling error, which the band accounts for but cannot
remove. A slow test simulates 400 clean days and requires at most 1.5%.

**Rank segments by the drop we're confident about.** For each segment, the standard error of its
metric change comes from the within-segment variance of per-row scores in both windows:
`se = √(var_cur/n_cur + var_ref/n_ref)`. Segments are ranked by
`share_cur · min(change + z·se, 0)` with `z = 2`, and listed only if that is still a drop. The
point estimate is kept for display, and the shift-share decomposition still sums exactly.
`confidence=0` restores ranking by point estimate.

**Default to a 20,000-row reference in the demo, and say why.** A larger reference narrows every
band that includes the reference's error. The registry accepts any size from 200 rows, and the
upload limit message recommends 20–50k rows.

**Print whole-number categories as integers.** Counts stored as floats (a column with nulls) were
labelled "prior_claims = 0.0". They now read "prior_claims = 0".

## Measured

Over five random seeds of the four demo scenarios (20 model runs):

| | |
| --- | --- |
| Incidents opened before the injected change started | 0 |
| Incidents on the healthy model (churn-predictor) | 0 of 5 |
| credit-risk concept drift detected | 4 of 5 |
| fraud-screen estimate drop detected | 5 of 5 |
| claims-triage relationship change detected | 5 of 5 |

On the committed demo, credit-risk's top segment is now the injected cause (division = Khulna).

## Consequences

- Fewer findings are listed. A segment whose drop could plausibly be noise is no longer shown,
  even if its point contribution is large. That is the intent: an engineer acts on the top row.
- The 4-of-5 credit-risk result is honest about power. That effect is small (a few points of
  accuracy on a fifth of traffic), and with these traffic volumes it is near what a week of labels
  can resolve. More labels or a larger reference raise the rate; nothing else should.
- The confidence multiplier `z` is a tunable. 2 favours precision in the ranking; 0 gives the
  previous behaviour.
