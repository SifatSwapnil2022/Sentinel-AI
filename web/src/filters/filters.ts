/**
 * The global slicers: period, comparison, team, status and model search. They live in the URL
 * so a filtered view can be bookmarked or sent to someone, and every page reads the same state.
 */
import type { Status } from "../data/schema";

export const PERIODS = [7, 30, 90] as const;
export type Period = (typeof PERIODS)[number];
export const DEFAULT_PERIOD: Period = 30;
const STATUSES: readonly Status[] = ["critical", "warning", "healthy"];
const ISO = /^\d{4}-\d{2}-\d{2}$/;

export interface Filters {
  period: Period;
  /** A custom range (from brushing a chart); overrides ``period`` when both are set. */
  from: string | null;
  to: string | null;
  /** Show the previous period of the same length alongside. */
  compare: boolean;
  teams: string[];
  statuses: Status[];
  q: string;
}

export const EMPTY: Filters = {
  period: DEFAULT_PERIOD,
  from: null,
  to: null,
  compare: false,
  teams: [],
  statuses: [],
  q: "",
};

function list(value: string | null): string[] {
  return value ? value.split(",").map((v) => v.trim()).filter(Boolean) : [];
}

export function parseFilters(params: URLSearchParams): Filters {
  const period = Number(params.get("period"));
  const from = params.get("from");
  const to = params.get("to");
  const custom = from !== null && to !== null && ISO.test(from) && ISO.test(to) && from <= to;
  return {
    period: (PERIODS as readonly number[]).includes(period) ? (period as Period) : DEFAULT_PERIOD,
    from: custom ? from : null,
    to: custom ? to : null,
    compare: params.get("compare") === "previous",
    teams: list(params.get("team")),
    statuses: list(params.get("status")).filter((s): s is Status =>
      (STATUSES as readonly string[]).includes(s),
    ),
    q: params.get("q")?.trim() ?? "",
  };
}

/** Only non-default values, so a plain URL stays plain. */
export function filtersToParams(f: Filters, base?: URLSearchParams): URLSearchParams {
  const params = new URLSearchParams(base);
  const set = (key: string, value: string | null) => {
    if (value) params.set(key, value);
    else params.delete(key);
  };
  set("period", f.period === DEFAULT_PERIOD ? null : String(f.period));
  set("from", f.from && f.to ? f.from : null);
  set("to", f.from && f.to ? f.to : null);
  set("compare", f.compare ? "previous" : null);
  set("team", f.teams.length ? f.teams.join(",") : null);
  set("status", f.statuses.length ? f.statuses.join(",") : null);
  set("q", f.q || null);
  return params;
}

export function activeCount(f: Filters): number {
  return (
    Number(f.period !== DEFAULT_PERIOD || f.from !== null) +
    Number(f.compare) +
    Number(f.teams.length > 0) +
    Number(f.statuses.length > 0) +
    Number(f.q !== "")
  );
}

const DAY_MS = 86_400_000;

export function addDays(iso: string, days: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

export interface DateRange {
  from: string;
  to: string;
  /** Number of days, inclusive. */
  days: number;
}

/** The dates the filters select, ending no later than ``today``. */
export function dateRange(f: Filters, today: string): DateRange {
  if (f.from && f.to) {
    const to = f.to > today ? today : f.to;
    const from = f.from > to ? to : f.from;
    return { from, to, days: daysBetween(from, to) + 1 };
  }
  return { from: addDays(today, -(f.period - 1)), to: today, days: f.period };
}

/** The same number of days immediately before ``range``. */
export function previousRange(range: DateRange): DateRange {
  const to = addDays(range.from, -1);
  return { from: addDays(to, -(range.days - 1)), to, days: range.days };
}

export function inRange(date: string, range: DateRange): boolean {
  return date >= range.from && date <= range.to;
}

/** Whether a model passes the team, status and search slicers. */
export function matchesModel(
  model: { id: string; name: string; team: string; status: Status },
  f: Filters,
): boolean {
  const q = f.q.toLowerCase();
  return (
    (f.teams.length === 0 || f.teams.includes(model.team)) &&
    (f.statuses.length === 0 || f.statuses.includes(model.status)) &&
    (q === "" || model.id.toLowerCase().includes(q) || model.name.toLowerCase().includes(q))
  );
}
