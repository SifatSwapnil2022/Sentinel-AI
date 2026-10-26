import { Link, useLocation } from "react-router";
import { Sparkline } from "../../charts/Sparkline";
import { QueryState } from "../../components/QueryState";
import { StatusMark } from "../../components/StatusMark";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import { useDaily, useFleet } from "../../data/api";
import type { Daily, Fleet, ModelSummary } from "../../data/schema";
import { dateRange, matchesModel } from "../../filters/filters";
import { FilterBar } from "../../filters/FilterBar";
import { withParams } from "../../filters/links";
import { useFilters } from "../../filters/useFilters";
import { csvName } from "../../lib/csv";
import { datesIn, rowsIn } from "../../lib/fleetStats";
import { compact, percent, points, shortDate } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import styles from "../model/Model.module.css";

export function ModelsPage() {
  useTitle("Models");
  const fleet = useFleet();
  const daily = useDaily();
  const teams = [...new Set(fleet.data?.models.map((m) => m.team) ?? [])].sort();
  return (
    <>
      <FilterBar teams={teams} />
      <QueryState query={fleet} subject="models">
        {(f) => (
          <QueryState query={daily} subject="daily figures">
            {(d) => <Models fleet={f} daily={d} />}
          </QueryState>
        )}
      </QueryState>
    </>
  );
}

function Models({ fleet, daily }: { fleet: Fleet; daily: Daily }) {
  const { filters } = useFilters();
  const { search } = useLocation();
  const range = dateRange(filters, fleet.today);
  const dates = datesIn(range);
  const models = fleet.models.filter((m) => matchesModel(m, filters));
  const ids = new Set(models.map((m) => m.id));
  const rows = rowsIn(daily.rows, ids, range);
  const byTeam = new Map<string, ModelSummary[]>();
  for (const m of models) byTeam.set(m.team, [...(byTeam.get(m.team) ?? []), m]);
  const teams = [...byTeam.keys()].sort();
  const span = `${shortDate(range.from)} to ${shortDate(range.to)}`;
  const link = (id: string) => `/models/${id}${withParams(search, { state: null })}`;

  const series = (id: string) => {
    const byDate = new Map(rows.filter((r) => r.modelId === id).map((r) => [r.date, r.estimate]));
    return dates.map((d) => byDate.get(d) ?? null);
  };
  const volume = (id: string) => rows.filter((r) => r.modelId === id).reduce((s, r) => s + r.rows, 0);

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>Models</h1>
        <p className={layout.lead}>
          {models.length} of {fleet.models.length} models, grouped by the team that owns them.
        </p>
      </header>

      {models.length === 0 ? (
        <p className={layout.empty}>No models match these filters.</p>
      ) : (
        <div className={layout.grid}>
          {teams.map((team) => (
            <Tile
              key={team}
              title={team}
              note={`${byTeam.get(team)?.length ?? 0} models. Trend: estimated accuracy, ${span}.`}
              csv={() => ({
                name: csvName("models", team, range.to),
                rows: (byTeam.get(team) ?? []).map((m) => ({
                  model: m.id,
                  version: m.version,
                  status: m.status,
                  estimate: m.estimate.value,
                  reference: m.referenceAccuracy,
                  predictions: volume(m.id),
                  drifted_features: m.driftedFeatures,
                  total_features: m.totalFeatures,
                  open_incidents: m.openAlerts,
                })),
              })}
            >
              <TableScroll label={`${team} models`}>
                <table className={layout.table}>
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">Status</th>
                      <th scope="col">Trend</th>
                      <th scope="col" className={layout.num}>Estimated today</th>
                      <th scope="col" className={layout.num}>Against reference</th>
                      <th scope="col" className={layout.num}>Predictions</th>
                      <th scope="col" className={layout.num}>Drifted features</th>
                      <th scope="col" className={layout.num}>Open incidents</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(byTeam.get(team) ?? []).map((m) => (
                      <tr key={m.id}>
                        <th scope="row" className={styles.modelCell}>
                          <Link to={link(m.id)}>{m.name}</Link> <span className={styles.statNote}>{m.version}</span>
                          <div className={styles.statNote}>{m.statusReason}</div>
                        </th>
                        <td>
                          <StatusMark status={m.status} />
                        </td>
                        <td>
                          <Sparkline values={series(m.id)} width={140} height={28} label={`Estimated accuracy of ${m.name}, ${span}`} />
                        </td>
                        <td className={layout.num}>{percent(m.estimate.value)}</td>
                        <td className={layout.num}>
                          {points(m.estimate.value - m.referenceAccuracy)}
                        </td>
                        <td className={layout.num}>{compact(volume(m.id))}</td>
                        <td className={layout.num}>
                          {m.driftedFeatures} of {m.totalFeatures}
                        </td>
                        <td className={layout.num}>{m.openAlerts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            </Tile>
          ))}
        </div>
      )}
    </div>
  );
}
