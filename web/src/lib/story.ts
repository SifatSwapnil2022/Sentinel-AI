/**
 * The facts the landing page tells, derived from the same documents the dashboard reads, so
 * the copy can't drift from the data. Each returns null when its case isn't in the data (a live
 * deployment with other models), and the page then leaves that part out.
 */
import type { Fleet, Incident } from "../data/schema";

const DAY_MS = 86_400_000;

function addDays(iso: string, days: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/** The gap between what labels can tell you and what the model is doing now. */
export interface LabelGap {
  modelId: string;
  /** Last accuracy measured from mostly-complete labels, and its date. */
  measured: number;
  measuredOn: string;
  /** Today's estimate and its likely range. */
  estimate: number;
  lower: number;
  upper: number;
  /** When Sentinel opened an incident for the drop. */
  flaggedOn: string;
  /** When labels for that day are expected to be complete. */
  labelsCompleteOn: string;
}

export function labelGap(fleet: Fleet, labelDelayDays: number, modelId: string): LabelGap | null {
  const model = fleet.models.find((m) => m.id === modelId);
  const alert = fleet.alerts.find((a) => a.modelId === modelId && a.kind === "estimate_drop");
  if (!model || !alert) return null;
  const { value, lower, upper } = model.estimate;
  const { value: measured, asOf } = model.measured;
  if (measured === null || asOf === null) return null;
  return {
    modelId,
    measured,
    measuredOn: asOf,
    estimate: value,
    lower,
    upper,
    flaggedOn: alert.openedOn,
    labelsCompleteOn: addDays(alert.openedOn, labelDelayDays),
  };
}

/** How much worse one segment did than the whole. */
export interface HiddenSegment {
  incidentId: string;
  /** "division = Khulna" style conditions. */
  conditions: { feature: string; value: string }[];
  overallDrop: number;
  segmentDrop: number;
}

export function hiddenSegment(incident: Incident): HiddenSegment | null {
  const top = incident.findings[0];
  if (!top) return null;
  return {
    incidentId: incident.id,
    conditions: top.conditions,
    overallDrop: incident.metric.reference - incident.metric.current,
    segmentDrop: top.metricReference - top.metricCurrent,
  };
}

/** The biggest change in how two features move together. */
export interface BrokenLink {
  incidentId: string;
  a: string;
  b: string;
  before: number;
  after: number;
}

export function brokenLink(incident: Incident): BrokenLink | null {
  const pair = incident.correlationChanges[0];
  if (!pair) return null;
  return { incidentId: incident.id, a: pair.a, b: pair.b, before: pair.reference, after: pair.current };
}

/** Models with no open alert over the dashboard window. */
export function quietModels(fleet: Fleet): string[] {
  return fleet.models.filter((m) => m.status === "healthy").map((m) => m.id);
}
