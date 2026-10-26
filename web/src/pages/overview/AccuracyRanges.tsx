import { Link } from "react-router";
import { scaleLinear } from "d3-scale";
import { GLYPH_PAD, RangeGlyph } from "../../components/RangeGlyph";
import { StatusMark } from "../../components/StatusMark";
import type { ModelSummary } from "../../data/schema";
import { percent } from "../../lib/format";
import { useElementWidth } from "../../lib/useElementWidth";
import styles from "./Overview.module.css";

/** Every model's estimate today, with its likely range, against its reference: a forest plot. */
export function AccuracyRanges({ models }: { models: ModelSummary[] }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(600);
  const glyph = Math.max(width - 290, 120);
  const domain = accuracyDomain(models);
  return (
    <div ref={ref}>
      <ul className={styles.ranges}>
        {models.map((m) => (
          <li key={m.id} className={styles.rangeRow}>
            <span className={styles.rangeName}>
              <StatusMark status={m.status} compact />
              <Link to={`/models/${m.id}`}>{m.name}</Link>
            </span>
            <span className={styles.rangeValue}>{percent(m.estimate.value)}</span>
            <RangeGlyph
              value={m.estimate.value}
              lower={m.estimate.lower}
              upper={m.estimate.upper}
              reference={m.referenceAccuracy}
              measured={m.measured.value}
              domain={domain}
              width={glyph}
              height={22}
              label={m.name}
            />
          </li>
        ))}
      </ul>
      <div className={styles.rangeAxis}>
        <Axis domain={domain} width={glyph} />
      </div>
    </div>
  );
}

/** A shared axis wide enough for every range, reference and measurement, in 5-point steps. */
export function accuracyDomain(models: ModelSummary[]): [number, number] {
  const values = models.flatMap((m) => [
    m.estimate.lower,
    m.estimate.upper,
    m.referenceAccuracy,
    ...(m.measured.value === null ? [] : [m.measured.value]),
  ]);
  if (values.length === 0) return [0.5, 1];
  const lo = Math.floor((Math.min(...values) - 0.01) * 20) / 20;
  const hi = Math.ceil((Math.max(...values) + 0.01) * 20) / 20;
  return [Math.max(0, lo), Math.min(1, hi)];
}

function Axis({ domain, width }: { domain: [number, number]; width: number }) {
  const x = scaleLinear().domain(domain).range([GLYPH_PAD, width - GLYPH_PAD]);
  const ticks = x.ticks(Math.max(2, Math.floor(width / 70)));
  return (
    <svg width={width} height={18} aria-hidden="true">
      {ticks.map((t) => (
        <text key={t} x={x(t)} y={13} textAnchor="middle" className={styles.axisTick}>
          {percent(t, 0)}
        </text>
      ))}
    </svg>
  );
}
