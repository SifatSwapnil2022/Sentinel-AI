import { Link, NavLink } from "react-router";
import { StatusMark } from "../components/StatusMark";
import { useFleet } from "../data/api";
import type { Model } from "../data/schema";
import { shortDate } from "../lib/format";
import styles from "./ModelHeader.module.css";
import layout from "./layout.module.css";

/** Header and tabs shared by a model's Performance and Inputs pages. */
export function ModelHeader({ model }: { model: Model }) {
  const fleet = useFleet();
  const summary = fleet.data?.models.find((m) => m.id === model.id);
  const incidents = fleet.data?.alerts.filter((a) => a.modelId === model.id) ?? [];

  return (
    <header className={layout.header}>
      <nav aria-label="Breadcrumb" className={layout.crumbs}>
        <Link to="/">Overview</Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">{model.name}</span>
      </nav>
      <div className={layout.titleRow}>
        <h1 className={layout.title}>{model.name}</h1>
        <span className={layout.version}>{model.version}</span>
        {summary && <StatusMark status={summary.status} />}
      </div>
      <p className={layout.meta}>
        {model.description} Owned by the {model.team} team. Labels usually arrive within{" "}
        {model.labelDelayDays} days.
      </p>
      {incidents.map((incident) => (
        <p key={incident.id} className={styles.incident} data-severity={incident.severity}>
          <StatusMark status={incident.severity} compact />
          <span>
            Open incident since {shortDate(incident.openedOn)}:{" "}
            <Link to={`/incidents/${incident.id}`}>{incident.title}</Link>
          </span>
        </p>
      ))}
      <nav aria-label="Model sections" className={layout.tabs}>
        <NavLink to={`/models/${model.id}`} end className={layout.tab ?? ""}>
          Performance
        </NavLink>
        <NavLink to={`/models/${model.id}/inputs`} className={layout.tab ?? ""}>
          Inputs
        </NavLink>
      </nav>
    </header>
  );
}
