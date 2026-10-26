import { DailyChart } from "../../charts/DailyChart";
import { TableScroll } from "../../components/TableScroll";
import { Tile } from "../../components/Tile";
import type { Day, Model } from "../../data/schema";
import { csvName } from "../../lib/csv";
import { compact, count, longDate, percent, shortDate } from "../../lib/format";
import layout from "../layout.module.css";
import styles from "./Model.module.css";

function change(now: number, before: number | undefined): string {
  if (before === undefined || before === 0) return "No previous period";
  const pct = (now - before) / before;
  return `${pct >= 0 ? "+" : "−"}${percent(Math.abs(pct), 1)} on previous period`;
}

/** The previous period aligned to the end of the current one, day by day. */
function aligned(dates: readonly string[], previous: readonly Day[] | undefined, value: (d: Day) => number) {
  if (!previous) return undefined;
  const offset = previous.length - dates.length;
  return dates.map((_, i) => {
    const d = previous[i + offset];
    return d ? value(d) : null;
  });
}

export function TrafficTab({ model, days, previous }: { model: Model; days: Day[]; previous?: Day[] | undefined }) {
  const dates = days.map((d) => d.date);
  const total = days.reduce((s, d) => s + d.rows, 0);
  const totalBefore = previous?.reduce((s, d) => s + d.rows, 0);
  const peak = days.reduce((best, d) => (d.p95LatencyMs > best.p95LatencyMs ? d : best), days[0] as Day);
  const labelled = days.reduce((s, d) => s + d.rows * d.labelCoverage, 0);
  const span = `${shortDate(dates[0] ?? "")} to ${shortDate(dates.at(-1) ?? "")}`;
  const csv = () => ({
    name: csvName(model.id, "traffic", dates[0] ?? "", dates.at(-1) ?? ""),
    rows: days.map((d) => ({
      date: d.date,
      predictions: d.rows,
      p95_latency_ms: d.p95LatencyMs,
      label_coverage: d.labelCoverage,
    })),
  });
  const table = () => (
    <TableScroll label="Traffic by day">
      <table className={layout.table}>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col" className={layout.num}>Predictions</th>
            <th scope="col" className={layout.num}>p95 latency</th>
            <th scope="col" className={layout.num}>Labels in</th>
          </tr>
        </thead>
        <tbody>
          {[...days].reverse().map((d) => (
            <tr key={d.date}>
              <th scope="row">{longDate(d.date)}</th>
              <td className={layout.num}>{count(d.rows)}</td>
              <td className={layout.num}>{Math.round(d.p95LatencyMs)} ms</td>
              <td className={layout.num}>{percent(d.labelCoverage, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );

  return (
    <>
      <dl className={styles.stats}>
        <div>
          <dt>Predictions</dt>
          <dd>
            <span className={styles.statValue}>{compact(total)}</span>
            <span className={styles.statNote}>{previous ? change(total, totalBefore) : span}</span>
          </dd>
        </div>
        <div>
          <dt>Per day</dt>
          <dd>
            <span className={styles.statValue}>{count(Math.round(total / Math.max(days.length, 1)))}</span>
            <span className={styles.statNote}>average over {days.length} days</span>
          </dd>
        </div>
        <div>
          <dt>Highest p95 latency</dt>
          <dd>
            <span className={styles.statValue}>{Math.round(peak.p95LatencyMs)} ms</span>
            <span className={styles.statNote}>on {shortDate(peak.date)}</span>
          </dd>
        </div>
        <div>
          <dt>Labelled so far</dt>
          <dd>
            <span className={styles.statValue}>{percent(labelled / Math.max(total, 1), 0)}</span>
            <span className={styles.statNote}>recent days are still collecting</span>
          </dd>
        </div>
      </dl>

      <div className={layout.grid}>
        <Tile
          title="Predictions per day"
          note={previous ? `${span}. Dashed: the period before, aligned by day.` : span}
          table={table}
          csv={csv}
        >
          <DailyChart
            kind="bar"
            dates={dates}
            series={[{ id: "rows", label: "Predictions", values: days.map((d) => d.rows) }]}
            compare={aligned(dates, previous, (d) => d.rows)}
            format={(v) => count(Math.round(v))}
            label={`Predictions per day, ${span}`}
          />
        </Tile>
        <Tile span={6} title="p95 latency" note="Milliseconds, 95th percentile of each day's requests." table={table} csv={csv}>
          <DailyChart
            kind="line"
            dates={dates}
            series={[{ id: "latency", label: "p95 latency", values: days.map((d) => d.p95LatencyMs) }]}
            compare={aligned(dates, previous, (d) => d.p95LatencyMs)}
            format={(v) => `${Math.round(v)} ms`}
            label={`p95 latency per day, ${span}`}
          />
        </Tile>
        <Tile
          span={6}
          title="Labels in"
          note={`Share of each day's predictions with an outcome so far. Labels arrive within ${model.labelDelayDays} days.`}
          table={table}
          csv={csv}
        >
          <DailyChart
            kind="line"
            dates={dates}
            zero
            series={[{ id: "coverage", label: "Labels in", values: days.map((d) => d.labelCoverage) }]}
            format={(v) => percent(v, 0)}
            label={`Label coverage per day, ${span}`}
          />
        </Tile>
      </div>
    </>
  );
}
