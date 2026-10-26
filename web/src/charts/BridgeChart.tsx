import { scaleLinear } from "d3-scale";
import { percent, points } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./BridgeChart.module.css";

interface Props {
  reference: number;
  performanceEffect: number;
  mixEffect: number;
  current: number;
  basis: "estimated" | "measured";
}

const NARROW = 560;

/**
 * Waterfall from reference accuracy to current: the part caused by the model doing worse within
 * segments, and the part caused by the traffic mix moving toward harder segments.
 */
export function BridgeChart({ reference, performanceEffect, mixEffect, current, basis }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(720);
  // Wide: label | bar | value on one line. Narrow: label above, then bar and value.
  const narrow = width < NARROW;
  const ROW = narrow ? 62 : 44;
  const LABEL = narrow ? 0 : 210;
  const VALUE = narrow ? 92 : 110;
  const BAR_OFFSET = narrow ? 22 : 0;
  const plot = Math.max(width - LABEL - VALUE, 120);
  const afterPerformance = reference + performanceEffect;
  const all = [reference, afterPerformance, current];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = Math.max((hi - lo) * 0.25, 0.01);
  const x = scaleLinear().domain([lo - pad, hi + pad]).range([0, plot]);

  const rows = [
    { key: "ref", label: "Reference accuracy", from: x.domain()[0] ?? 0, to: reference, total: true, text: percent(reference) },
    {
      key: "perf",
      label: performanceEffect < 0 ? "Worse within segments" : "Better within segments",
      from: reference,
      to: afterPerformance,
      total: false,
      text: points(performanceEffect),
    },
    {
      key: "mix",
      label: "Change in traffic mix",
      from: afterPerformance,
      to: afterPerformance + mixEffect,
      total: false,
      text: points(mixEffect),
    },
    {
      key: "cur",
      label: `${basis === "estimated" ? "Estimated" : "Measured"} accuracy now`,
      from: x.domain()[0] ?? 0,
      to: current,
      total: true,
      text: percent(current),
    },
  ];

  return (
    <div ref={ref} className={styles.frame}>
      <svg
        width={width}
        height={rows.length * ROW + 8}
        role="img"
        aria-label={`From ${percent(reference)} to ${percent(current)}: ${points(performanceEffect)} from accuracy within segments, ${points(mixEffect)} from the traffic mix.`}
      >
        {rows.map((r, i) => {
          const left = x(Math.min(r.from, r.to));
          const barWidth = Math.max(Math.abs(x(r.to) - x(r.from)), 2);
          const yTop = i * ROW + 10;
          const yBar = yTop + BAR_OFFSET;
          return (
            <g key={r.key}>
              <text className={styles.label} x={0} y={yTop + 15}>
                {r.label}
              </text>
              <rect
                className={r.total ? styles.total : styles.delta}
                x={LABEL + left}
                y={yBar}
                width={barWidth}
                height={22}
                rx={2}
              />
              {!r.total && i < rows.length - 1 && (
                <line
                  className={styles.connector}
                  x1={LABEL + x(r.to)}
                  x2={LABEL + x(r.to)}
                  y1={yBar + 22}
                  y2={yBar + ROW}
                />
              )}
              <text className={styles.value} x={LABEL + plot + 12} y={yBar + 15}>
                {r.text}
              </text>
            </g>
          );
        })}
        <line
          className={styles.connector}
          x1={LABEL + x(reference)}
          x2={LABEL + x(reference)}
          y1={10 + BAR_OFFSET + 22}
          y2={ROW + 10 + BAR_OFFSET}
        />
      </svg>
    </div>
  );
}
