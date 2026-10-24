import { useState } from "react";
import { useParams } from "react-router";
import { AccuracyChart, MIN_COVERAGE_FOR_MEASURED } from "../charts/AccuracyChart";
import { LabelCheckChart } from "../charts/LabelCheckChart";
import { Legend } from "../components/Legend";
import { QueryState } from "../components/QueryState";
import { RangeGlyph } from "../components/RangeGlyph";
import { useModel } from "../data/api";
import type { Day, MetricName, Model } from "../data/schema";
import { count, decimal, longDate, percent, percentRange, shortDate } from "../lib/format";
import { ModelHeader } from "./ModelHeader";
import styles from "./ModelPage.module.css";
import layout from "./layout.module.css";
import { TableScroll } from "../components/TableScroll";

const METRICS: { value: MetricName; label: string }[] = [
  { value: "accuracy", label: "Accuracy" },
  { value: "precision", label: "Precision" },
  { value: "recall", label: "Recall" },
  { value: "f1", label: "F1" },
];

export function ModelPage() {
  const { modelId = "" } = useParams();
  const model = useModel(modelId);
  return (
    <QueryState query={model} subject="this model">
      {(data) => <ModelPerformance model={data} />}
    </QueryState>
  );
}

function ModelPerformance({ model }: { model: Model }) {
  const [metric, setMetric] = useState<MetricName>("accuracy");
  const metricLabel = METRICS.find((m) => m.value === metric)?.label ?? "Accuracy";
  const latest = model.days.at(-1);
  const lastMeasured = latestTrustworthy(model.days);
  const reference = model.referenceMetrics[metric];
  if (!latest) return null;
  const estimate = latest.estimate[metric];

  return (
    <div className={layout.page}>
      <ModelHeader model={model} />

      <section className={styles.reading} aria-label={`Current ${metricLabel.toLowerCase()}`}>
        <div className={styles.primary}>
          <p className={styles.readingLabel}>Estimated {metricLabel.toLowerCase()}, {shortDate(latest.date)}</p>
          <p className={styles.readingValue}>{percent(estimate.value)}</p>
          <p className={styles.readingRange}>Likely {percentRange(estimate.lower, estimate.upper)}</p>
          {estimate.value !== null && estimate.lower !== null && estimate.upper !== null && (
            <RangeGlyph
              value={estimate.value}
              lower={estimate.lower}
              upper={estimate.upper}
              {...(reference === null ? {} : { reference })}
              measured={lastMeasured?.measured?.[metric] ?? null}
              domain={[
                Math.max(0, Math.min(estimate.lower, reference ?? 1) - 0.06),
                Math.min(1, Math.max(estimate.upper, reference ?? 0) + 0.06),
              ]}
              width={300}
              height={26}
              label={`Estimated ${metricLabel.toLowerCase()}`}
            />
          )}
        </div>
        <dl className={styles.facts}>
          <div>
            <dt>Measured from labels</dt>
            <dd>
              {lastMeasured ? (
                <>
                  <strong>{percent(lastMeasured.measured?.[metric])}</strong> on{" "}
                  {shortDate(lastMeasured.date)}, the latest day with at least half its labels in
                </>
              ) : (
                "No day has half its labels yet"
              )}
            </dd>
          </div>
          <div>
            <dt>Reference</dt>
            <dd>
              <strong>{percent(reference)}</strong> on {count(model.referenceRows)} labelled rows the
              model was checked against before release
            </dd>
          </div>
          <div>
            <dt>Labels in for today's predictions</dt>
            <dd>
              <strong>{percent(latest.labelCoverage, 0)}</strong> of {count(latest.rows)} predictions
            </dd>
          </div>
        </dl>
      </section>

      <section className={layout.section} aria-labelledby="trend-heading">
        <div className={layout.sectionHead}>
          <h2 id="trend-heading">Last {model.days.length} days</h2>
          <fieldset className={styles.metrics}>
            <legend className="visually-hidden">Metric</legend>
            {METRICS.map((m) => (
              <label key={m.value}>
                <input
                  type="radio"
                  name="metric"
                  value={m.value}
                  checked={metric === m.value}
                  onChange={() => setMetric(m.value)}
                />
                <span>{m.label}</span>
              </label>
            ))}
          </fieldset>
        </div>
        <Legend items={["band", "ring", "reference"]} />
        <AccuracyChart days={model.days} metric={metric} reference={reference} label={metricLabel} />
        <p className={layout.sectionNote}>
          Measured {metricLabel.toLowerCase()} appears once {percent(MIN_COVERAGE_FOR_MEASURED, 0)} of a
          day's labels are in; earlier figures swing too much to trust.{" "}
          {calibrationNote(model)}
        </p>
        <details className={layout.details}>
          <summary>Show these values as a table</summary>
          <DaysTable days={model.days} metric={metric} />
        </details>
      </section>

      <section className={layout.section} aria-labelledby="check-heading">
        <h2 id="check-heading">Check against labels</h2>
        <p className={layout.meta}>
          Each point pools a week of labelled predictions, enough to see a gap of two or three points
          that a single day can't. If measured accuracy leaves the expected range two days running,
          the model's confidence no longer matches outcomes: what decides the outcome has changed, or
          the model is seeing inputs unlike anything it learned from.
        </p>
        <Legend
          items={["band", "ring", "flag"]}
          labels={{
            band: "Expected from the model's confidence",
            ring: "Measured, previous 7 days",
            flag: "Measured outside the expected range",
          }}
        />
        <LabelCheckChart days={model.days} />
      </section>
    </div>
  );
}

function calibrationNote(model: Model): string {
  const { applied, eceBefore, eceAfter } = model.calibration;
  return applied
    ? `The model's scores were recalibrated before estimating, because they were overconfident (calibration error ${decimal(eceBefore, 3)}, ${decimal(eceAfter, 3)} after).`
    : `The model's scores were already well calibrated (calibration error ${decimal(eceBefore, 3)}), so they are used as they are.`;
}

/** Latest day with at least half its labels in: recent enough to matter, full enough to trust. */
export function latestTrustworthy(days: Day[]): Day | undefined {
  return [...days].reverse().find((d) => d.measured !== null && d.labelCoverage >= 0.5);
}

function DaysTable({ days, metric }: { days: Day[]; metric: MetricName }) {
  return (
    <TableScroll label="Daily values">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col" className={layout.num}>Estimated</th>
            <th scope="col" className={layout.num}>Likely range</th>
            <th scope="col" className={layout.num}>Measured</th>
            <th scope="col" className={layout.num}>Labels in</th>
            <th scope="col" className={layout.num}>Predictions</th>
          </tr>
        </thead>
        <tbody>
          {[...days].reverse().map((d) => (
            <tr key={d.date}>
              <td className={layout.data}>{longDate(d.date)}</td>
              <td className={layout.num}>{percent(d.estimate[metric].value)}</td>
              <td className={layout.num}>
                {percentRange(d.estimate[metric].lower, d.estimate[metric].upper)}
              </td>
              <td className={layout.num}>{percent(d.measured?.[metric])}</td>
              <td className={layout.num}>{percent(d.labelCoverage, 0)}</td>
              <td className={layout.num}>{count(d.rows)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
