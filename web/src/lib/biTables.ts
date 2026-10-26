/** The BI star schema served as CSV. Column details are in docs/bi.md. */
export interface BiTable {
  name: string;
  kind: "dimension" | "fact";
  grain: string;
  keys: string[];
  description: string;
}

export const BI_TABLES: readonly BiTable[] = [
  {
    name: "dim_model",
    kind: "dimension",
    grain: "One row per model",
    keys: ["model_id"],
    description: "Name, team, version, label delay, reference metrics, current status and open incidents.",
  },
  {
    name: "dim_date",
    kind: "dimension",
    grain: "One row per day",
    keys: ["date"],
    description: "Calendar attributes for slicing by month, ISO week and weekday.",
  },
  {
    name: "fact_model_day",
    kind: "fact",
    grain: "Model × day",
    keys: ["model_id", "date"],
    description:
      "Predictions, estimated and measured accuracy, precision, recall and F1, label coverage, p95 latency, reconstruction error and drift counts.",
  },
  {
    name: "fact_feature_day",
    kind: "fact",
    grain: "Model × feature × day",
    keys: ["model_id", "feature", "date"],
    description: "Drift test result, threshold, PSI and missing-value rate for every feature.",
  },
  {
    name: "fact_segment",
    kind: "fact",
    grain: "Model × feature × segment, last 7 days",
    keys: ["model_id", "feature", "segment"],
    description: "Traffic share and accuracy per segment, reference against the last week.",
  },
  {
    name: "fact_incident",
    kind: "fact",
    grain: "One row per incident",
    keys: ["incident_id"],
    description: "Kind, severity, status, open and resolve dates, accuracy change and the segment that cost most.",
  },
  {
    name: "fact_incident_signal",
    kind: "fact",
    grain: "Incident × signal",
    keys: ["incident_id", "kind"],
    description: "Each check that fired within an incident, and the day it fired.",
  },
];
