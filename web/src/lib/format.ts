/** Formatting for every number and date shown. Pure functions, unit-tested. */

const MINUS = "−";
const EMPTY = "—";

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY;
  return `${signed((value * 100).toFixed(digits))}%`;
}

/** Change in percentage points, signed: "−2.4 points", "+0.8 points". */
export function points(delta: number | null | undefined, digits = 1): string {
  if (delta === null || delta === undefined || !Number.isFinite(delta)) return EMPTY;
  const value = (delta * 100).toFixed(digits);
  if (Number(value) === 0) return `0 points`;
  const prefix = delta > 0 ? "+" : "";
  return `${prefix}${signed(value)} points`;
}

/** "75.3 to 78.2%" */
export function percentRange(lower: number | null, upper: number | null, digits = 1): string {
  if (lower === null || upper === null) return EMPTY;
  return `${(lower * 100).toFixed(digits)} to ${(upper * 100).toFixed(digits)}%`;
}

export function count(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function compact(n: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function decimal(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return EMPTY;
  return signed(value.toFixed(digits));
}

/** p-values: small values in scientific-ish form so they stay readable. */
export function pValue(p: number): string {
  if (!Number.isFinite(p)) return EMPTY;
  if (p < 0.0001) return "p < 0.0001";
  return `p = ${p < 0.01 ? p.toFixed(4) : p.toFixed(3)}`;
}

const shortFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const longFormat = new Intl.DateTimeFormat("en-US", {
  month: "long",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

function parseDate(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

export function shortDate(iso: string): string {
  return shortFormat.format(parseDate(iso));
}

export function longDate(iso: string): string {
  return longFormat.format(parseDate(iso));
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((parseDate(toIso).getTime() - parseDate(fromIso).getTime()) / 86_400_000);
}

/** "today", "yesterday", "8 days ago" */
export function ago(iso: string, todayIso: string): string {
  const days = daysBetween(iso, todayIso);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

function signed(text: string): string {
  return text.startsWith("-") ? `${MINUS}${text.slice(1)}` : text;
}
