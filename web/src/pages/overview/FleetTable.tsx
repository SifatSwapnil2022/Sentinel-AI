import { Link } from "react-router";
import { SortableTh } from "../../components/SortableTh";
import { StatusMark } from "../../components/StatusMark";
import { TableScroll } from "../../components/TableScroll";
import type { DailyRow, ModelSummary, Status } from "../../data/schema";
import { compact, percent, points, shortDate } from "../../lib/format";
import { useSort } from "../../lib/useSort";
import layout from "../layout.module.css";

const RANK: Record<Status, number> = { critical: 0, warning: 1, healthy: 2 };

export interface FleetRow {
  model: ModelSummary;
  gap: number | null;
  previousGap: number | null;
  predictions: number;
  driftDays: number;
}

type Key =
  | "name"
  | "team"
  | "status"
  | "estimate"
  | "reference"
  | "gap"
  | "previousGap"
  | "measured"
  | "coverage"
  | "predictions"
  | "latency"
  | "drift"
  | "incidents";

const COLUMNS: { key: Key; label: string; numeric?: boolean; compare?: boolean }[] = [
  { key: "name", label: "Model" },
  { key: "team", label: "Team" },
  { key: "status", label: "Status" },
  { key: "estimate", label: "Estimated today", numeric: true },
  { key: "reference", label: "Reference", numeric: true },
  { key: "gap", label: "Against reference", numeric: true },
  { key: "previousGap", label: "Previous period", numeric: true, compare: true },
  { key: "measured", label: "Last measured", numeric: true },
  { key: "coverage", label: "Labels, 7 days", numeric: true },
  { key: "predictions", label: "Predictions", numeric: true },
  { key: "latency", label: "p95 ms", numeric: true },
  { key: "drift", label: "Drift days", numeric: true },
  { key: "incidents", label: "Open", numeric: true },
];

function get(row: FleetRow, key: Key): string | number | null {
  const m = row.model;
  switch (key) {
    case "name":
      return m.name;
    case "team":
      return m.team;
    case "status":
      return -RANK[m.status];
    case "estimate":
      return m.estimate.value;
    case "reference":
      return m.referenceAccuracy;
    case "gap":
      return row.gap;
    case "previousGap":
      return row.previousGap;
    case "measured":
      return m.measured.value;
    case "coverage":
      return m.measured.coverage;
    case "predictions":
      return row.predictions;
    case "latency":
      return m.p95LatencyMs;
    case "drift":
      return row.driftDays;
    case "incidents":
      return m.openAlerts;
  }
}

/** Every model in the slicers, sortable by any column. */
export function FleetTable({ rows, compare }: { rows: FleetRow[]; compare: boolean }) {
  const { sorted, toggle, ariaSort } = useSort<FleetRow, Key>(rows, get, {
    key: "status",
    direction: "desc",
  });
  const columns = COLUMNS.filter((c) => compare || !c.compare);
  return (
    <TableScroll label="Models">
      <table className={layout.table}>
        <thead>
          <tr>
            {columns.map((c) => (
              <SortableTh
                key={c.key}
                label={c.label}
                state={ariaSort(c.key)}
                onSort={() => toggle(c.key)}
                numeric={c.numeric}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const m = row.model;
            return (
              <tr key={m.id}>
                <th scope="row">
                  <Link to={`/models/${m.id}`}>{m.name}</Link>
                </th>
                <td>{m.team}</td>
                <td>
                  <StatusMark status={m.status} />
                </td>
                <td className={layout.num}>{percent(m.estimate.value)}</td>
                <td className={layout.num}>{percent(m.referenceAccuracy)}</td>
                <td className={layout.num}>{points(row.gap)}</td>
                {compare && <td className={layout.num}>{points(row.previousGap)}</td>}
                <td className={layout.num}>
                  {m.measured.value === null || m.measured.asOf === null
                    ? "—"
                    : `${percent(m.measured.value)} on ${shortDate(m.measured.asOf)}`}
                </td>
                <td className={layout.num}>{percent(m.measured.coverage, 0)}</td>
                <td className={layout.num}>{compact(row.predictions)}</td>
                <td className={layout.num}>{Math.round(m.p95LatencyMs)}</td>
                <td className={layout.num}>{row.driftDays}</td>
                <td className={layout.num}>{m.openAlerts}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroll>
  );
}

/** Period aggregates per model from the daily facts. */
export function fleetRows(
  models: ModelSummary[],
  current: readonly DailyRow[],
  previous: readonly DailyRow[],
): FleetRow[] {
  const gap = (rows: readonly DailyRow[]) => {
    let t = 0;
    let w = 0;
    for (const r of rows) {
      if (r.reference === null) continue;
      t += (r.estimate - r.reference) * r.rows;
      w += r.rows;
    }
    return w ? t / w : null;
  };
  return models.map((model) => {
    const mine = current.filter((r) => r.modelId === model.id);
    const before = previous.filter((r) => r.modelId === model.id);
    return {
      model,
      gap: gap(mine),
      previousGap: gap(before),
      predictions: mine.reduce((t, r) => t + r.rows, 0),
      driftDays: mine.filter((r) => r.driftedFeatures >= 2 || r.multivariateDrifted || r.missingJump > 0.05)
        .length,
    };
  });
}
