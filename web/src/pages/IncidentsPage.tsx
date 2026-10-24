import { QueryState } from "../components/QueryState";
import { useFleet } from "../data/api";
import { IncidentList } from "./FleetPage";
import layout from "./layout.module.css";

export function IncidentsPage() {
  const fleet = useFleet();
  return (
    <QueryState query={fleet} subject="incidents">
      {(data) => (
        <div className={layout.page}>
          <header className={layout.header}>
            <h1>Incidents</h1>
            <p className={layout.lead}>
              {data.alerts.length === 0
                ? "No open incidents."
                : `${data.alerts.length} open, most severe first.`}{" "}
              Signals that fire on the same model are grouped into one incident.
            </p>
          </header>
          <section className={layout.section} aria-label="Open incidents">
            <IncidentList incidents={data.alerts} models={data.models} today={data.today} />
          </section>
        </div>
      )}
    </QueryState>
  );
}
