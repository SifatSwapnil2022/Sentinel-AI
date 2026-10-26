# Sentinel dashboard design

## Brief

**Who:** ML engineers and on-call data scientists who own models in production, and the
analysts and leads who report on them.
**Job:** answer three questions. Is any model getting worse right now, including before labels
arrive? If so, where, and why? And how has the fleet done over the last week, month or quarter?
**Where it's used:** a desk monitor during an investigation or a weekly review, and a phone
when an alert fires.

Version 1 answered the first two questions for four models over 30 days. Version 2 covers eight
models over 90 days, so it adds what BI tools are used for: slicers, period comparison, a table
and an export behind every chart, a free-form explore view, and the data as a star schema for
Power BI and Tableau.

## Concept: readings with error bars, laid out as a console

Every estimate is drawn as a **range**: a band with a tick at the estimate. Measured accuracy,
when labels arrive, is a **hollow ring**. The pair appears wherever a metric does: the forest
plot on the overview, the model's accuracy chart, the incident's context chart.

Around those marks, the layout is a monitoring console rather than a document: a sticky top bar,
a sticky filter bar under it, and a 12-column grid of tiles. Each tile has the same header: a
title, one line saying what is plotted and over which dates, then its actions (table view, CSV,
full screen). The header is the only chrome; tiles have a 1px border and no shadow.

## Tokens

All in `src/styles/tokens.css`.

### Colour

Dark by default, because the dashboard is read for long stretches and alongside terminals and
log viewers. Light is one click away and follows the same rules.

| Role | Light | Dark |
| --- | --- | --- |
| Canvas (page) | `#eef2f3` | `#0f1619` |
| Panel (tiles) | `#ffffff` | `#151e22` |
| Raised (controls, headers) | `#f5f8f9` | `#1c272c` |
| Line | `#d8e0e3` | `#26343a` |
| Ink | `#132026` | `#e3ebee` |
| Muted | `#4f6169` | `#a0b0b7` |
| Estimate (series 1) | `#2a78d6` | `#3987e5` |

The neutrals lean slightly blue-green so the estimate blue sits in them without glowing. Neither
mode uses pure black or white for the canvas.

**Data colours are separate from interface colours** and each has one job:

- *Categorical* (`--series-1` to `--series-8`): identity of a model or team, assigned in a fixed
  order by the entity's position in the whole fleet, so filtering never repaints a model.
  Validated with the dataviz palette checker on both panel colours (lightness band, chroma floor,
  colour-blind separation of neighbours, contrast). More than eight series is not allowed;
  the explore view has exactly eight models.
- *Diverging* (`--div-neg-3` to `--div-pos-3`, grey midpoint): accuracy against reference.
  Red is worse, blue is better. Used in the overview heatmap and the segment table.
- *Sequential* (`--seq-0` to `--seq-6`, one blue): magnitude, for the drift heatmap.
- *Status* (good, warning, critical): reserved for status, always with a shape (circle,
  triangle, diamond) and a word. Never used as a series colour.

### Type

**Archivo**, variable, one family for everything. Its width axis does the work two families
would: 84% width for tables, axes and tile notes, so a 13-column table fits; 108% for page
titles, so they read as headings without a second typeface. Tabular numerals everywhere numbers
line up. Base size 14px; scale 11.5, 12.5, 14, 16, 20, 26 and 36 for a single reading.

Sentence case throughout. No all-caps labels, no eyebrows above headings, no monospace for
numbers.

### Layout

```
┌ Sentinel  Overview  Models  Incidents 5  Explore  Reports        Demo data to Oct 24  Dark ┐
├ Period [7][30][90]  Compare  Team ▾  Status ◆▲●  Find a model             Copy link     ┤
│ Overview                                                                                   │
│ Five of eight models need attention ...                                                    │
│ ┌ Predictions ┬ Against reference ┬ Labels in ┬ p95 ┬ Drift days ┬ Open incidents ┐      │
│ ┌ Estimated accuracy today ─────────┐ ┌ Incidents ──────────────────────────┐             │
│ │ forest plot                       │ │ timeline, one lane per model        │             │
│ ┌ Accuracy against reference, by day ───────────────────────────────────────┐             │
│ │ heatmap: models × days, diverging                                        │             │
│ ┌ Models ───────────────────────────────────────────────────────────────────┐             │
│ │ sortable table                                                            │             │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Content is left-aligned up to 1,600px. Tiles span 3 to 12 columns at 1,100px and wider, and
  stack below that. Phones get 16px gutters; the filter bar collapses into a "Filters (n)"
  button and the nav into a menu.
- Radius 3px on tiles, 4px on controls. Status is a shape and a word.

## Interaction

**Slicers live in the address.** Period, custom dates, comparison, team, status and search are
URL parameters, so a filtered view is a link. Navigation carries them from page to page; "Copy
link" copies the current one. Only non-default values are written, so a plain visit has a plain
URL.

**Drill-down follows the data.** A heatmap cell opens the model at the two weeks around that
day; a feature in the drift heatmap opens its distribution; a segment in "largest drops" opens
that feature's table; a timeline bar opens the incident.

**Brushing.** Dragging across the accuracy chart (or Enter on two days with the keyboard) sets
the date slicer to that span.

**Every chart has a table view and a CSV.** The table view is also the accessible version of
the chart. CSV files are named after what they contain and the dates, for example
`sentinel_accuracy-gap_2026-09-25_2026-10-24.csv`.

**Comparison** draws the previous period of the same length as a dashed line or outlined bar,
aligned day by day, and adds a "previous" column to tables. It only appears where the previous
period is a fair comparison.

Motion is limited to one moment and what the user causes: the estimate band on the accuracy
chart draws in once from left to right, and everything else (hover readouts, the brush, opening a
tile full screen) responds to the user. All of it is skipped under `prefers-reduced-motion`.

## Writing

Plain words for what people see: "Estimated accuracy", "Labels in", "Likely 72.6 to 79.3%",
"Against reference". Tile notes say what is plotted and the dates, nothing else. Incident pages
open with one sentence saying what happened and where, built from the data. Empty states say
what is missing ("No incidents for these filters between Sep 25 and Oct 24"). Errors say what
failed and what to do.

The landing page follows the same rule: it describes the problem and what the checks do, links
each claim to a page in the demo, and lists what Sentinel does not do. Figures on it come from
the data (`lib/story.ts`), so regenerating the demo cannot make the copy wrong.

## Review against generic defaults

Before building, the plan was checked against what generated dashboards usually look like, and
changed where it matched:

- **One bright accent on near-black** was the first idea for a dark theme. Replaced with blue-grey
  neutrals and a data palette that only appears in charts; the interface itself has no accent
  colour beyond the active-tab underline.
- **KPI cards with big numbers and coloured deltas.** Kept the KPI row, because a fleet review
  starts with totals, but as one bordered strip with a sparkline each, deltas in muted text, and
  no icons.
- **Identical rounded cards with shadows.** Tiles have a border, a small radius and no shadow,
  and differ in width by what they hold.
- **Two typefaces.** Replaced by one variable family using its width axis.
- **Numbered steps (01, 02, 03)** on the landing page's list of problems. They are not a sequence,
  so the numbers were removed.

## Changes after reviewing screenshots

Every page was captured at 1440px and 390px wide, in both themes, and reviewed:

- The timeline's last date label and the heatmap's labels were clipped; both now reserve room.
- The KPI for label coverage compared a period whose labels are complete with one still filling
  in. It no longer shows a change, and says why.
- The segments table and the "largest drops" list scrolled the page sideways on phones. Both are
  now inside scrollable, focusable regions, and a Playwright test fails any page that scrolls
  sideways.
- Axe flagged charts whose SVG had `role="img"` but contained links (nested interactive
  content). Those charts are now figures with the links reachable inside.
- The incident page said "every part of the traffic got worse" for the data quality incident,
  where accuracy actually went up. The explanation now depends on the kind of incident and the
  direction of the change.
