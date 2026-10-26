import { useState } from "react";
import { AccuracyChart, MIN_COVERAGE_FOR_MEASURED } from "../../charts/AccuracyChart";
import { LabelCheckChart } from "../../charts/LabelCheckChart";
import { Legend } from "../../components/Legend";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import type { Day, MetricName, Model } from "../../data/schema";
import { csvName } from "../../lib/csv";
import { count, decimal, longDate, percent, percentRange, points, shortDate } from "../../lib/format";
import layout from "../layout.module.css";
import styles from "./Model.module.css";

const METRICS: { value: MetricName; label: string }[] = [
  { value: "accuracy", label: "Accuracy" },
  { value: "precision", label: "Precision" },
  { value: "recall", label: "Recall" },
  { value: "f1", label: "F1" },
];

/** Latest day with at least half its labels in: recent enough to matter, full enough to trust. */
export function latestTrustworthy(days: readonly Day[]): Day | undefined {
  return [...days].reverse().find((d) => d.measured !== null && d.labelCoverage >= 0.5);
}

interface Props {
  model: Model;
  days: Day[];
  compare?: Day[] | undefined;
  onSelectRange: (from: string, to: string) => void;
}

export function PerformanceTab({ model, days, compare, onSelectRange }: Props) {
  const [metric, setMetric] = useState<MetricName>("accuracy");
  const label = METRICS.find((m) => m.value === metric)?.label ?? "Accuracy";
  const lower = label.toLowerCase();
  const latest = days.at(-1);
  if (!latest) return null;
  const reference = model.referenceMetrics[metric];
  const estimate = latest.estimate[metric];
  const measured = latestTrustworthy(days);
  const span = `${shortDate(days[0]?.date ?? latest.date)} to ${shortDate(latest.date)}`;
  const checks = days.filter((d) => d.labelCheck !== null);

  return (
    <>
      <dl className={styles.stats}>
        <div>
          <dt>Estimated {lower}, {shortDate(latest.date)}</dt>
          <dd>
            <span className={styles.statValue}>{percent(estimate.value)}</span>
            <span className={styles.statNote}>Likely {percentRange(estimate.lower, estimate.upper)}</span>
          </dd>
        </div>
        <div>
          <dt>Reference</dt>
          <dd>
            <span className={styles.statValue}>{percent(reference)}</span>
            <span className={styles.statNote}>
              {estimate.value !== null && reference !== null
                ? `${points(estimate.value - reference)} today`
                : `${count(model.referenceRows)} labelled rows`}
            </span>
          </dd>
        </div>
        <div>
          <dt>Last measured</dt>
          <dd>
            <span className={styles.statValue}>{percent(measured?.measured?.[metric])}</span>
            <span className={styles.statNote}>
              {measured ? `${shortDate(measured.date)}, half its labels in` : "No day half labelled yet"}
            </span>
          </dd>
        </div>
        <div>
          <dt>Labels in, {shortDate(latest.date)}</dt>
          <dd>
            <span className={styles.statValue}>{percent(latest.labelCoverage, 0)}</span>
            <span className={styles.statNote}>
              of {count(latest.rows)}; full within {model.labelDelayDays} days
            </span>
          </dd>
        </div>
      </dl>

      <div className={layout.grid}>
        <Tile
          title={`Estimated ${lower}`}
          note={`${span}. Drag across the chart to zoom into those dates.`}
          controls={
            <div className={styles.segmented} role="group" aria-label="Metric">
              {METRICS.map((m) => (
                <button
                  key={m.value}
                  type="button"
                  aria-pressed={metric === m.value}
                  onClick={() => setMetric(m.value)}
                >
                  {m.label}
                </button>
              ))}
            </div>
          }
          table={() => <DaysTable days={days} metric={metric} />}
          csv={() => ({
            name: csvName(model.id, metric, days[0]?.date ?? "", latest.date),
            rows: days.map((d) => ({
              date: d.date,
              estimate: d.estimate[metric].value,
              lower: d.estimate[metric].lower,
              upper: d.estimate[metric].upper,
              measured: d.measured?.[metric] ?? null,
              label_coverage: d.labelCoverage,
              predictions: d.rows,
            })),
          })}
        >
          <Legend items={compare ? ["band", "ring", "reference", "previous"] : ["band", "ring", "reference"]} />
          <AccuracyChart
            days={days}
            metric={metric}
            reference={reference}
            label={label}
            compare={compare}
            onSelectRange={onSelectRange}
          />
          <p className={styles.note}>
            Measured {lower} is drawn once {percent(MIN_COVERAGE_FOR_MEASURED, 0)} of a day's labels are in.{" "}
            {calibrationNote(model)}
          </p>
        </Tile>

        <Tile
          title="Check against labels"
          note="Measured accuracy over the previous 7 days, against what the model's confidence predicted for the same rows."
          table={() => <ChecksTable days={checks} />}
          csv={() => ({
            name: csvName(model.id, "label-check", days[0]?.date ?? "", latest.date),
            rows: checks.map((d) => ({
              date: d.date,
              expected: d.labelCheck?.estimated,
              lower: d.labelCheck?.lower,
              upper: d.labelCheck?.upper,
              measured: d.labelCheck?.measured,
              labelled: d.labelCheck?.labelled,
              below_range: d.conceptFlag,
            })),
          })}
        >
          {checks.length === 0 ? (
            <p className={layout.empty}>Not enough labels in these dates for a check.</p>
          ) : (
            <>
              <Legend
                items={["band", "ring", "flag"]}
                labels={{
                  band: "Expected from confidence",
                  ring: "Measured, previous 7 days",
                  flag: "Measured below the range",
                }}
              />
              <LabelCheckChart days={days} />
              <p className={styles.note}>
                Two days running below the range opens a concept drift incident: outcomes no longer
                follow the model's confidence. Measured above the range is not flagged.
              </p>
            </>
          )}
        </Tile>
      </div>
    </>
  );
}

function calibrationNote(model: Model): string {
  const { applied, eceBefore, eceAfter } = model.calibration;
  return applied
    ? `Scores were recalibrated before estimating (calibration error ${decimal(eceBefore, 3)} before, ${decimal(eceAfter, 3)} after).`
    : `Scores were already calibrated (error ${decimal(eceBefore, 3)}) and are used as they are.`;
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
              <th scope="row">{longDate(d.date)}</th>
              <td className={layout.num}>{percent(d.estimate[metric].value)}</td>
              <td className={layout.num}>{percentRange(d.estimate[metric].lower, d.estimate[metric].upper)}</td>
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

function checkResult(measured: number, lower: number, upper: number): string {
  if (measured < lower) return "Below range";
  if (measured > upper) return "Above range, not flagged";
  return "Within range";
}

function ChecksTable({ days }: { days: Day[] }) {
  return (
    <TableScroll label="Label checks">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col" className={layout.num}>Expected</th>
            <th scope="col" className={layout.num}>Range</th>
            <th scope="col" className={layout.num}>Measured</th>
            <th scope="col" className={layout.num}>Labelled rows</th>
            <th scope="col">Result</th>
          </tr>
        </thead>
        <tbody>
          {[...days].reverse().map((d) =>
            d.labelCheck ? (
              <tr key={d.date}>
                <th scope="row">{longDate(d.date)}</th>
                <td className={layout.num}>{percent(d.labelCheck.estimated)}</td>
                <td className={layout.num}>{percentRange(d.labelCheck.lower, d.labelCheck.upper)}</td>
                <td className={layout.num}>{percent(d.labelCheck.measured)}</td>
                <td className={layout.num}>{count(d.labelCheck.labelled)}</td>
                <td>{checkResult(d.labelCheck.measured, d.labelCheck.lower, d.labelCheck.upper)}</td>
              </tr>
            ) : null,
          )}
        </tbody>
      </table>
    </TableScroll>
  );
}
