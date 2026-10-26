import { Link, useParams } from "react-router";
import { AccuracyChart } from "../../charts/AccuracyChart";
import { BridgeChart } from "../../charts/BridgeChart";
import { DailyChart } from "../../charts/DailyChart";
import { Legend } from "../../components/Legend";
import { QueryState } from "../../components/QueryState";
import { StatusMark } from "../../components/StatusMark";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import { useFleet, useIncident, useModel } from "../../data/api";
import type { Finding, Incident, Model, SignalKind } from "../../data/schema";
import { addDays } from "../../filters/filters";
import { csvName } from "../../lib/csv";
import { conditionText, METHOD_LABELS, summarize } from "../../lib/describe";
import { ago, count, daysBetween, decimal, percent, points, pValue, shortDate } from "../../lib/format";
import { useTitle } from "../../lib/useTitle";
import layout from "../layout.module.css";
import modelStyles from "../model/Model.module.css";
import styles from "./IncidentPage.module.css";

export const SIGNAL_RULES: Record<SignalKind, string> = {
  estimate_drop: "The top of the estimate's likely range fell below reference accuracy two days in a row.",
  concept_drift: "Measured accuracy over the past 7 days fell below the estimate's range two days in a row.",
  data_quality: "A feature's share of missing values rose more than 5 points above its reference two days in a row.",
  multivariate: "Reconstruction error left its expected range two days in a row.",
  input_drift: "Two or more features drifted two days in a row.",
};

/** Days of history shown before an incident opened, for context. */
const LEAD_IN_DAYS = 21;

export function IncidentPage() {
  const { incidentId = "" } = useParams();
  useTitle(`Incident ${incidentId}`);
  const incident = useIncident(incidentId);
  return (
    <QueryState query={incident} subject="this incident">
      {(data) => <IncidentView incident={data} />}
    </QueryState>
  );
}

function IncidentView({ incident }: { incident: Incident }) {
  const fleet = useFleet();
  const model = useModel(incident.modelId);
  const today = fleet.data?.today ?? incident.window.to;
  const summary = fleet.data?.models.find((m) => m.id === incident.modelId);
  const { metric } = incident;
  const top = incident.findings[0];
  const open = incident.status === "open";
  const lasted = daysBetween(incident.openedOn, incident.resolvedOn ?? today);

  return (
    <div className={layout.page}>
      <header className={layout.header}>
        <nav aria-label="Breadcrumb" className={layout.crumbs}>
          <Link to="/incidents">Incidents</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">{incident.id}</span>
        </nav>
        <div className={layout.titleRow}>
          <h1 className={layout.title}>{incident.title}</h1>
          <StatusMark status={incident.severity} />
          <span className={styles.state} data-open={open}>
            {open ? "Open" : "Resolved"}
          </span>
        </div>
        <p className={layout.meta}>
          <Link to={`/models/${incident.modelId}`}>{summary?.name ?? incident.modelId}</Link>
          {summary && ` ${summary.version}, ${summary.team} team`}. Opened {shortDate(incident.openedOn)} (
          {ago(incident.openedOn, today)})
          {incident.resolvedOn ? `, resolved ${shortDate(incident.resolvedOn)} after ${lasted} days` : ""}.
        </p>
        <p className={layout.lead}>{summarize(incident)}</p>
      </header>

      <dl className={modelStyles.stats}>
        <div>
          <dt>{metric.basis === "measured" ? "Measured" : "Estimated"} accuracy</dt>
          <dd>
            <span className={modelStyles.statValue}>{percent(metric.current)}</span>
            <span className={modelStyles.statNote}>
              {shortDate(incident.window.from)} to {shortDate(incident.window.to)}
            </span>
          </dd>
        </div>
        <div>
          <dt>Reference</dt>
          <dd>
            <span className={modelStyles.statValue}>{percent(metric.reference)}</span>
            <span className={modelStyles.statNote}>{points(metric.current - metric.reference)} since</span>
          </dd>
        </div>
        <div>
          <dt>Predictions analysed</dt>
          <dd>
            <span className={modelStyles.statValue}>{count(incident.window.rows)}</span>
            <span className={modelStyles.statNote}>
              {metric.basis === "measured" ? "with labels" : "labels not needed"}
            </span>
          </dd>
        </div>
        <div>
          <dt>{open ? "Open for" : "Lasted"}</dt>
          <dd>
            <span className={modelStyles.statValue}>
              {lasted} {lasted === 1 ? "day" : "days"}
            </span>
            <span className={modelStyles.statNote}>
              {open ? "resolves after 7 quiet days" : `quiet since ${shortDate(incident.resolvedOn ?? "")}`}
            </span>
          </dd>
        </div>
      </dl>

      <div className={layout.grid}>
        {model.data && <Context model={model.data} incident={incident} today={today} />}

        <Tile span={metric.performanceEffect !== null ? 5 : 12} title="What fired" note="In the order the checks failed.">
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
                  <p className={styles.rule}>{SIGNAL_RULES[s.kind]}</p>
                </div>
              </li>
            ))}
          </ol>
        </Tile>

        {metric.performanceEffect !== null && metric.mixEffect !== null && (
          <Tile
            span={7}
            title="Where the change comes from"
            note={`${metric.basis === "measured" ? "Measured" : "Estimated"} accuracy, split by ${
              metric.partition.join(" and ") || "segment"
            }: worse within segments, or more traffic from segments that were always harder.`}
            csv={() => ({
              name: csvName(incident.id, "bridge"),
              rows: [
                { step: "reference", value: metric.reference },
                { step: "within_segments", value: metric.performanceEffect },
                { step: "traffic_mix", value: metric.mixEffect },
                { step: "current", value: metric.current },
              ],
            })}
          >
            <BridgeChart
              reference={metric.reference}
              performanceEffect={metric.performanceEffect}
              mixEffect={metric.mixEffect}
              current={metric.current}
              basis={metric.basis}
            />
          </Tile>
        )}

        {incident.missingFeatures.length > 0 && (
          <Tile title="Missing values" note="Share of rows arriving without a value, during the incident window.">
            <TableScroll label="Missing values">
              <table className={layout.table}>
                <thead>
                  <tr>
                    <th scope="col">Feature</th>
                    <th scope="col" className={layout.num}>Reference</th>
                    <th scope="col" className={layout.num}>During incident</th>
                    <th scope="col" className={layout.num}>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {incident.missingFeatures.map((f) => (
                    <tr key={f.name}>
                      <th scope="row">{f.name}</th>
                      <td className={layout.num}>{percent(f.referenceNullRate, 1)}</td>
                      <td className={layout.num}>{percent(f.nullRate, 1)}</td>
                      <td className={layout.num}>{points(f.nullRate - f.referenceNullRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </Tile>
        )}

        <Tile
          title={incident.findings.length > 0 ? "Segments that cost the most" : "Traffic shifts"}
          csv={() =>
            incident.findings.length > 0
              ? {
                  name: csvName(incident.id, "segments"),
                  rows: incident.findings.map((f) => ({
                    segment: f.conditions.map((c) => `${c.feature}=${c.value}`).join(" & "),
                    predictions: f.nCurrent,
                    accuracy_before: f.metricReference,
                    accuracy_now: f.metricCurrent,
                    cost: f.contribution,
                  })),
                }
              : {
                  name: csvName(incident.id, "traffic-shifts"),
                  rows: incident.mixShifts.map((m) => ({ ...m })),
                }
          }
        >
          {incident.findings.length > 0 ? (
            <Findings findings={incident.findings} basis={metric.basis} total={metric.current - metric.reference} />
          ) : (
            <MixShifts incident={incident} />
          )}
        </Tile>

        {incident.correlationChanges.length > 0 && (
          <Tile span={6} title="Relationships that changed most" note="Pearson correlation between feature pairs.">
            <TableScroll label="Relationships that changed">
              <table className={layout.table}>
                <thead>
                  <tr>
                    <th scope="col">Features</th>
                    <th scope="col" className={layout.num}>Reference</th>
                    <th scope="col" className={layout.num}>Now</th>
                    <th scope="col" className={layout.num}>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {incident.correlationChanges.map((c) => (
                    <tr key={`${c.a}-${c.b}`}>
                      <th scope="row">
                        {c.a} and {c.b}
                      </th>
                      <td className={layout.num}>{decimal(c.reference)}</td>
                      <td className={layout.num}>{decimal(c.current)}</td>
                      <td className={layout.num}>{decimal(c.current - c.reference)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </Tile>
        )}

        {incident.driftedFeatures.length > 0 && (
          <Tile
            span={incident.correlationChanges.length > 0 ? 6 : 12}
            title="Features that drifted"
            controls={
              <Link to={`/models/${incident.modelId}?tab=inputs`} className={styles.more}>
                All inputs
              </Link>
            }
          >
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
                      <th scope="row">
                        <Link to={`/models/${incident.modelId}?tab=inputs&feature=${encodeURIComponent(f.name)}`}>{f.name}</Link>
                      </th>
                      <td>{METHOD_LABELS[f.method]}</td>
                      <td className={layout.num}>{f.isPValue ? pValue(f.statistic) : decimal(f.statistic, 3)}</td>
                      <td className={layout.num}>{f.isPValue ? `p < ${f.threshold}` : `≥ ${decimal(f.threshold, 2)}`}</td>
                      <td className={layout.num}>{decimal(f.psi, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          </Tile>
        )}

        {top && incident.sampleRows.rows.length > 0 && (
          <Tile
            title="Example predictions"
            note={`From the top segment, where ${top.conditions.map((c) => conditionText(c.feature, c.value)).join(" and ")}. Wrong predictions are marked in the margin.`}
            csv={() => ({
              name: csvName(incident.id, "examples"),
              rows: incident.sampleRows.rows.map((r) => ({
                ...Object.fromEntries(incident.sampleRows.columns.map((c, j) => [c, r.values[j] ?? null])),
                score: r.score,
                prediction: r.prediction,
                outcome: r.outcome,
              })),
            })}
          >
            <SampleRows incident={incident} />
          </Tile>
        )}
      </div>
    </div>
  );
}

/** The model's accuracy from three weeks before the incident to its end, and missing values if relevant. */
function Context({ model, incident, today }: { model: Model; incident: Incident; today: string }) {
  const from = addDays(incident.openedOn, -LEAD_IN_DAYS);
  const to = incident.resolvedOn ? addDays(incident.resolvedOn, 7) : today;
  const days = model.days.filter((d) => d.date >= from && d.date <= to);
  const missing = incident.missingFeatures.slice(0, 4);
  if (days.length === 0) return null;
  const span = `${shortDate(days[0]?.date ?? from)} to ${shortDate(days.at(-1)?.date ?? to)}`;
  return (
    <>
      <Tile
        span={missing.length > 0 ? 7 : 12}
        title="Accuracy around the incident"
        note={`${span}. Opened ${shortDate(incident.openedOn)}${incident.resolvedOn ? `, resolved ${shortDate(incident.resolvedOn)}` : ""}.`}
        controls={
          <Link to={`/models/${model.id}?from=${days[0]?.date ?? from}&to=${days.at(-1)?.date ?? to}`} className={styles.more}>
            Open model
          </Link>
        }
      >
        <Legend items={["band", "ring", "reference"]} />
        <AccuracyChart
          days={days}
          metric="accuracy"
          reference={model.referenceMetrics.accuracy}
          label="Accuracy"
          markers={[
            { date: incident.openedOn, label: "Opened" },
            ...(incident.resolvedOn ? [{ date: incident.resolvedOn, label: "Resolved" }] : []),
          ]}
        />
      </Tile>
      {missing.length > 0 && (
        <Tile span={5} title="Missing values by day" note={span}>
          <DailyChart
            kind="line"
            zero
            height={390}
            dates={days.map((d) => d.date)}
            format={(v) => percent(v, 0)}
            label={`Missing values by day, ${span}`}
            series={missing.map((f, i) => ({
              id: f.name,
              label: f.name,
              slot: i + 1,
              values: days.map((d) => d.dataQuality[f.name]?.nullRate ?? null),
            }))}
          />
        </Tile>
      )}
    </>
  );
}

function Findings({ findings, basis, total }: { findings: Finding[]; basis: "estimated" | "measured"; total: number }) {
  const largest = Math.max(...findings.map((f) => Math.abs(f.contribution)), 1e-6);
  return (
    <>
      <p className={styles.explain}>
        Ranked by points of {basis} accuracy each segment cost overall (its change weighted by its share
        of traffic), against a total change of {points(total)}. Only segments clearly worse than average
        are listed. Segments overlap, so their costs don't add up.
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
                  <th scope="row">
                    <ul className={styles.conditions}>
                      {f.conditions.map((c) => (
                        <li key={c.feature}>{conditionText(c.feature, c.value)}</li>
                      ))}
                    </ul>
                  </th>
                  <td className={layout.num}>{count(f.nCurrent)}</td>
                  <td className={layout.num}>{percent(f.metricReference)}</td>
                  <td className={layout.num}>{percent(f.metricCurrent)}</td>
                  <td className={layout.num}>{points(f.metricCurrent - f.metricReference)}</td>
                  <td>
                    <div className={styles.share}>
                      <span className={styles.shareBar} style={{ width: `${(Math.abs(f.contribution) / largest) * 120}px` }} />
                      <span>{points(f.contribution)}</span>
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
      <p className={styles.explain}>{mixText(incident)}</p>
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
                <th scope="row">{conditionText(m.feature, m.value)}</th>
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

function mixText(incident: Incident): string {
  if (incident.kind === "data_quality") {
    return "Rows without a value count as their own segment. The shares show how much traffic moved into it.";
  }
  if (incident.metric.current < incident.metric.reference) {
    return "No segment stands out: every part of the traffic got worse by about the same amount. That points to a broad change in what the model is asked to score.";
  }
  return "No segment got clearly worse. These are the largest changes in where traffic comes from.";
}

function MixBar({ before, after }: { before: number; after: number }) {
  const width = 160;
  const scale = (v: number) => Math.min(v, 1) * width;
  return (
    <svg width={width} height={16} aria-label={`${percent(before, 0)} to ${percent(after, 0)}`} role="img">
      <line x1={0} x2={width} y1={8} y2={8} stroke="var(--line)" />
      <line x1={scale(before)} x2={scale(after)} y1={8} y2={8} stroke="var(--ink)" strokeWidth={2} />
      <circle cx={scale(before)} cy={8} r={4} fill="var(--panel)" stroke="var(--muted)" strokeWidth={1.5} />
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
                <td key={columns[j] ?? j} className={typeof v === "number" ? layout.num : undefined}>
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
    </TableScroll>
  );
}

function formatCell(value: string | number | boolean | null): string {
  if (value === null) return "–";
  if (typeof value === "number") return Number.isInteger(value) ? count(value) : decimal(value, 3);
  return String(value);
}
