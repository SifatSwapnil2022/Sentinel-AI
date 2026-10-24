import { scaleBand, scaleLinear } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import { useId, useState } from "react";
import type { Day } from "../data/schema";
import { decimal, shortDate } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./ReconstructionChart.module.css";

const MARGIN = { top: 16, right: 16, bottom: 28, left: 44 };
const HEIGHT = 200;

/** Multivariate drift: how badly each day's data reconstructs, against its expected range. */
export function ReconstructionChart({ days }: { days: Day[] }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(900);
  const [active, setActive] = useState<number | null>(null);
  const captionId = useId();
  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 120);

  const x = scaleBand()
    .domain(days.map((d) => d.date))
    .range([0, innerWidth])
    .paddingOuter(0.1);
  const cx = (date: string) => (x(date) ?? 0) + x.bandwidth() / 2;
  const values = days.flatMap((d) => [d.multivariate.lower, d.multivariate.upper, d.multivariate.error]);
  const y = scaleLinear()
    .domain([Math.min(...values) * 0.97, Math.max(...values) * 1.03])
    .range([HEIGHT, 0])
    .nice(4);

  const band =
    area<Day>()
      .x((d) => cx(d.date))
      .y0((d) => y(d.multivariate.lower))
      .y1((d) => y(d.multivariate.upper))
      .curve(curveMonotoneX)(days) ?? "";
  const path =
    line<Day>()
      .x((d) => cx(d.date))
      .y((d) => y(d.multivariate.error))
      .curve(curveMonotoneX)(days) ?? "";
  const ticks = days.filter((_, i) => (days.length - 1 - i) % 7 === 0);
  const activeDay = active === null ? undefined : days[active];
  const drifted = days.filter((d) => d.multivariate.drifted).length;

  return (
    <figure className={styles.figure}>
      <figcaption id={captionId} className="visually-hidden">
        Reconstruction error over {days.length} days; {drifted} of them outside the expected range.
      </figcaption>
      <div ref={ref} className={styles.frame} role="group" aria-labelledby={captionId}>
        <svg width={width} height={HEIGHT + MARGIN.top + MARGIN.bottom} aria-hidden="true">
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            {y.ticks(4).map((t) => (
              <g key={t} transform={`translate(0,${y(t)})`}>
                <line className={styles.grid} x2={innerWidth} />
                <text className={styles.label} x={-10} dy="0.32em" textAnchor="end">
                  {t.toFixed(2)}
                </text>
              </g>
            ))}
            <path className={styles.band} d={band} />
            <path className={styles.line} d={path} />
            {days.map((d) => (
              <circle
                key={d.date}
                className={d.multivariate.drifted ? styles.out : styles.in}
                cx={cx(d.date)}
                cy={y(d.multivariate.error)}
                r={d.multivariate.drifted ? 4.5 : 2.5}
              />
            ))}
            {ticks.map((d) => (
              <text key={d.date} className={styles.label} x={cx(d.date)} y={HEIGHT + 20} textAnchor="middle">
                {shortDate(d.date)}
              </text>
            ))}
            {activeDay && (
              <line
                className={styles.crosshair}
                x1={cx(activeDay.date)}
                x2={cx(activeDay.date)}
                y1={0}
                y2={HEIGHT}
              />
            )}
            <rect
              className={styles.hit}
              width={innerWidth}
              height={HEIGHT}
              onPointerMove={(e) => {
                const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
                const step = innerWidth / days.length;
                setActive(Math.min(days.length - 1, Math.max(0, Math.floor(px / step))));
              }}
              onPointerLeave={() => setActive(null)}
            />
          </g>
        </svg>
        {activeDay && (
          <div
            className={styles.readout}
            style={
              MARGIN.left + cx(activeDay.date) > width - 220
                ? { right: width - MARGIN.left - cx(activeDay.date) + 12 }
                : { left: MARGIN.left + cx(activeDay.date) + 12 }
            }
          >
            <strong>{shortDate(activeDay.date)}</strong>
            <span>
              Error {decimal(activeDay.multivariate.error, 3)}, expected{" "}
              {decimal(activeDay.multivariate.lower, 3)} to {decimal(activeDay.multivariate.upper, 3)}
            </span>
            {activeDay.multivariate.drifted && <span className={styles.outText}>Outside expected range</span>}
          </div>
        )}
      </div>
    </figure>
  );
}
