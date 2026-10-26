import { Sparkline } from "../../charts/Sparkline";
import type { DateRange } from "../../filters/filters";
import { change, type FleetKpis, type Kpi } from "../../lib/fleetStats";
import { compact, percent, points } from "../../lib/format";
import styles from "./Overview.module.css";

interface Card {
  label: string;
  kpi: Kpi;
  format: (v: number | null) => string;
  formatChange: (v: number) => string;
  note: string;
  /** Some figures can't be compared across periods (older days have had longer to collect). */
  comparable?: boolean;
}

/** The headline figures for the selected period, each against the period before it. */
export function Kpis({
  kpis,
  open,
  range,
}: {
  kpis: FleetKpis;
  open: { critical: number; warning: number };
  range: DateRange;
}) {
  const period = `previous ${range.days} days`;
  const cards: Card[] = [
    {
      label: "Predictions",
      kpi: kpis.predictions,
      format: (v) => (v === null ? "—" : compact(v)),
      formatChange: (d) => `${d >= 0 ? "+" : "−"}${compact(Math.abs(d))} vs ${period}`,
      note: "scored in the period",
    },
    {
      label: "Accuracy against reference",
      kpi: kpis.gap,
      format: (v) => points(v),
      formatChange: (d) => `${points(d)} vs ${period}`,
      note: "estimated, traffic-weighted",
    },
    {
      label: "Labels received",
      kpi: kpis.labelCoverage,
      format: (v) => percent(v, 0),
      formatChange: (d) => `${points(d)} vs ${period}`,
      note: "so far; older days keep collecting",
      comparable: false,
    },
    {
      label: "p95 latency",
      kpi: kpis.p95LatencyMs,
      format: (v) => (v === null ? "—" : `${Math.round(v)} ms`),
      formatChange: (d) => `${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} ms vs ${period}`,
      note: "traffic-weighted",
    },
    {
      label: "Model-days with drift",
      kpi: kpis.driftDays,
      format: (v) => (v === null ? "—" : String(v)),
      formatChange: (d) => `${d >= 0 ? "+" : "−"}${Math.abs(d)} vs ${period}`,
      note: "inputs, relationships or missing values",
    },
  ];

  return (
    <ul className={styles.kpis} aria-label="Key figures">
      {cards.map((c) => {
        const d = c.comparable === false ? null : change(c.kpi);
        return (
          <li key={c.label} className={styles.kpi}>
            <p className={styles.kpiLabel}>{c.label}</p>
            <p className={styles.kpiValue}>{c.format(c.kpi.value)}</p>
            <p className={styles.kpiChange}>{d === null ? c.note : c.formatChange(d)}</p>
            <div className={styles.kpiSpark}>
              <Sparkline values={c.kpi.series} label={`${c.label}, daily`} />
            </div>
          </li>
        );
      })}
      <li className={styles.kpi}>
        <p className={styles.kpiLabel}>Open incidents</p>
        <p className={styles.kpiValue}>{open.critical + open.warning}</p>
        <p className={styles.kpiChange}>
          {open.critical} critical, {open.warning} warning
        </p>
      </li>
    </ul>
  );
}
