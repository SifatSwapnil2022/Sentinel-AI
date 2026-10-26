import { Link } from "react-router";
import { Timeline } from "../../charts/Timeline";
import { StatusMark } from "../../components/StatusMark";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import type { IncidentRef, Model } from "../../data/schema";
import type { DateRange } from "../../filters/filters";
import { csvName } from "../../lib/csv";
import { daysBetween, shortDate } from "../../lib/format";
import layout from "../layout.module.css";

/** Every incident this model has had. The date filter doesn't apply: history is short and sparse. */
export function IncidentsTab({ model, incidents }: { model: Model; incidents: IncidentRef[]; range: DateRange }) {
  const first = model.days[0]?.date ?? "";
  const last = model.days.at(-1)?.date ?? "";
  const ordered = [...incidents].sort((a, b) => b.openedOn.localeCompare(a.openedOn));

  if (ordered.length === 0) {
    return (
      <p className={layout.empty}>
        No incidents in the {model.days.length} days on record. Incidents open when a check fails two
        days running.
      </p>
    );
  }

  return (
    <div className={layout.grid}>
      <Tile title="Incident history" note={`${shortDate(first)} to ${shortDate(last)}, the whole record. Filled bars are open.`}>
        <Timeline
          lanes={[{ id: model.id, label: model.name }]}
          incidents={ordered}
          from={first}
          to={last}
          label={`Incidents for ${model.name}`}
        />
      </Tile>
      <Tile
        title="Incidents"
        csv={() => ({
          name: csvName(model.id, "incidents"),
          rows: ordered.map((i) => ({
            incident: i.id,
            kind: i.kind,
            severity: i.severity,
            status: i.status,
            opened_on: i.openedOn,
            resolved_on: i.resolvedOn,
          })),
        })}
      >
        <TableScroll label="Incidents">
          <table className={layout.table}>
            <thead>
              <tr>
                <th scope="col">Incident</th>
                <th scope="col">Severity</th>
                <th scope="col">Status</th>
                <th scope="col">Opened</th>
                <th scope="col">Resolved</th>
                <th scope="col" className={layout.num}>Days</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((i) => (
                <tr key={i.id}>
                  <th scope="row">
                    <Link to={`/incidents/${i.id}`}>{i.title}</Link>
                  </th>
                  <td>
                    <StatusMark status={i.severity} />
                  </td>
                  <td>{i.status === "open" ? "Open" : "Resolved"}</td>
                  <td>{shortDate(i.openedOn)}</td>
                  <td>{i.resolvedOn ? shortDate(i.resolvedOn) : "–"}</td>
                  <td className={layout.num}>{daysBetween(i.openedOn, i.resolvedOn ?? last)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </Tile>
    </div>
  );
}
