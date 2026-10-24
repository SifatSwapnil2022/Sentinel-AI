import { Link, useParams } from "react-router";
import { BridgeChart } from "../charts/BridgeChart";
import { QueryState } from "../components/QueryState";
import { StatusMark } from "../components/StatusMark";
import { useFleet, useIncident } from "../data/api";
import type { Finding, Incident, SignalKind } from "../data/schema";
import { conditionText, METHOD_LABELS, summarize } from "../lib/describe";
import { ago, count, decimal, percent, points, pValue, shortDate } from "../lib/format";
import styles from "./IncidentPage.module.css";
import layout from "./layout.module.css";
import { TableScroll } from "../components/TableScroll";

const SIGNAL_RULES: Record<SignalKind, string> = {
  estimate_drop:
    "The top of the estimate's likely range fell below reference accuracy two days in a row.",
  concept_drift:
    "Measured accuracy over the past seven days fell outside the estimate's range two days in a row.",
  multivariate: "Reconstruction error left its expected range two days in a row.",
  input_drift: "Two or more features drifted two days in a row.",
};

export function IncidentPage() {
  const { incidentId = "" } = useParams();
  const incident = useIncident(incidentId);
  return (
    <QueryState query={incident} subject="this incident">
      {(data) => <IncidentView incident={data} />}
    </QueryState>
  );
}

function IncidentView({ incident }: { incident: Incident }) {
  const fleet = useFleet();
  const today = fleet.data?.today ?? incident.window.to;
  const model = fleet.data?.models.find((m) => m.id === incident.modelId);
  const { metric } = incident;
  const top = incident.findings[0];

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <nav aria-label="Breadcrumb" className={layout.crumbs}>
          <Link to="/incidents">Incidents</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{incident.id}</span>
        </nav>
        <div className={layout.titleRow}>
          <h1>{incident.title}</h1>
          <StatusMark status={incident.severity} />
        </div>
        <p className={layout.meta}>
          <Link to={`/models/${incident.modelId}`} className={layout.data}>
            {model?.name ?? incident.modelId}
          </Link>
          {model && ` ${model.version}`}. Opened {shortDate(incident.openedOn)},{" "}
          {ago(incident.openedOn, today)}. Covers {count(incident.window.rows)}{" "}
          {metric.basis === "measured" ? "labelled predictions" : "predictions"} from{" "}
          {shortDate(incident.window.from)} to {shortDate(incident.window.to)}.
        </p>
        <p className={layout.lead}>{summarize(incident)}</p>
      </header>

      <section className={layout.section} aria-labelledby="signals-heading">
        <h2 id="signals-heading">What fired</h2>
        <ol className={styles.timeline}>
          {incident.signals.map((s) => (
            <li key={s.kind}>
              <time dateTime={s.firedOn} className={styles.when}>
                {shortDate(s.firedOn)}
              </time>
              <div>
                <p className={styles.signalTitle}>
                  <StatusMark status={s.severity} compact /> {s.title}
                </p>
                <p className={layout.quiet}>{SIGNAL_RULES[s.kind]}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {metric.performanceEffect !== null && metric.mixEffect !== null && (
        <section className={layout.section} aria-labelledby="change-heading">
          <h2 id="change-heading">Where the change comes from</h2>
          <p className={layout.meta}>
            Splitting predictions by {metric.partition.join(" and ") || "segment"}, the{" "}
            {metric.basis} accuracy change of {points(metric.current - metric.reference)} breaks
            into the part caused by the model doing worse within segments, and the part caused by
            more traffic coming from segments that were always harder.
          </p>
          <BridgeChart
            reference={metric.reference}
            performanceEffect={metric.performanceEffect}
            mixEffect={metric.mixEffect}
            current={metric.current}
            basis={metric.basis}
          />
        </section>
      )}

      <section className={layout.section} aria-labelledby="segments-heading">
        <h2 id="segments-heading">Segments</h2>
        {incident.findings.length > 0 ? (
          <Findings
            findings={incident.findings}
            basis={metric.basis}
            total={metric.current - metric.reference}
          />
        ) : (
          <MixShifts incident={incident} />
        )}
      </section>

      {incident.correlationChanges.length > 0 && (
        <section className={layout.section} aria-labelledby="corr-heading">
          <h2 id="corr-heading">Relationships that changed most</h2>
          <TableScroll label="Relationships that changed">
            <table className={layout.table}>
              <thead>
                <tr>
                  <th scope="col">Features</th>
                  <th scope="col" className={layout.num}>Reference correlation</th>
                  <th scope="col" className={layout.num}>Now</th>
                  <th scope="col" className={layout.num}>Change</th>
                </tr>
              </thead>
              <tbody>
                {incident.correlationChanges.map((c) => (
                  <tr key={`${c.a}-${c.b}`}>
                    <td className={layout.data}>
                      {c.a} and {c.b}
                    </td>
                    <td className={layout.num}>{decimal(c.reference)}</td>
                    <td className={layout.num}>{decimal(c.current)}</td>
                    <td className={layout.num}>{decimal(c.current - c.reference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </section>
      )}

      {incident.driftedFeatures.length > 0 && (
        <section className={layout.section} aria-labelledby="drift-heading">
          <div className={layout.sectionHead}>
            <h2 id="drift-heading">Features that drifted</h2>
            <Link to={`/models/${incident.modelId}/inputs`} className={layout.quiet}>
              See all inputs
            </Link>
          </div>
          <TableScroll label="Features that drifted">
            <table className={layout.table}>
              <thead>
                <tr>
                  <th scope="col">Feature</th>
                  <th scope="col">Test</th>
                  <th scope="col" className={layout.num}>Result</th>
                  <th scope="col" className={layout.num}>Threshold</th>
                  <th scope="col" className={layout.num}>PSI</th>
                </tr>
              </thead>
              <tbody>
                {incident.driftedFeatures.map((f) => (
                  <tr key={f.name}>
                    <td className={layout.data}>{f.name}</td>
                    <td className={layout.quiet}>{METHOD_LABELS[f.method]}</td>
                    <td className={layout.num}>
                      {f.isPValue ? pValue(f.statistic) : decimal(f.statistic, 3)}
                    </td>
                    <td className={layout.num}>{f.isPValue ? `p < ${f.threshold}` : `≥ ${decimal(f.threshold, 2)}`}</td>
                    <td className={layout.num}>{decimal(f.psi, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </section>
      )}

      {top && incident.sampleRows.rows.length > 0 && (
        <section className={layout.section} aria-labelledby="examples-heading">
          <h2 id="examples-heading">Example predictions</h2>
          <p className={layout.meta}>
            From the top segment, where{" "}
            {top.conditions.map((c) => conditionText(c.feature, c.value)).join(" and ")}.
          </p>
          <SampleRows incident={incident} />
        </section>
      )}
    </div>
  );
}

function Findings({
  findings,
  basis,
  total,
}: {
  findings: Finding[];
  basis: "estimated" | "measured";
  total: number;
}) {
  const largest = Math.max(...findings.map((f) => Math.abs(f.contribution)), 1e-6);
  return (
    <>
      <p className={layout.meta}>
        Ranked by how many points of {basis} accuracy each segment cost overall (its change, weighted
        by its share of traffic), against a total change of {points(total)}. Only segments that got
        clearly worse than average are listed. Segments overlap, so their costs don't add up, and one
        can cost more than the total when other segments improved.
      </p>
      <TableScroll label="Segments">
        <table className={layout.table}>
          <thead>
            <tr>
              <th scope="col">Segment</th>
              <th scope="col" className={layout.num}>Predictions</th>
              <th scope="col" className={layout.num}>Accuracy before</th>
              <th scope="col" className={layout.num}>Now</th>
              <th scope="col" className={layout.num}>Change</th>
              <th scope="col">Cost to overall accuracy</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((f) => {
              const key = f.conditions.map((c) => `${c.feature}=${c.value}`).join("&");
              return (
                <tr key={key}>
                  <td>
                    <ul className={styles.conditions}>
                      {f.conditions.map((c) => (
                        <li key={c.feature}>{conditionText(c.feature, c.value)}</li>
                      ))}
                    </ul>
                  </td>
                  <td className={layout.num}>{count(f.nCurrent)}</td>
                  <td className={layout.num}>{percent(f.metricReference)}</td>
                  <td className={layout.num}>{percent(f.metricCurrent)}</td>
                  <td className={layout.num}>{points(f.metricCurrent - f.metricReference)}</td>
                  <td>
                    <div className={styles.share}>
                      <span
                        className={styles.shareBar}
                        style={{ width: `${(Math.abs(f.contribution) / largest) * 120}px` }}
                      />
                      <span className={styles.shareValue}>{points(f.contribution)}</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </>
  );
}

function MixShifts({ incident }: { incident: Incident }) {
  return (
    <>
      <p className={styles.callout}>
        No segment stands out: every part of the traffic got worse by about the same amount. That
        points to a broad change in what the model is being asked to score, shown below.
      </p>
      <TableScroll label="Traffic shifts">
        <table className={layout.table}>
          <thead>
            <tr>
              <th scope="col">Segment</th>
              <th scope="col" className={layout.num}>Share before</th>
              <th scope="col" className={layout.num}>Now</th>
              <th scope="col">Change in share</th>
            </tr>
          </thead>
          <tbody>
            {incident.mixShifts.map((m) => (
              <tr key={`${m.feature}=${m.value}`}>
                <td className={layout.data}>{conditionText(m.feature, m.value)}</td>
                <td className={layout.num}>{percent(m.reference, 0)}</td>
                <td className={layout.num}>{percent(m.current, 0)}</td>
                <td>
                  <MixBar before={m.reference} after={m.current} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </>
  );
}

function MixBar({ before, after }: { before: number; after: number }) {
  const width = 160;
  const scale = (v: number) => Math.min(v, 1) * width;
  return (
    <svg width={width} height={16} aria-label={`${percent(before, 0)} to ${percent(after, 0)}`} role="img">
      <line x1={0} x2={width} y1={8} y2={8} stroke="var(--hairline)" />
      <line
        x1={scale(before)}
        x2={scale(after)}
        y1={8}
        y2={8}
        stroke="var(--ink)"
        strokeWidth={2}
      />
      <circle cx={scale(before)} cy={8} r={4} fill="var(--sheet)" stroke="var(--graphite)" strokeWidth={1.5} />
      <circle cx={scale(after)} cy={8} r={4.5} fill="var(--ink)" />
    </svg>
  );
}

function SampleRows({ incident }: { incident: Incident }) {
  const { columns, rows } = incident.sampleRows;
  const numeric = columns.map((_, j) => rows.every((row) => typeof row.values[j] === "number"));
  return (
    <TableScroll label="Example predictions">
      <table className={`${layout.table} ${styles.samples}`}>
        <thead>
          <tr>
            {columns.map((c, j) => (
              <th key={c} scope="col" className={numeric[j] ? layout.num : undefined}>
                {c}
              </th>
            ))}
            <th scope="col" className={layout.num}>Score</th>
            <th scope="col" className={layout.num}>Predicted</th>
            <th scope="col" className={layout.num}>Actual</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} data-wrong={row.outcome !== null && row.outcome !== row.prediction}>
              {row.values.map((v, j) => (
                <td key={columns[j] ?? j} className={typeof v === "number" ? layout.num : layout.data}>
                  {formatCell(v)}
                </td>
              ))}
              <td className={layout.num}>{decimal(row.score, 3)}</td>
              <td className={layout.num}>{row.prediction}</td>
              <td className={layout.num}>{row.outcome === null ? "Not yet known" : row.outcome}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={layout.sectionNote}>Rows where the prediction was wrong are marked in the margin.</p>
    </TableScroll>
  );
}

function formatCell(value: string | number | boolean | null): string {
  if (value === null) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? count(value) : decimal(value, 3);
  return String(value);
}
