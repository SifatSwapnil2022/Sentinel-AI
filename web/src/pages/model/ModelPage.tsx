import { Link, useLocation, useParams } from "react-router";
import { QueryState } from "../../components/QueryState";
import { StatusMark } from "../../components/StatusMark";
import { useFleet, useModel } from "../../data/api";
import type { Model } from "../../data/schema";
import { dateRange, inRange, previousRange } from "../../filters/filters";
import { FilterBar } from "../../filters/FilterBar";
import { withParams } from "../../filters/links";
import { useFilters } from "../../filters/useFilters";
import { shortDate } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import { IncidentsTab } from "./IncidentsTab";
import { InputsTab } from "./InputsTab";
import styles from "./Model.module.css";
import { PerformanceTab } from "./PerformanceTab";
import { SegmentsTab } from "./SegmentsTab";
import { TrafficTab } from "./TrafficTab";

export const TABS = [
  { id: "performance", label: "Performance" },
  { id: "inputs", label: "Inputs" },
  { id: "segments", label: "Segments" },
  { id: "traffic", label: "Traffic" },
  { id: "incidents", label: "Incidents" },
] as const;
export type TabId = (typeof TABS)[number]["id"];

export function ModelPage({ tab: fixed }: { tab?: TabId }) {
  const { modelId = "" } = useParams();
  const { search } = useLocation();
  const requested = new URLSearchParams(search).get("tab");
  const tab: TabId = fixed ?? TABS.find((t) => t.id === requested)?.id ?? "performance";
  const label = TABS.find((t) => t.id === tab)?.label ?? "";
  useTitle(tab === "performance" ? modelId : `${modelId} ${label.toLowerCase()}`);
  const model = useModel(modelId);
  return (
    <>
      <FilterBar scope="model" />
      <QueryState query={model} subject="this model">
        {(data) => <ModelView model={data} tab={tab} />}
      </QueryState>
    </>
  );
}

function ModelView({ model, tab }: { model: Model; tab: TabId }) {
  const { filters, update } = useFilters();
  const { search } = useLocation();
  const fleet = useFleet();
  const summary = fleet.data?.models.find((m) => m.id === model.id);
  const history = [...(fleet.data?.alerts ?? []), ...(fleet.data?.resolved ?? [])].filter(
    (i) => i.modelId === model.id,
  );
  const open = history.filter((i) => i.status === "open");
  const today = model.days.at(-1)?.date ?? "";
  const range = dateRange(filters, today);
  const before = previousRange(range);
  const days = model.days.filter((d) => inRange(d.date, range));
  const previous = model.days.filter((d) => inRange(d.date, before));
  const compare = filters.compare && previous.length > 0 ? previous : undefined;

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <nav aria-label="Breadcrumb" className={layout.crumbs}>
          <Link to={`/overview${withParams(search, { tab: null, feature: null, segment: null })}`}>Overview</Link>
          <span aria-hidden="true">/</span>
          <Link to={`/models${withParams(search, { tab: null, feature: null, segment: null })}`}>Models</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{model.name}</span>
        </nav>
        <div className={layout.titleRow}>
          <h1 className={layout.title}>{model.name}</h1>
          <span className={layout.version}>{model.version}</span>
          {summary && <StatusMark status={summary.status} />}
        </div>
        <p className={layout.lead}>
          {model.description} {model.team} team. Labels arrive within {model.labelDelayDays} days.
        </p>
        {open.map((incident) => (
          <p key={incident.id} className={styles.banner} data-severity={incident.severity}>
            <StatusMark status={incident.severity} compact />
            <span>
              Open since {shortDate(incident.openedOn)}:{" "}
              <Link to={`/incidents/${incident.id}`}>{incident.title}</Link>
            </span>
          </p>
        ))}
      </header>

      <nav aria-label="Model sections" className={styles.tabs}>
        {TABS.map((t) => (
          <Link
            key={t.id}
            to={`/models/${model.id}${withParams(search, { tab: t.id === "performance" ? null : t.id })}`}
            className={styles.tab}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
            {t.id === "incidents" && history.length > 0 && <span className={styles.tabCount}>{history.length}</span>}
          </Link>
        ))}
      </nav>

      {days.length === 0 ? (
        <p className={layout.empty}>No predictions in the selected dates.</p>
      ) : tab === "performance" ? (
        <PerformanceTab
          model={model}
          days={days}
          compare={compare}
          onSelectRange={(from, to) => update({ from, to })}
        />
      ) : tab === "inputs" ? (
        <InputsTab model={model} days={days} />
      ) : tab === "segments" ? (
        <SegmentsTab model={model} />
      ) : tab === "traffic" ? (
        <TrafficTab model={model} days={days} previous={compare} />
      ) : (
        <IncidentsTab model={model} incidents={history} range={range} />
      )}
    </div>
  );
}
