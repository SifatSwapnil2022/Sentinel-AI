import { useLocation, useNavigate } from "react-router";
import { DailyChart } from "../../charts/DailyChart";
import { QueryState } from "../../components/QueryState";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import { useDaily, useFleet } from "../../data/api";
import type { Daily, Fleet } from "../../data/schema";
import { dateRange, matchesModel, previousRange } from "../../filters/filters";
import { FilterBar } from "../../filters/FilterBar";
import { withParams } from "../../filters/links";
import { useFilters } from "../../filters/useFilters";
import { csvName } from "../../lib/csv";
import { GROUPINGS, type Grouping, MEASURES, measureById, pivot, type View, VIEWS } from "../../lib/explore";
import { datesIn, rowsIn } from "../../lib/fleetStats";
import { shortDate } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import modelStyles from "../model/Model.module.css";
import styles from "./Explore.module.css";

export function ExplorePage() {
  useTitle("Explore");
  const fleet = useFleet();
  const daily = useDaily();
  const teams = [...new Set(fleet.data?.models.map((m) => m.team) ?? [])].sort();
  return (
    <>
      <FilterBar teams={teams} />
      <QueryState query={fleet} subject="the fleet">
        {(f) => (
          <QueryState query={daily} subject="daily figures">
            {(d) => <Explore fleet={f} daily={d} />}
          </QueryState>
        )}
      </QueryState>
    </>
  );
}

function Explore({ fleet, daily }: { fleet: Fleet; daily: Daily }) {
  const { filters } = useFilters();
  const { search } = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(search);
  const measure = measureById(params.get("measure"));
  const by: Grouping = GROUPINGS.find((g) => g.id === params.get("by"))?.id ?? "model";
  const requestedView: View = VIEWS.find((v) => v.id === params.get("view"))?.id ?? "line";
  const view: View = requestedView === "bar" && !measure.additive ? "line" : requestedView;
  const set = (patch: Record<string, string | null>) => void navigate(withParams(search, patch), { replace: true });

  const range = dateRange(filters, fleet.today);
  const before = previousRange(range);
  const dates = datesIn(range);
  const models = fleet.models.filter((m) => matchesModel(m, filters));
  const ids = new Set(models.map((m) => m.id));
  const groups = pivot(rowsIn(daily.rows, ids, range), measure, by, dates);
  const previous = filters.compare ? pivot(rowsIn(daily.rows, ids, before), measure, by, datesIn(before)) : [];
  const previousTotal = new Map(previous.map((g) => [g.id, g.total]));

  // Colour follows the entity: its place in the whole fleet, not in the filtered list.
  const order =
    by === "model" ? fleet.models.map((m) => m.id).sort() : by === "team" ? [...new Set(fleet.models.map((m) => m.team))].sort() : ["Fleet"];
  const slot = (id: string) => (by === "fleet" ? undefined : (order.indexOf(id) % 8) + 1);
  const name = (id: string) => (by === "model" ? (fleet.models.find((m) => m.id === id)?.name ?? id) : id);
  const span = `${shortDate(range.from)} to ${shortDate(range.to)}`;
  const ranked = [...groups].sort((a, b) => (b.total ?? -Infinity) - (a.total ?? -Infinity));
  const extent = Math.max(...groups.map((g) => Math.abs(g.total ?? 0)), 1e-9);
  const title = `${measure.label} by ${by === "fleet" ? "day" : GROUPINGS.find((g) => g.id === by)?.label.toLowerCase()}`;

  const csv = () => ({
    name: csvName("explore", measure.id, by, range.from, range.to),
    rows: groups.flatMap((g) =>
      dates.map((date, i) => ({ group: g.id, date, [measure.id]: g.values[i] ?? null })),
    ),
  });

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>Explore</h1>
        <p className={layout.lead}>
          Chart any daily measure for the models under the filters. The choices are kept in the address,
          so a view can be shared as a link.
        </p>
      </header>

      <form className={styles.builder} onSubmit={(e) => e.preventDefault()} aria-label="Chart settings">
        <label>
          <span>Measure</span>
          <select className={modelStyles.select} value={measure.id} onChange={(e) => set({ measure: e.target.value })}>
            {MEASURES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Group by</span>
          <select className={modelStyles.select} value={by} onChange={(e) => set({ by: e.target.value })}>
            {GROUPINGS.map((g) => (
              <option key={g.id} value={g.id}>
                {g.label}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>Show as</legend>
          <div className={modelStyles.segmented}>
            {VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                aria-pressed={view === v.id}
                disabled={v.id === "bar" && !measure.additive}
                title={v.id === "bar" && !measure.additive ? "Bars are for amounts that add up" : undefined}
                onClick={() => set({ view: v.id === "line" ? null : v.id })}
              >
                {v.label}
              </button>
            ))}
          </div>
        </fieldset>
      </form>

      {groups.length === 0 ? (
        <p className={layout.empty}>No data for these filters.</p>
      ) : (
        <div className={layout.grid}>
          <Tile
            title={title}
            note={`${span}. ${measure.note}`}
            table={() => (
              <TableScroll label={title}>
                <table className={layout.table}>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      {groups.map((g) => (
                        <th key={g.id} scope="col" className={layout.num}>
                          {name(g.id)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...dates].reverse().map((date) => {
                      const i = dates.indexOf(date);
                      return (
                        <tr key={date}>
                          <th scope="row">{shortDate(date)}</th>
                          {groups.map((g) => {
                            const v = g.values[i];
                            return (
                              <td key={g.id} className={layout.num}>
                                {v === null || v === undefined ? "–" : measure.format(v)}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableScroll>
            )}
            csv={csv}
          >
            {view === "total" ? (
              <TableScroll label={`${measure.label}, period total`}>
                <table className={layout.table}>
                  <tbody>
                    {ranked.map((g) => (
                      <tr key={g.id}>
                        <th scope="row" className={styles.groupName}>
                          {name(g.id)}
                        </th>
                        <td className={styles.barCell}>
                          <span className={styles.bar} aria-hidden="true">
                            <span
                              style={{
                                width: `${(Math.abs(g.total ?? 0) / extent) * 100}%`,
                                background: `var(--series-${slot(g.id) ?? 1})`,
                              }}
                            />
                          </span>
                        </td>
                        <td className={layout.num}>{g.total === null ? "–" : measure.format(g.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            ) : (
              <DailyChart
                kind={view === "bar" ? "bar" : "line"}
                stacked={view === "bar"}
                zero={measure.additive}
                height={320}
                dates={dates}
                series={groups.map((g) => ({ id: g.id, label: name(g.id), values: g.values, slot: slot(g.id) }))}
                compare={by === "fleet" ? previous[0]?.values : undefined}
                format={measure.format}
                label={`${title}, ${span}`}
              />
            )}
          </Tile>

          <Tile
            title="Summary"
            note={filters.compare ? `${span} against the ${dates.length} days before.` : `${span}. Turn on comparison to add the previous period.`}
            csv={() => ({
              name: csvName("explore-summary", measure.id, by, range.from, range.to),
              rows: groups.map((g) => ({
                group: g.id,
                period: g.total,
                previous: previousTotal.get(g.id) ?? null,
                lowest_day: lowest(g.values),
                highest_day: highest(g.values),
              })),
            })}
          >
            <TableScroll label="Summary">
              <table className={layout.table}>
                <thead>
                  <tr>
                    <th scope="col">{GROUPINGS.find((g) => g.id === by)?.label}</th>
                    <th scope="col" className={layout.num}>Period</th>
                    {filters.compare && (
                      <>
                        <th scope="col" className={layout.num}>Previous</th>
                        <th scope="col" className={layout.num}>Change</th>
                      </>
                    )}
                    <th scope="col" className={layout.num}>Lowest day</th>
                    <th scope="col" className={layout.num}>Highest day</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => {
                    const prev = previousTotal.get(g.id) ?? null;
                    const lo = lowest(g.values);
                    const hi = highest(g.values);
                    return (
                      <tr key={g.id}>
                        <th scope="row">{name(g.id)}</th>
                        <td className={layout.num}>{g.total === null ? "–" : measure.format(g.total)}</td>
                        {filters.compare && (
                          <>
                            <td className={layout.num}>{prev === null ? "–" : measure.format(prev)}</td>
                            <td className={layout.num}>{change(g.total, prev, measure.additive)}</td>
                          </>
                        )}
                        <td className={layout.num}>{lo === null ? "–" : measure.format(lo)}</td>
                        <td className={layout.num}>{hi === null ? "–" : measure.format(hi)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TableScroll>
          </Tile>
        </div>
      )}
    </div>
  );
}

const known = (values: (number | null)[]) => values.filter((v): v is number => v !== null);
const lowest = (values: (number | null)[]) => (known(values).length ? Math.min(...known(values)) : null);
const highest = (values: (number | null)[]) => (known(values).length ? Math.max(...known(values)) : null);

/** Counts change by a percentage; rates and gaps by points. */
function change(now: number | null, before: number | null, additive: boolean): string {
  if (now === null || before === null) return "–";
  if (additive) {
    if (before === 0) return "–";
    const pct = ((now - before) / before) * 100;
    return `${pct >= 0 ? "+" : "−"}${Math.abs(pct).toFixed(1)}%`;
  }
  const pts = (now - before) * 100;
  return `${pts >= 0 ? "+" : "−"}${Math.abs(pts).toFixed(1)} pts`;
}
