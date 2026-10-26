/** The explore view: one measure from the daily facts, grouped and pivoted by day. */
import type { DailyRow } from "../data/schema";
import { compact, percent, points } from "./format";

type Aggregate = "sum" | "weighted" | "max";

export interface Measure {
  id: string;
  label: string;
  /** How a group's rows for one day (or the whole period) combine into one number. */
  aggregate: Aggregate;
  value: (row: DailyRow) => number | null;
  format: (v: number) => string;
  /** Bars only make sense for amounts that add up. */
  additive: boolean;
  note: string;
}

export const MEASURES: readonly Measure[] = [
  {
    id: "estimate",
    label: "Estimated accuracy",
    aggregate: "weighted",
    value: (r) => r.estimate,
    format: (v) => percent(v),
    additive: false,
    note: "Averaged over models by their prediction volume.",
  },
  {
    id: "gap",
    label: "Accuracy against reference",
    aggregate: "weighted",
    value: (r) => (r.reference === null ? null : r.estimate - r.reference),
    format: (v) => points(v),
    additive: false,
    note: "Estimated minus reference accuracy, in points, averaged by prediction volume.",
  },
  {
    id: "measured",
    label: "Measured accuracy",
    aggregate: "weighted",
    value: (r) => (r.labelCoverage >= 0.5 ? r.measured : null),
    format: (v) => percent(v),
    additive: false,
    note: "Only days with at least half their labels in; recent days are blank until labels arrive.",
  },
  {
    id: "predictions",
    label: "Predictions",
    aggregate: "sum",
    value: (r) => r.rows,
    format: (v) => compact(Math.round(v)),
    additive: true,
    note: "Total predictions served.",
  },
  {
    id: "coverage",
    label: "Labels in",
    aggregate: "weighted",
    value: (r) => r.labelCoverage,
    format: (v) => percent(v, 0),
    additive: false,
    note: "Share of predictions with an outcome so far.",
  },
  {
    id: "latency",
    label: "p95 latency",
    aggregate: "weighted",
    value: (r) => r.p95LatencyMs,
    format: (v) => `${Math.round(v)} ms`,
    additive: false,
    note: "Each model's daily p95, averaged by prediction volume. Not a fleet-wide percentile.",
  },
  {
    id: "drift",
    label: "Features drifted",
    aggregate: "weighted",
    value: (r) => (r.totalFeatures === 0 ? null : r.driftedFeatures / r.totalFeatures),
    format: (v) => percent(v, 0),
    additive: false,
    note: "Share of a model's features whose drift test fired, averaged by prediction volume.",
  },
  {
    id: "missing",
    label: "Missing values above reference",
    aggregate: "max",
    value: (r) => r.missingJump,
    format: (v) => points(v),
    additive: false,
    note: "The largest rise in any feature's missing share, in points. Worst model in the group.",
  },
];

/** The measure with this id, or the first one. */
export function measureById(id: string | null): Measure {
  const found = MEASURES.find((m) => m.id === id) ?? MEASURES[0];
  if (!found) throw new Error("no measures defined");
  return found;
}

export const GROUPINGS = [
  { id: "model", label: "Model" },
  { id: "team", label: "Team" },
  { id: "fleet", label: "Whole fleet" },
] as const;
export type Grouping = (typeof GROUPINGS)[number]["id"];

export const VIEWS = [
  { id: "line", label: "Line by day" },
  { id: "bar", label: "Bars by day" },
  { id: "total", label: "Period total" },
] as const;
export type View = (typeof VIEWS)[number]["id"];

export function combine(rows: readonly DailyRow[], measure: Measure): number | null {
  let total = 0;
  let weight = 0;
  let best: number | null = null;
  for (const row of rows) {
    const v = measure.value(row);
    if (v === null) continue;
    if (measure.aggregate === "sum") {
      total += v;
      weight = 1;
    } else if (measure.aggregate === "max") {
      best = best === null ? v : Math.max(best, v);
    } else if (row.rows > 0) {
      total += v * row.rows;
      weight += row.rows;
    }
  }
  if (measure.aggregate === "max") return best;
  if (weight === 0) return null;
  return measure.aggregate === "sum" ? total : total / weight;
}

export interface Group {
  id: string;
  /** One value per date, aligned with the dates passed in. */
  values: (number | null)[];
  /** The measure over the whole period. */
  total: number | null;
}

export function groupKey(row: DailyRow, by: Grouping): string {
  return by === "model" ? row.modelId : by === "team" ? row.team : "Fleet";
}

/** Rows grouped and pivoted to one series per group, in the order groups first appear sorted by id. */
export function pivot(rows: readonly DailyRow[], measure: Measure, by: Grouping, dates: readonly string[]): Group[] {
  const groups = new Map<string, DailyRow[]>();
  for (const row of rows) {
    const key = groupKey(row, by);
    const list = groups.get(key);
    if (list) list.push(row);
    else groups.set(key, [row]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([id, list]) => {
      const byDate = new Map<string, DailyRow[]>();
      for (const row of list) byDate.set(row.date, [...(byDate.get(row.date) ?? []), row]);
      return {
        id,
        values: dates.map((d) => {
          const day = byDate.get(d);
          return day ? combine(day, measure) : null;
        }),
        total: combine(list, measure),
      };
    });
}
