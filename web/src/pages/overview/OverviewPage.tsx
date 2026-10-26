import { useMemo } from "react";
import { Heatmap, ScaleLegend } from "../../charts/Heatmap";
import { Timeline } from "../../charts/Timeline";
import { QueryState } from "../../components/QueryState";
import { Tile } from "../../components/Tile";
import { TableScroll } from "../../components/TableScroll";
import { useDaily, useFleet } from "../../data/api";
import type { Daily, Fleet, Status } from "../../data/schema";
import { addDays, dateRange, matchesModel, previousRange } from "../../filters/filters";
import { FilterBar } from "../../filters/FilterBar";
import { useFilters } from "../../filters/useFilters";
import { csvName } from "../../lib/csv";
import { fleetSentence } from "../../lib/describe";
import { datesIn, fleetKpis, GAP_BINS, gapColor, incidentsIn, rowsIn } from "../../lib/fleetStats";
import { longDate, percent, points, shortDate } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import { AccuracyRanges } from "./AccuracyRanges";
import { FleetTable, fleetRows } from "./FleetTable";
import { Kpis } from "./Kpis";

const RANK: Record<Status, number> = { critical: 0, warning: 1, healthy: 2 };

export function OverviewPage() {
  useTitle("Overview");
  const fleet = useFleet();
  const daily = useDaily();
  const teams = [...new Set(fleet.data?.models.map((m) => m.team) ?? [])].sort();
  return (
    <>
      <FilterBar teams={teams} />
      <QueryState query={fleet} subject="the overview">
        {(f) => (
          <QueryState query={daily} subject="daily figures">
            {(d) => <Overview fleet={f} daily={d} />}
          </QueryState>
        )}
      </QueryState>
    </>
  );
}

function Overview({ fleet, daily }: { fleet: Fleet; daily: Daily }) {
  const { filters } = useFilters();
  const range = dateRange(filters, fleet.today);
  const before = previousRange(range);
  const dates = datesIn(range);

  const models = useMemo(
    () =>
      fleet.models
        .filter((m) => matchesModel(m, filters))
        .sort((a, b) => RANK[a.status] - RANK[b.status] || a.name.localeCompare(b.name)),
    [fleet.models, filters],
  );
  const ids = useMemo(() => new Set(models.map((m) => m.id)), [models]);
  const current = rowsIn(daily.rows, ids, range);
  const previous = rowsIn(daily.rows, ids, before);
  const kpis = fleetKpis(current, previous, dates);
  const incidents = incidentsIn([...fleet.alerts, ...fleet.resolved], ids, range);
  const openAlerts = fleet.alerts.filter((a) => ids.has(a.modelId));
  const rows = fleetRows(models, current, previous);
  const gapByCell = new Map(current.map((r) => [`${r.modelId}|${r.date}`, r]));
  const openings = new Set(incidents.map((i) => `${i.modelId}|${i.openedOn}`));
  const span = `${shortDate(range.from)} to ${shortDate(range.to)}`;

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>Overview</h1>
        <p className={layout.lead}>
          {fleetSentence(models.map((m) => m.status))} Data through {longDate(fleet.today)}.
        </p>
      </header>

      {models.length === 0 ? (
        <p className={layout.empty}>No models match these filters.</p>
      ) : (
        <>
          <Kpis
            kpis={kpis}
            range={range}
            open={{
              critical: openAlerts.filter((a) => a.severity === "critical").length,
              warning: openAlerts.filter((a) => a.severity === "warning").length,
            }}
          />

          <div className={layout.grid}>
            <Tile
              span={6}
              title="Estimated accuracy today"
              note="Band: likely range. Rule: accuracy at release. Ring: last measured."
              table={() => <RangesTable models={models} />}
              csv={() => ({
                name: csvName("estimates", fleet.today),
                rows: models.map((m) => ({
                  model: m.id,
                  estimate: m.estimate.value,
                  lower: m.estimate.lower,
                  upper: m.estimate.upper,
                  reference: m.referenceAccuracy,
                  measured: m.measured.value,
                  measured_on: m.measured.asOf,
                })),
              })}
            >
              <AccuracyRanges models={models} />
            </Tile>

            <Tile
              span={6}
              title="Incidents"
              note={`Open and resolved, ${span}. Filled bars are open.`}
              table={() => <IncidentTable incidents={incidents} />}
              csv={() => ({
                name: csvName("incidents", range.from, range.to),
                rows: incidents.map((i) => ({
                  incident: i.id,
                  model: i.modelId,
                  kind: i.kind,
                  severity: i.severity,
                  status: i.status,
                  opened_on: i.openedOn,
                  resolved_on: i.resolvedOn,
                })),
              })}
            >
              {incidents.length === 0 ? (
                <p className={layout.empty}>No incidents in this period.</p>
              ) : (
                <Timeline
                  lanes={models.map((m) => ({ id: m.id, label: m.name }))}
                  incidents={incidents}
                  from={range.from}
                  to={range.to}
                  label={`Incidents from ${span}`}
                />
              )}
            </Tile>

            <Tile
              title="Accuracy against reference, by day"
              note={`Estimated minus reference accuracy, ${span}. Triangles mark incidents opening. Select a day to open the model there.`}
              table={() => (
                <HeatmapTable models={models.map((m) => m.id)} dates={dates} cells={gapByCell} />
              )}
              csv={() => ({
                name: csvName("accuracy-gap", range.from, range.to),
                rows: current.map((r) => ({
                  model: r.modelId,
                  date: r.date,
                  estimate: r.estimate,
                  reference: r.reference,
                  gap: r.reference === null ? null : r.estimate - r.reference,
                })),
              })}
            >
              <Heatmap
                label={`Daily estimated accuracy against reference for ${models.length} models, ${span}`}
                rows={models.map((m) => ({ id: m.id, label: m.name, href: `/models/${m.id}` }))}
                columns={dates}
                value={(id, date) => {
                  const r = gapByCell.get(`${id}|${date}`);
                  return r?.reference == null ? null : r.estimate - r.reference;
                }}
                color={gapColor}
                marker={(id, date) => openings.has(`${id}|${date}`)}
                cellHref={(id, date) => `/models/${id}?from=${addDays(date, -13)}&to=${date}`}
                describe={(id, date, v) => {
                  const r = gapByCell.get(`${id}|${date}`);
                  return (
                    <>
                      <strong>
                        {id}, {shortDate(date)}
                      </strong>
                      {r ? (
                        <>
                          Estimated {percent(r.estimate)}, {points(v)} against reference
                          <br />
                          {r.rows.toLocaleString("en-US")} predictions, {percent(r.labelCoverage, 0)} labelled
                        </>
                      ) : (
                        "No predictions"
                      )}
                    </>
                  );
                }}
              />
              <ScaleLegend items={GAP_BINS.map((b) => ({ color: `var(${b.token})`, label: b.label }))} />
            </Tile>

            <Tile
              title="Models"
              note={`Figures for ${span} unless they say today.`}
              csv={() => ({
                name: csvName("models", range.from, range.to),
                rows: rows.map((r) => ({
                  model: r.model.id,
                  team: r.model.team,
                  status: r.model.status,
                  estimate_today: r.model.estimate.value,
                  reference: r.model.referenceAccuracy,
                  gap: r.gap,
                  gap_previous_period: r.previousGap,
                  measured: r.model.measured.value,
                  measured_on: r.model.measured.asOf,
                  predictions: r.predictions,
                  p95_latency_ms: r.model.p95LatencyMs,
                  drift_days: r.driftDays,
                  open_incidents: r.model.openAlerts,
                })),
              })}
            >
              <FleetTable rows={rows} compare={filters.compare} />
            </Tile>
          </div>
        </>
      )}
    </div>
  );
}

function RangesTable({ models }: { models: Fleet["models"] }) {
  return (
    <TableScroll label="Estimates">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col" className={layout.num}>Estimated</th>
            <th scope="col" className={layout.num}>Likely range</th>
            <th scope="col" className={layout.num}>Reference</th>
            <th scope="col" className={layout.num}>Last measured</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <th scope="row">{m.name}</th>
              <td className={layout.num}>{percent(m.estimate.value)}</td>
              <td className={layout.num}>
                {percent(m.estimate.lower)} to {percent(m.estimate.upper)}
              </td>
              <td className={layout.num}>{percent(m.referenceAccuracy)}</td>
              <td className={layout.num}>{percent(m.measured.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}

function IncidentTable({ incidents }: { incidents: Fleet["alerts"] }) {
  return (
    <TableScroll label="Incidents">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Incident</th>
            <th scope="col">Model</th>
            <th scope="col">Severity</th>
            <th scope="col">Opened</th>
            <th scope="col">Resolved</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((i) => (
            <tr key={i.id}>
              <th scope="row">{i.title}</th>
              <td>{i.modelId}</td>
              <td>{i.severity}</td>
              <td>{shortDate(i.openedOn)}</td>
              <td>{i.resolvedOn ? shortDate(i.resolvedOn) : "Open"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}

function HeatmapTable({
  models,
  dates,
  cells,
}: {
  models: string[];
  dates: string[];
  cells: Map<string, { estimate: number; reference: number | null }>;
}) {
  return (
    <TableScroll label="Accuracy against reference by day">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Date</th>
            {models.map((m) => (
              <th key={m} scope="col" className={layout.num}>
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((d) => (
            <tr key={d}>
              <th scope="row">{shortDate(d)}</th>
              {models.map((m) => {
                const c = cells.get(`${m}|${d}`);
                return (
                  <td key={m} className={layout.num}>
                    {c?.reference == null ? "—" : points(c.estimate - c.reference)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
