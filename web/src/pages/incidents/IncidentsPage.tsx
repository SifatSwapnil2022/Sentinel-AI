import { useCallback } from "react";
import { Link, useLocation } from "react-router";
import { Timeline } from "../../charts/Timeline";
import { QueryState } from "../../components/QueryState";
import { SortableTh } from "../../components/SortableTh";
import { StatusMark } from "../../components/StatusMark";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import { useFleet } from "../../data/api";
import type { Fleet, IncidentRef, ModelSummary } from "../../data/schema";
import { dateRange, matchesModel } from "../../filters/filters";
import { FilterBar } from "../../filters/FilterBar";
import { withParams } from "../../filters/links";
import { useFilters } from "../../filters/useFilters";
import { csvName } from "../../lib/csv";
import { incidentsIn } from "../../lib/fleetStats";
import { daysBetween, shortDate } from "../../lib/format";
import { useSort } from "../../lib/useSort";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import styles from "../model/Model.module.css";

const STATES = [
  { id: "open", label: "Open" },
  { id: "resolved", label: "Resolved" },
  { id: "all", label: "All" },
] as const;
type State = (typeof STATES)[number]["id"];

interface Row {
  incident: IncidentRef;
  model: ModelSummary | undefined;
  days: number;
}

type Key = "title" | "model" | "severity" | "status" | "opened" | "resolved" | "days";

export function IncidentsPage() {
  useTitle("Incidents");
  const fleet = useFleet();
  const teams = [...new Set(fleet.data?.models.map((m) => m.team) ?? [])].sort();
  return (
    <>
      <FilterBar teams={teams} />
      <QueryState query={fleet} subject="incidents">
        {(data) => <Incidents fleet={data} />}
      </QueryState>
    </>
  );
}

function Incidents({ fleet }: { fleet: Fleet }) {
  const { filters } = useFilters();
  const { search } = useLocation();
  const requested = new URLSearchParams(search).get("state");
  const state: State = STATES.find((s) => s.id === requested)?.id ?? "open";
  const range = dateRange(filters, fleet.today);
  const models = fleet.models.filter((m) => matchesModel(m, filters));
  const ids = new Set(models.map((m) => m.id));
  const byId = new Map(fleet.models.map((m) => [m.id, m]));
  const touching = incidentsIn([...fleet.alerts, ...fleet.resolved], ids, range);
  const shown = touching.filter((i) => state === "all" || i.status === state);
  const rows: Row[] = shown.map((incident) => ({
    incident,
    model: byId.get(incident.modelId),
    days: daysBetween(incident.openedOn, incident.resolvedOn ?? fleet.today),
  }));

  const get = useCallback((r: Row, key: Key): string | number | null => {
    const i = r.incident;
    switch (key) {
      case "title":
        return i.title;
      case "model":
        return r.model?.name ?? i.modelId;
      case "severity":
        return i.severity === "critical" ? 2 : 1;
      case "status":
        return i.status;
      case "opened":
        return i.openedOn;
      case "resolved":
        return i.resolvedOn;
      case "days":
        return r.days;
    }
  }, []);
  const { sorted, toggle, ariaSort } = useSort<Row, Key>(rows, get, { key: "opened", direction: "desc" });
  const lanes = [...new Set(shown.map((i) => i.modelId))]
    .sort()
    .map((id) => ({ id, label: byId.get(id)?.name ?? id }));
  const counts = {
    open: touching.filter((i) => i.status === "open").length,
    resolved: touching.filter((i) => i.status === "resolved").length,
    all: touching.length,
  };
  const span = `${shortDate(range.from)} to ${shortDate(range.to)}`;
  const th = (key: Key, label: string, numeric = false) => (
    <SortableTh label={label} numeric={numeric} state={ariaSort(key)} onSort={() => toggle(key)} />
  );

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>Incidents</h1>
        <p className={layout.lead}>
          {fleet.alerts.length === 0 ? "Nothing open." : `${fleet.alerts.length} open across the fleet.`} An
          incident opens when a check fails two days running and resolves after 7 quiet days. Signals on
          the same model are grouped into one incident.
        </p>
      </header>

      <nav aria-label="Incident status" className={styles.tabs}>
        {STATES.map((s) => (
          <Link
            key={s.id}
            to={withParams(search, { state: s.id === "open" ? null : s.id })}
            className={styles.tab}
            aria-current={state === s.id ? "page" : undefined}
            replace
          >
            {s.label}
            <span className={styles.tabCount}>{counts[s.id]}</span>
          </Link>
        ))}
      </nav>

      {rows.length === 0 ? (
        <p className={layout.empty}>
          No {state === "all" ? "" : `${state} `}incidents for these filters between {span}.
        </p>
      ) : (
        <div className={layout.grid}>
          <Tile title="Timeline" note={`${span}. Filled bars are open, outlined bars resolved.`}>
            <Timeline lanes={lanes} incidents={shown} from={range.from} to={range.to} label={`Incidents, ${span}`} />
          </Tile>
          <Tile
            title={`${STATES.find((s) => s.id === state)?.label ?? ""} incidents`}
            note={`${rows.length} touching ${span}.`}
            csv={() => ({
              name: csvName("incidents", state, range.from, range.to),
              rows: sorted.map((r) => ({
                incident: r.incident.id,
                model: r.incident.modelId,
                team: r.model?.team ?? null,
                kind: r.incident.kind,
                severity: r.incident.severity,
                status: r.incident.status,
                opened_on: r.incident.openedOn,
                resolved_on: r.incident.resolvedOn,
                days: r.days,
              })),
            })}
          >
            <TableScroll label="Incidents">
              <table className={layout.table}>
                <thead>
                  <tr>
                    {th("title", "Incident")}
                    {th("model", "Model")}
                    {th("severity", "Severity")}
                    {th("status", "Status")}
                    {th("opened", "Opened")}
                    {th("resolved", "Resolved")}
                    {th("days", "Days", true)}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(({ incident: i, model, days }) => (
                    <tr key={i.id}>
                      <th scope="row">
                        <Link to={`/incidents/${i.id}`}>{i.title}</Link>
                        <div className={styles.statNote}>{i.id}</div>
                      </th>
                      <td>
                        <Link to={`/models/${i.modelId}${withParams(search, { state: null, tab: "incidents" })}`}>
                          {model?.name ?? i.modelId}
                        </Link>
                        {model && <div className={styles.statNote}>{model.team}</div>}
                      </td>
                      <td>
                        <StatusMark status={i.severity} />
                      </td>
                      <td>{i.status === "open" ? "Open" : "Resolved"}</td>
                      <td>{shortDate(i.openedOn)}</td>
                      <td>{i.resolvedOn ? shortDate(i.resolvedOn) : "–"}</td>
                      <td className={layout.num}>{days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </Tile>
        </div>
      )}
    </div>
  );
}
