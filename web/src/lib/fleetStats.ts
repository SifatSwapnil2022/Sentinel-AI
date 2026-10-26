/** Fleet-level figures for the overview, computed from the daily facts under the slicers. */
import type { DailyRow, IncidentRef } from "../data/schema";
import { type DateRange, inRange } from "../filters/filters";

export function rowsIn(rows: readonly DailyRow[], models: ReadonlySet<string>, range: DateRange) {
  return rows.filter((r) => models.has(r.modelId) && inRange(r.date, range));
}

function weighted(rows: readonly DailyRow[], value: (r: DailyRow) => number | null): number | null {
  let total = 0;
  let weight = 0;
  for (const r of rows) {
    const v = value(r);
    if (v === null || r.rows === 0) continue;
    total += v * r.rows;
    weight += r.rows;
  }
  return weight === 0 ? null : total / weight;
}

export interface Kpi {
  value: number | null;
  previous: number | null;
  /** One value per day of the current range, for the sparkline. */
  series: (number | null)[];
}

export interface FleetKpis {
  predictions: Kpi;
  /** Mean of estimated minus reference accuracy, weighted by traffic. */
  gap: Kpi;
  labelCoverage: Kpi;
  p95LatencyMs: Kpi;
  /** Model-days on which any drift check fired. */
  driftDays: Kpi;
}

function daily(
  rows: readonly DailyRow[],
  dates: readonly string[],
  value: (day: DailyRow[]) => number | null,
): (number | null)[] {
  const byDate = new Map<string, DailyRow[]>();
  for (const r of rows) byDate.set(r.date, [...(byDate.get(r.date) ?? []), r]);
  return dates.map((d) => {
    const day = byDate.get(d);
    return day ? value(day) : null;
  });
}

const gapOf = (r: DailyRow) => (r.reference === null ? null : r.estimate - r.reference);
const drifting = (r: DailyRow) => r.driftedFeatures >= 2 || r.multivariateDrifted || r.missingJump > 0.05;

export function fleetKpis(
  current: readonly DailyRow[],
  previous: readonly DailyRow[],
  dates: readonly string[],
): FleetKpis {
  const sum = (rows: readonly DailyRow[]) => (rows.length ? rows.reduce((t, r) => t + r.rows, 0) : null);
  const drift = (rows: readonly DailyRow[]) => (rows.length ? rows.filter(drifting).length : null);
  return {
    predictions: {
      value: sum(current),
      previous: sum(previous),
      series: daily(current, dates, (d) => sum(d)),
    },
    gap: {
      value: weighted(current, gapOf),
      previous: weighted(previous, gapOf),
      series: daily(current, dates, (d) => weighted(d, gapOf)),
    },
    labelCoverage: {
      value: weighted(current, (r) => r.labelCoverage),
      previous: weighted(previous, (r) => r.labelCoverage),
      series: daily(current, dates, (d) => weighted(d, (r) => r.labelCoverage)),
    },
    p95LatencyMs: {
      value: weighted(current, (r) => r.p95LatencyMs),
      previous: weighted(previous, (r) => r.p95LatencyMs),
      series: daily(current, dates, (d) => weighted(d, (r) => r.p95LatencyMs)),
    },
    driftDays: {
      value: drift(current),
      previous: drift(previous),
      series: daily(current, dates, (d) => drift(d)),
    },
  };
}

/** Change from the previous period; null when either side is missing. */
export function change(kpi: Kpi): number | null {
  return kpi.value === null || kpi.previous === null ? null : kpi.value - kpi.previous;
}

/** Diverging bins for "estimated minus reference accuracy", in accuracy units. */
export const GAP_BINS = [
  { below: -0.05, token: "--div-neg-3", label: "5+ points worse" },
  { below: -0.02, token: "--div-neg-2", label: "2 to 5 worse" },
  { below: -0.005, token: "--div-neg-1", label: "0.5 to 2 worse" },
  { below: 0.005, token: "--div-mid", label: "Within 0.5" },
  { below: 0.02, token: "--div-pos-1", label: "0.5 to 2 better" },
  { below: Number.POSITIVE_INFINITY, token: "--div-pos-2", label: "2+ better" },
] as const;

export function gapColor(gap: number): string {
  const bin = GAP_BINS.find((b) => gap < b.below) ?? GAP_BINS[GAP_BINS.length - 1];
  return `var(${bin?.token ?? "--div-mid"})`;
}

/** Incidents (open or resolved) whose span touches the range, for the given models. */
export function incidentsIn(
  incidents: readonly IncidentRef[],
  models: ReadonlySet<string>,
  range: DateRange,
): IncidentRef[] {
  return incidents.filter(
    (i) =>
      models.has(i.modelId) &&
      i.openedOn <= range.to &&
      (i.resolvedOn === null || i.resolvedOn >= range.from),
  );
}

/** Every date in a range, oldest first. */
export function datesIn(range: DateRange): string[] {
  const out: string[] = [];
  const start = Date.parse(`${range.from}T00:00:00Z`);
  for (let i = 0; i < range.days; i++) {
    out.push(new Date(start + i * 86_400_000).toISOString().slice(0, 10));
  }
  return out;
}
