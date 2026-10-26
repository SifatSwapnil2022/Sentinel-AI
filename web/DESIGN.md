# Sentinel dashboard design

## Brief

**Who:** ML engineers and on-call data scientists who own models in production.
**Job:** answer two questions fast. Is any model getting worse right now, including before
labels arrive? If so, where, and why?
**Where it's used:** a desk monitor during an investigation, and a phone when an alert fires.

## Concept: readings with error bars

Sentinel's distinctive claim is that it *estimates* accuracy before labels exist. An estimate
without its uncertainty is a guess, so every estimate in the interface is drawn as a **range**:
a band with a tick at the estimate. Measured accuracy, when labels arrive, is drawn as a **hollow
ring** in ink. The pair, band and ring, is the visual signature, and it appears everywhere a
metric does: the fleet table, the model header, the main chart.

The fleet page uses this to build a forest plot: one row per model, every band on the same
accuracy axis, so a model whose band sits left of its reference line stands out without reading
a number.

## Tokens

### Colour

| Role | Light | Dark | Notes |
| --- | --- | --- | --- |
| Field (page) | `#e9edea` | `#11171c` | Cool mineral grey-green; deliberately not cream, not near-black |
| Sheet (surfaces, chart plane) | `#f8faf8` | `#182027` | |
| Ink | `#16222e` | `#e3e9ee` | Text, measured values |
| Graphite | `#566370` | `#9aa7b2` | Secondary text, axis labels |
| Hairline | `#d3dad5` | `#26313a` | Rules, gridlines, table separators |
| Estimate | `#2a78d6` | `#3987e5` | The band and tick; dataviz slot 1 |
| Good | `#0ca30c` | same | Status only, always with icon and word |
| Warning | `#fab219` | same | Status only; dark text on it |
| Critical | `#d03b3b` | same | Status only |

Validated with the dataviz palette checker. Estimate blue vs ink passes colour-blind separation
(ΔE 34) and contrast. The checker flags ink as a *categorical* hue (too dark, low chroma); that is
expected. Measured values are observations, not a peer series, and are told apart by shape
(hollow ring vs filled band), as in statistical forecast plots where observed points are black.

### Type

- **Barlow** for interface text and headings. Its slightly squared, road-sign construction suits
  an instrument; it is not the Inter or Space Grotesk most dashboards default to.
- **Barlow Semi Condensed** for tables, axes and dense figures, with tabular numerals so columns
  align. Large standalone readings keep proportional figures.
- Scale (px): 12.5, 13.5, 15 (body), 18, 22, 28, 48 (the one reading per page).
- Sentence case everywhere. No all-caps labels, no letter-spaced eyebrows.

### Layout

```
┌────────────┬──────────────────────────────────────────────────────────┐
│ Sentinel   │ credit-risk v3                                           │
│            │ Lending team. Labels arrive within 14 days.              │
│ Models     │                                                          │
│ ◆ credit…  │ Estimated accuracy      Measured accuracy                │
│ ▲ claims…  │ 76.7%  ├──┼──┤          72.3%  ◯  on Oct 16              │
│ ◆ fraud…   │ likely 75.3 to 78.2     18% of last week labelled        │
│ ● churn…   │                                                          │
│            │ ┌ 30 days ───────────────────────────────────────────┐   │
│ Incidents  │ │ band ▒▒▒▒▒▒▒▒▒▒   rings ◯ ◯ ◯                      │   │
│            │ └─────────────────────────────────────────────────────┘   │
│            │ label coverage ▇▇▇▇▇▆▅▄▃▂▁                                │
└────────────┴──────────────────────────────────────────────────────────┘
```

- Left-aligned content, 1,180px maximum, 16px gutters on phones. The sidebar collapses into a top
  bar below 900px.
- No cards with shadows. Sections are separated by space and a single hairline. Radius 6px on
  controls only; data surfaces are square.
- Status is a shape and a word: circle "Healthy", triangle "Warning", diamond "Critical".

### Motion

One moment: on a model page, the estimate band draws in from left to right once. Everything
else responds only to the user (hover readouts, expanding a feature row). All of it is skipped
under `prefers-reduced-motion`.

### Writing

Plain words for what people see: "Estimated accuracy", "Measured accuracy", "Labels received",
"Likely range". Every incident page opens with one sentence saying what happened and where,
built from the data. Errors say what failed and what to do. No arrows on links, no exclamation
marks.

## The landing page

**Who:** someone deciding in two minutes whether Sentinel solves a real problem: a hiring
engineer, a team lead, an ML engineer with a silent model. **Job:** make the problem concrete,
show the product solving it, and prove the claims.

The page argues in the order a reader doubts:

1. **The problem, with real numbers.** The hero pairs two readings from the demo: what labels
   say (the last day most are in) and what Sentinel estimates today. The gap is the problem.
   The fraud model's real chart sits below it, rings appearing only as labels arrive.
2. **Why existing tools miss it.** Three gaps, each with a source: label delay (card networks'
   120-day dispute window), input drift being the wrong alarm (even label-free estimators assume
   no concept drift), and averages hiding segment failures.
3. **What Sentinel does**, one row per check: what it does, the method, and a link to the live
   demo page that shows it working. Every figure in this section comes from the data documents
   (`lib/story.ts`), never typed into copy, so regenerating the demo can't make the page wrong.
   A case missing from the data (a live deployment with other models) is left out.
4. **How it works**: the data path as an ordered list, so it reads in order to a screen reader
   and reflows to a vertical pipeline on phones.
5. **How it's checked**: measured figures only, each with its denominator.
6. **How to run it, and what it doesn't do yet.** Stating limits is part of the argument.

Same tokens, type and marks as the dashboard; the content column is centred because the page is
read top to bottom. The primary button is ink on field: blue on white fails contrast in the dark
theme, and blue is reserved for data marks. The dashboard moved to `/overview`.

## Review against generic defaults

Checked before building, and changed where the first draft drifted toward a default:

- First draft used a dark theme with one bright accent, like the reference screenshot. Changed
  to a light mineral field with a dark theme as an option; the dark theme keeps the same
  restrained palette rather than adding neon.
- First draft joined metadata with middle dots ("Lending · 14-day labels"). Rewritten as
  sentences.
- First draft put every number in a card. Replaced with a table and one hero reading; cards
  are not used.
- Monospace for numbers was considered and dropped in favour of tabular Barlow Semi Condensed.

## Changes after reviewing screenshots

Every page was captured at desktop and phone sizes, in light and dark mode, and reviewed before
shipping. What that review changed:

- **Concept-drift flags were unexplained.** They sat above days whose measured rings were inside
  the daily band, because the signal uses a pooled week of labels the chart didn't show. Added a
  separate "Check against labels" chart that draws exactly the comparison the signal makes.
- **Phones scrolled sideways.** Grid items default to `min-width: auto`, so wide charts and
  tables stretched the page; visually hidden labels inside scroll containers escaped them too.
  Both fixed, and a Playwright test now fails any page that scrolls sideways.
- **Shares of the drop were capped at 100%.** A segment can cost more than the total when others
  improve. Replaced with each segment's cost in points.
- Axis labels were clipped at the ends of the forest plot, model names wrapped, the reference
  rule was too faint, and the coverage strip's label collided with the y-axis. All fixed.
- Axe flagged horizontally scrolling tables as unreachable by keyboard. They are now focusable,
  labelled regions.
