# 8. Incident history, a data quality check, one-sided label check, BI tables

Date: 2026-10-25 · Status: accepted

## Context

The demo grew from four models over 30 days to eight models over 90 days, and the dashboard
gained date slicers, period comparison and exports. Four problems showed up.

- **Incidents had no history.** The worker kept only the current state per model, so after an
  incident resolved there was no record of it, and the overview could not show what happened
  last month. A 90-day window makes this visible: the policy-lapse model had a temporary shift
  in late August that resolved on its own.
- **Missing values were invisible.** In the upsell-propensity scenario a pipeline change leaves
  `data_usage_gb` empty for about 70% of rows. The model treats empty as a value it has never
  seen, its scores shift towards confident, and estimated accuracy *rises* by about four points.
  No drift test fires on the rows that do have values. The only check that eventually caught it
  was the label check, three days later, once enough labels had come in.
- **The label check fired on good news.** It flagged measured accuracy outside the estimate's
  range in either direction. On the healthy models, a week of lucky labels above the range
  counted as a failing check.
- **People asked for the numbers outside the dashboard.** Analysts want the data in Power BI or
  Tableau, joined with their own tables, not screenshots.

## Decisions

**Incidents are derived from day history.** `episodes(reference, days)` walks the day documents
in order and returns every episode: opened on the second consecutive day a rule holds, resolved
on the first of seven quiet days, with the signals that fired in between. The rules are the same
as in [ADR 7](0007-server-architecture.md); what changed is that the function is pure and
returns all of them, so the demo builder and the worker produce the same history from the same
documents. The worker reconciles stored incidents with the episodes: it keeps ids for episodes
it already knows (matched by overlap), resolves incidents whose episode ended, and creates new
ones. Incident documents now carry `status` and `resolvedOn`.

**Missing values are their own rule.** A feature's null rate more than 5 points above its
reference rate is a `data_quality` signal; above 25 points it is critical. Like the others it must
hold two days. It ranks first when several signals open together (data quality, concept drift,
estimate drop, multivariate, input drift), because a broken pipeline explains the others and is
the cheapest to fix. Day documents record each feature's null rate, and incident documents list
the features that went missing.

*Why not treat missing as drift?* Drift tests compare distributions of present values. A feature
that is empty 70% of the time can have a perfectly normal distribution in the other 30%. Counting
nulls as a category inside the drift test would make it fire, but the incident would then say
"input distributions shifted", which points people at the data instead of the pipeline.

**The label check is one-sided.** Only measured accuracy below the estimate's range sets
`conceptFlag`. Measured accuracy above the range is still shown on the chart and in the table
view ("above range, not flagged"), but it does not open an incident. With the change, three
random seeds of the eight demo models over 90 days produce no incident on a model without an
injected problem, and every injected problem still opens one within four days.

**A star schema for BI tools.** `sentinel_server.analysis.bi` turns the documents into seven
tables (two dimensions, five facts; see [bi.md](../bi.md)). The demo build writes them as CSV;
the API serves them at `/v1/export/<table>.csv`. Because they are derived from the same
documents, a BI report and the dashboard cannot disagree. `bi/build_bi.py` generates a Power BI
project and a Tableau workbook on those tables. They are generated, not saved from the desktop
tools, so a column change is one edit, the files diff cleanly, and CI checks that the committed
files are current and that the Power BI JSON matches Microsoft's schemas.

*Alternatives.* A Postgres read replica with views for BI tools would avoid the CSV step for a
live deployment, and is the better choice for large fleets. It needs database credentials in
every analyst's tool and does not work for the static demo. CSV over HTTP works for both and is
what every BI tool reads; the API's export endpoint can sit behind the same key as the
dashboard.

## Consequences

- Incident ids are stable across recomputes only while episodes keep overlapping. A backfill
  that splits one episode into two creates a new id for the second.
- The data quality rule uses a fixed 5-point threshold. A feature that is legitimately sparse
  and varies a lot day to day (an optional field) may need a per-feature threshold; there is no
  setting for that yet.
- The BI tables are rebuilt from documents on each export request. That is fine for a handful of
  models; for hundreds, the export should be materialised like the documents are.
- The Power BI and Tableau files cannot be opened in CI. Their structure is checked; whether
  they render is checked by opening them in the desktop tools.
