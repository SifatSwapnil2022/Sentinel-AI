import { scaleLinear } from "d3-scale";
import { Link } from "react-router";
import { Legend } from "../components/Legend";
import { QueryState } from "../components/QueryState";
import { GLYPH_PAD, RangeGlyph } from "../components/RangeGlyph";
import { StatusMark } from "../components/StatusMark";
import { useFleet } from "../data/api";
import type { Fleet, IncidentRef, ModelSummary, Status } from "../data/schema";
import { fleetSentence } from "../lib/describe";
import { ago, compact, longDate, percent, percentRange, shortDate } from "../lib/format";
import { useMediaQuery } from "../lib/useMediaQuery";
import styles from "./FleetPage.module.css";
import layout from "./layout.module.css";
import { TableScroll } from "../components/TableScroll";
import { useTitle } from "../lib/useTitle";

const RANK: Record<Status, number> = { critical: 0, warning: 1, healthy: 2 };
const GLYPH_WIDE = 260;
const GLYPH_NARROW = 150;

export function FleetPage() {
  useTitle("Overview");
  const fleet = useFleet();
  return (
    <QueryState query={fleet} subject="the overview">
      {(data) => <Fleet data={data} />}
    </QueryState>
  );
}

function Fleet({ data }: { data: Fleet }) {
  const models = [...data.models].sort(
    (a, b) => RANK[a.status] - RANK[b.status] || a.name.localeCompare(b.name),
  );
  const domain = accuracyDomain(models);
  const narrow = useMediaQuery("(max-width: 640px)");
  const glyphWidth = narrow ? GLYPH_NARROW : GLYPH_WIDE;

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <h1>Overview</h1>
        <p className={layout.lead}>{fleetSentence(models.map((m) => m.status))}</p>
        <p className={layout.meta}>
          Accuracy is estimated from each model's confidence, so it is available before labels
          arrive. Data through {longDate(data.today)}.
        </p>
      </header>

      <section className={layout.section} aria-labelledby="models-heading">
        <div className={layout.sectionHead}>
          <h2 id="models-heading">Models</h2>
          <Legend items={["band", "reference", "ring"]} />
        </div>
        <TableScroll label="Models">
          <table className={`${layout.table} ${styles.fleet}`}>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col" className={styles.phoneHide}>
                  Status
                </th>
                <th scope="col" className={layout.num}>
                  Estimated accuracy
                </th>
                <th scope="col" className={styles.axisHead}>
                  <span className="visually-hidden">Estimate against reference</span>
                  <Axis domain={domain} width={glyphWidth} />
                </th>
                <th scope="col" className={`${layout.num} ${styles.phoneHide}`}>
                  Measured
                </th>
                <th scope="col" className={`${layout.num} ${styles.wide}`}>
                  Labels in, last 7 days
                </th>
                <th scope="col" className={`${layout.num} ${styles.wide}`}>
                  Predictions a day
                </th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <ModelRow key={m.id} model={m} domain={domain} glyphWidth={glyphWidth} />
              ))}
            </tbody>
          </table>
        </TableScroll>
      </section>

      <section className={layout.section} aria-labelledby="incidents-heading">
        <div className={layout.sectionHead}>
          <h2 id="incidents-heading">Open incidents</h2>
          <Link to="/incidents" className={layout.quiet}>
            All incidents
          </Link>
        </div>
        <IncidentList incidents={data.alerts} models={data.models} today={data.today} />
      </section>
    </div>
  );
}

function ModelRow({
  model,
  domain,
  glyphWidth,
}: {
  model: ModelSummary;
  domain: [number, number];
  glyphWidth: number;
}) {
  const { estimate, measured } = model;
  return (
    <tr>
      <td>
        <span className={styles.modelName}>
          <span className={styles.phoneOnly}>
            <StatusMark status={model.status} compact />
          </span>
          <Link to={`/models/${model.id}`} className={styles.modelLink}>
            {model.name}
          </Link>
          <span className={layout.quiet}>{model.version}</span>
        </span>
        <div className={styles.sub}>{model.team}</div>
      </td>
      <td className={styles.phoneHide}>
        <StatusMark status={model.status} />
        {model.status !== "healthy" && <div className={styles.reason}>{model.statusReason}</div>}
      </td>
      <td className={layout.num}>
        <span className={styles.estimate}>{percent(estimate.value)}</span>
        <div className={styles.sub}>{percentRange(estimate.lower, estimate.upper)}</div>
      </td>
      <td className={styles.glyphCell}>
        <RangeGlyph
          value={estimate.value}
          lower={estimate.lower}
          upper={estimate.upper}
          reference={model.referenceAccuracy}
          measured={null}
          domain={domain}
          width={glyphWidth}
          label={model.name}
        />
      </td>
      <td className={`${layout.num} ${styles.phoneHide}`}>
        {measured.value === null || measured.asOf === null ? (
          <span className={layout.quiet}>No labels yet</span>
        ) : (
          <>
            {percent(measured.value)}
            <div className={styles.sub}>on {shortDate(measured.asOf)}</div>
          </>
        )}
      </td>
      <td className={`${layout.num} ${styles.wide}`}>{percent(measured.coverage, 0)}</td>
      <td className={`${layout.num} ${styles.wide}`}>{compact(model.predictionsPerDay)}</td>
    </tr>
  );
}

function Axis({ domain, width }: { domain: [number, number]; width: number }) {
  const x = scaleLinear().domain(domain).range([GLYPH_PAD, width - GLYPH_PAD]);
  const ticks = x.ticks(width < 200 ? 3 : 4);
  return (
    <svg width={width} height={20} className={styles.axis} aria-hidden="true">
      {ticks.map((t) => (
        <text key={t} x={x(t)} y={14} textAnchor="middle">
          {Math.round(t * 100)}%
        </text>
      ))}
    </svg>
  );
}

export function IncidentList({
  incidents,
  models,
  today,
}: {
  incidents: IncidentRef[];
  models: ModelSummary[];
  today: string;
}) {
  if (incidents.length === 0) {
    return <p className={layout.quiet}>No open incidents. Every model is within its expected range.</p>;
  }
  const names = new Map(models.map((m) => [m.id, m.name]));
  return (
    <ul className={styles.incidents}>
      {incidents.map((incident) => (
        <li key={incident.id}>
          <StatusMark status={incident.severity} compact />
          <Link to={`/incidents/${incident.id}`} className={styles.incidentTitle}>
            {incident.title}
          </Link>
          <span className={styles.incidentModel}>{names.get(incident.modelId) ?? incident.modelId}</span>
          <span className={styles.incidentWhen}>
            Opened {shortDate(incident.openedOn)}, {ago(incident.openedOn, today)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Shared accuracy axis for every row, padded and snapped to 5-point steps. */
export function accuracyDomain(models: ModelSummary[]): [number, number] {
  const lows = models.flatMap((m) => [m.estimate.lower, m.referenceAccuracy]);
  const highs = models.flatMap((m) => [m.estimate.upper, m.referenceAccuracy]);
  if (lows.length === 0) return [0.5, 1];
  const low = Math.max(0, Math.floor((Math.min(...lows) - 0.01) * 20) / 20);
  const high = Math.min(1, Math.ceil((Math.max(...highs) + 0.01) * 20) / 20);
  return [low, high];
}
