/**
 * Runtime schemas for everything the dashboard reads. Data is validated at the boundary so a
 * malformed payload fails loudly in one place instead of rendering NaN deep inside a chart.
 * The static demo and the API serve the same shapes (the server's parity test holds them to it).
 */
import { z } from "zod";

const isoDate = z.iso.date();
const unit = z.number().min(0).max(1);
const nullableUnit = unit.nullable();

export const SCHEMA_VERSION = 2;

export const severitySchema = z.enum(["warning", "critical"]);
export const statusSchema = z.enum(["healthy", "warning", "critical"]);
export const signalKindSchema = z.enum([
  "concept_drift",
  "data_quality",
  "estimate_drop",
  "multivariate",
  "input_drift",
]);
export const driftMethodSchema = z.enum([
  "ks",
  "chisquare",
  "z",
  "wasserstein",
  "jensenshannon",
  "psi",
]);
export const metricNameSchema = z.enum(["accuracy", "precision", "recall", "f1"]);

const rangeSchema = z.object({ value: unit, lower: unit, upper: unit });

// --------------------------------------------------------------------------- fleet

export const modelSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  version: z.string(),
  team: z.string(),
  status: statusSchema,
  statusReason: z.string(),
  referenceAccuracy: unit,
  estimate: rangeSchema,
  measured: z.object({ value: nullableUnit, asOf: isoDate.nullable(), coverage: unit }),
  predictionsPerDay: z.number().int().nonnegative(),
  p95LatencyMs: z.number().nonnegative(),
  driftedFeatures: z.number().int().nonnegative(),
  totalFeatures: z.number().int().positive(),
  multivariateDrifted: z.boolean(),
  openAlerts: z.number().int().nonnegative(),
  trend: z.array(unit),
});

export const incidentStatusSchema = z.enum(["open", "resolved"]);

export const incidentRefSchema = z.object({
  id: z.string(),
  modelId: z.string(),
  kind: signalKindSchema,
  title: z.string(),
  severity: severitySchema,
  status: incidentStatusSchema,
  openedOn: isoDate,
  resolvedOn: isoDate.nullable(),
});

export const fleetSchema = z.object({
  schemaVersion: z.literal(SCHEMA_VERSION),
  today: isoDate,
  windowDays: z.number().int().positive(),
  models: z.array(modelSummarySchema),
  alerts: z.array(incidentRefSchema),
  resolved: z.array(incidentRefSchema),
});

/** One row per model per day: what slicers, heatmaps and the explore view work from. */
export const dailyRowSchema = z.object({
  modelId: z.string(),
  team: z.string(),
  date: isoDate,
  rows: z.number().int().nonnegative(),
  estimate: unit,
  lower: unit,
  upper: unit,
  reference: nullableUnit,
  measured: nullableUnit,
  labelCoverage: unit,
  p95LatencyMs: z.number().nonnegative(),
  driftedFeatures: z.number().int().nonnegative(),
  totalFeatures: z.number().int().nonnegative(),
  multivariateDrifted: z.boolean(),
  conceptFlag: z.boolean().nullable(),
  missingJump: z.number(),
});

export const dailySchema = z.object({
  schemaVersion: z.literal(SCHEMA_VERSION),
  rows: z.array(dailyRowSchema),
});

// --------------------------------------------------------------------------- model

const metricsRecord = <T extends z.ZodType>(item: T) =>
  z.object({ accuracy: item, precision: item, recall: item, f1: item });

export const daySchema = z.object({
  date: isoDate,
  rows: z.number().int().nonnegative(),
  estimate: metricsRecord(
    z.object({ value: nullableUnit, lower: nullableUnit, upper: nullableUnit }),
  ),
  measured: metricsRecord(nullableUnit).nullable(),
  labelCoverage: unit,
  /** The rolling seven-day comparison behind the concept-drift signal; null until enough labels. */
  labelCheck: z
    .object({
      estimated: unit,
      lower: unit,
      upper: unit,
      measured: unit,
      labelled: z.number().int().nonnegative(),
      flagged: z.boolean(),
    })
    .nullable(),
  conceptFlag: z.boolean().nullable(),
  multivariate: z.object({
    error: z.number(),
    lower: z.number(),
    upper: z.number(),
    drifted: z.boolean(),
  }),
  p95LatencyMs: z.number().nonnegative(),
  dataQuality: z.record(z.string(), z.object({ nullRate: unit, referenceNullRate: unit })),
});

export const featureSchema = z.object({
  name: z.string(),
  kind: z.enum(["numeric", "categorical", "binary"]),
  method: driftMethodSchema,
  threshold: z.number(),
  isPValue: z.boolean(),
  series: z.array(
    z.object({
      date: isoDate,
      /** Null on a day the feature was entirely missing, so no test could run. */
      statistic: z.number().nullable(),
      drifted: z.boolean(),
      psi: z.number().nullable(),
      nullRate: nullableUnit,
    }),
  ),
  latest: z.object({
    statistic: z.number(),
    drifted: z.boolean(),
    psi: z.number(),
    nullRate: unit,
  }),
  referenceNullRate: unit,
  histogram: z.object({
    bins: z.array(z.string()),
    reference: z.array(unit),
    current: z.array(unit),
  }),
});

export const modelSchema = z.object({
  schemaVersion: z.literal(SCHEMA_VERSION),
  id: z.string(),
  name: z.string(),
  version: z.string(),
  team: z.string(),
  description: z.string(),
  labelDelayDays: z.number().int().positive(),
  referenceRows: z.number().int().positive(),
  referenceMetrics: metricsRecord(nullableUnit),
  calibration: z.object({ applied: z.boolean(), eceBefore: unit, eceAfter: unit }),
  days: z.array(daySchema).min(1),
  features: z.array(featureSchema),
  segments: z.object({
    window: z.object({ to: isoDate, rows: z.number().int().nonnegative() }),
    rows: z.array(
      z.object({
        feature: z.string(),
        value: z.string(),
        nReference: z.number().int().nonnegative(),
        nCurrent: z.number().int().nonnegative(),
        shareReference: unit,
        shareCurrent: unit,
        referenceAccuracy: nullableUnit,
        estimatedAccuracy: nullableUnit,
        measuredAccuracy: nullableUnit,
        labelled: z.number().int().nonnegative(),
      }),
    ),
  }),
  alertIds: z.array(z.string()),
});

// --------------------------------------------------------------------------- incident

const conditionSchema = z.object({ feature: z.string(), value: z.string() });

export const findingSchema = z.object({
  conditions: z.array(conditionSchema).min(1),
  nReference: z.number().int().nonnegative(),
  nCurrent: z.number().int().nonnegative(),
  shareReference: unit,
  shareCurrent: unit,
  metricReference: unit,
  metricCurrent: unit,
  contribution: z.number(),
  shareOfDrop: z.number().nullable(),
});

export const incidentSchema = z.object({
  id: z.string(),
  modelId: z.string(),
  kind: signalKindSchema,
  title: z.string(),
  severity: severitySchema,
  status: incidentStatusSchema,
  openedOn: isoDate,
  resolvedOn: isoDate.nullable(),
  window: z.object({ from: isoDate, to: isoDate, rows: z.number().int().nonnegative() }),
  metric: z.object({
    name: metricNameSchema,
    basis: z.enum(["estimated", "measured"]),
    reference: unit,
    current: unit,
    performanceEffect: z.number().nullable(),
    mixEffect: z.number().nullable(),
    partition: z.array(z.string()),
  }),
  findings: z.array(findingSchema),
  sampleRows: z.object({
    columns: z.array(z.string()),
    rows: z.array(
      z.object({
        values: z.array(z.union([z.string(), z.number(), z.boolean(), z.null()])),
        score: unit,
        prediction: z.union([z.literal(0), z.literal(1)]),
        outcome: z.union([z.literal(0), z.literal(1)]).nullable(),
      }),
    ),
  }),
  correlationChanges: z.array(
    z.object({ a: z.string(), b: z.string(), reference: z.number(), current: z.number() }),
  ),
  mixShifts: z.array(
    z.object({ feature: z.string(), value: z.string(), reference: unit, current: unit }),
  ),
  signals: z
    .array(
      z.object({
        kind: signalKindSchema,
        title: z.string(),
        severity: severitySchema,
        firedOn: isoDate,
      }),
    )
    .min(1),
  missingFeatures: z.array(
    z.object({ name: z.string(), nullRate: unit, referenceNullRate: unit }),
  ),
  driftedFeatures: z.array(
    z.object({
      name: z.string(),
      method: driftMethodSchema,
      statistic: z.number(),
      threshold: z.number(),
      isPValue: z.boolean(),
      psi: z.number(),
    }),
  ),
});

export type Fleet = z.infer<typeof fleetSchema>;
export type Daily = z.infer<typeof dailySchema>;
export type DailyRow = z.infer<typeof dailyRowSchema>;
export type IncidentStatus = z.infer<typeof incidentStatusSchema>;
export type ModelSummary = z.infer<typeof modelSummarySchema>;
export type IncidentRef = z.infer<typeof incidentRefSchema>;
export type Model = z.infer<typeof modelSchema>;
export type Day = z.infer<typeof daySchema>;
export type Feature = z.infer<typeof featureSchema>;
export type Incident = z.infer<typeof incidentSchema>;
export type Finding = z.infer<typeof findingSchema>;
export type Status = z.infer<typeof statusSchema>;
export type Severity = z.infer<typeof severitySchema>;
export type SignalKind = z.infer<typeof signalKindSchema>;
export type DriftMethod = z.infer<typeof driftMethodSchema>;
export type MetricName = z.infer<typeof metricNameSchema>;

// ------------------------------------------------------------------------ LLM app monitoring

export const llmRuleSchema = z.enum([
  "pii_leak",
  "unsupported_answers",
  "errors",
  "latency",
  "negative_feedback",
  "topic_shift",
]);

const llmExampleSchema = z.object({
  promptVersion: z.string(),
  topic: z.string(),
  question: z.string(),
  context: z.string(),
  answer: z.string(),
  unsupported: z.array(z.string()),
  pii: z.array(z.string()),
  feedback: z.union([z.literal(1), z.literal(-1)]).nullable(),
});

export const llmSchema = z.object({
  schemaVersion: z.literal(1),
  today: isoDate,
  app: z.object({
    id: z.string(),
    name: z.string(),
    description: z.string(),
    model: z.object({ name: z.string(), priceIn: z.number(), priceOut: z.number() }),
    referenceWindow: z.object({ from: isoDate, to: isoDate }),
  }),
  reference: z.object({
    unsupportedRate: unit,
    errorRate: unit,
    negativeRate: unit,
    p95LatencyMs: z.number(),
    topics: z.record(z.string(), z.number().int()),
  }),
  days: z.array(
    z.object({
      date: isoDate,
      requests: z.number().int().nonnegative(),
      errorRate: unit,
      unsupportedRate: unit,
      piiAnswers: z.number().int().nonnegative(),
      refusalRate: unit,
      negativeRate: unit,
      feedback: z.number().int().nonnegative(),
      p50LatencyMs: z.number(),
      p95LatencyMs: z.number(),
      inputTokens: z.number().int(),
      outputTokens: z.number().int(),
      costUsd: z.number(),
      topicShift: unit,
      topics: z.record(z.string(), z.number().int()),
      versions: z.record(z.string(), z.object({ requests: z.number().int(), unsupportedRate: unit })),
      signals: z.array(llmRuleSchema),
    }),
  ),
  versions: z.array(
    z.object({
      version: z.string(),
      from: isoDate,
      to: isoDate,
      requests: z.number().int(),
      unsupportedRate: unit,
      negativeRate: unit,
      p95LatencyMs: z.number(),
      costPer1k: z.number(),
    }),
  ),
  incidents: z.array(
    z.object({
      id: z.string(),
      rule: llmRuleSchema,
      rules: z.array(llmRuleSchema),
      title: z.string(),
      severity: severitySchema,
      status: incidentStatusSchema,
      openedOn: isoDate,
      resolvedOn: isoDate.nullable(),
      days: z.number().int(),
      examples: z.array(llmExampleSchema),
    }),
  ),
});

export type Llm = z.infer<typeof llmSchema>;
export type LlmRule = z.infer<typeof llmRuleSchema>;
