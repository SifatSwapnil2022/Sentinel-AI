/**
 * Plain-English descriptions built from data. Every incident page opens with one of these, so
 * the reader knows what happened before reading a chart.
 */
import type { DriftMethod, Finding, Incident, SignalKind, Status } from "../data/schema";
import { percent, shortDate } from "./format";

const RANGE_PREFIXES = ["<", "≥"];

/** "division = Khulna", "amount_bdt ≥ 3.44k", "monthly_income 28.7k – 41.9k" */
export function conditionText(feature: string, value: string): string {
  const isRange = RANGE_PREFIXES.some((p) => value.startsWith(p)) || value.includes(" – ");
  return isRange ? `${feature} ${value}` : `${feature} = ${value}`;
}

export function findingText(finding: Finding): string {
  return finding.conditions.map((c) => conditionText(c.feature, c.value)).join(" and ");
}

export const METHOD_LABELS: Record<DriftMethod, string> = {
  ks: "Kolmogorov–Smirnov test",
  chisquare: "Chi-square test",
  z: "Two-proportion Z-test",
  wasserstein: "Wasserstein distance",
  jensenshannon: "Jensen–Shannon distance",
  psi: "Population stability index",
};

export const SIGNAL_LABELS: Record<SignalKind, string> = {
  concept_drift: "Measured accuracy fell outside the estimate",
  estimate_drop: "Estimated accuracy dropped",
  multivariate: "Feature relationships changed",
  input_drift: "Input distributions shifted",
};

export const STATUS_LABELS: Record<Status, string> = {
  healthy: "Healthy",
  warning: "Warning",
  critical: "Critical",
};

/** One or two sentences: what happened, and where (or that it's broad). */
export function summarize(incident: Incident): string {
  const { metric, findings, kind } = incident;
  const top = findings[0];
  const since = shortDate(incident.window.from);

  if (kind === "multivariate") {
    const pair = incident.correlationChanges[0];
    const lead = pair
      ? `The link between ${pair.a} and ${pair.b} changed: their correlation went from ${pair.reference.toFixed(2)} to ${pair.current.toFixed(2)}.`
      : "The way features move together changed.";
    return `${lead} Each feature on its own still looks normal, so per-feature drift checks don't fire.`;
  }

  const opening =
    kind === "concept_drift"
      ? `Measured accuracy on labelled predictions since ${since} is ${percent(metric.current)}, lower than the model's own confidence predicts.`
      : `Estimated accuracy since ${since} is ${percent(metric.current)}, down from ${percent(metric.reference)} on the reference data, before most labels have arrived.`;

  if (top) {
    return `${opening} The drop is concentrated where ${findingText(top)}: accuracy there went from ${percent(top.metricReference)} to ${percent(top.metricCurrent)}.`;
  }
  const shift = incident.mixShifts[0];
  const broad = "No single segment explains it; the drop is spread across the traffic.";
  if (shift) {
    return `${opening} ${broad} The biggest change in who is being scored: ${conditionText(shift.feature, shift.value)} went from ${percent(shift.reference, 0)} to ${percent(shift.current, 0)} of predictions.`;
  }
  return `${opening} ${broad}`;
}

const NUMBER_WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];

function countWord(n: number, lower = false): string {
  const word = NUMBER_WORDS[n] ?? String(n);
  return lower ? word.toLowerCase() : word;
}

/** Overview lead: how many models need attention, in a sentence. */
export function fleetSentence(statuses: Status[]): string {
  const total = statuses.length;
  const critical = statuses.filter((s) => s === "critical").length;
  const warning = statuses.filter((s) => s === "warning").length;
  const attention = critical + warning;
  if (total === 0) return "No models are being monitored yet.";
  if (attention === 0) return `All ${countWord(total, true)} models are healthy.`;
  const parts = [
    critical > 0 ? `${countWord(critical, true)} critical` : null,
    warning > 0 ? `${countWord(warning, true)} with a warning` : null,
  ].filter(Boolean);
  const verb = attention === 1 ? "needs" : "need";
  const of = `${countWord(attention)} of ${countWord(total, true)} models ${verb} attention`;
  return `${of}: ${parts.join(" and ")}.`;
}
