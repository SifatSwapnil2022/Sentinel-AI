import { scaleBand, scaleLinear } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import { useId, useState } from "react";
import type { Day } from "../data/schema";
import { count, percent, percentRange, shortDate } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./LabelCheckChart.module.css";

type Check = NonNullable<Day["labelCheck"]>;
interface Point extends Check {
  date: string;
}

const MARGIN = { top: 20, right: 16, bottom: 28, left: 44 };
const HEIGHT = 190;

/**
 * The check behind the concept-drift signal: over each rolling week of labelled predictions,
 * the estimate's range (from the model's confidence) against what labels actually measured.
 */
export function LabelCheckChart({ days }: { days: Day[] }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(900);
  const [active, setActive] = useState<Point | null>(null);
  const captionId = useId();
  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 120);

  const x = scaleBand()
    .domain(days.map((d) => d.date))
    .range([0, innerWidth])
    .paddingOuter(0.1);
  const cx = (date: string) => (x(date) ?? 0) + x.bandwidth() / 2;
  // Flag what raises an incident: measured below the range. Above it, the model did better
  // than its confidence said, which is worth seeing but not worth paging about.
  const points: Point[] = days.flatMap((d) =>
    d.labelCheck ? [{ date: d.date, ...d.labelCheck, flagged: d.conceptFlag === true }] : [],
  );

  if (points.length === 0) {
    return (
      <p className={styles.empty}>
        Not enough labels yet. The check starts once a week of predictions has at least 300 labels.
      </p>
    );
  }

  const values = points.flatMap((p) => [p.lower, p.upper, p.measured]);
  const y = scaleLinear()
    .domain([Math.min(...values) - 0.005, Math.max(...values) + 0.005])
    .range([HEIGHT, 0])
    .nice(4);
  const band =
    area<Point>()
      .x((p) => cx(p.date))
      .y0((p) => y(p.lower))
      .y1((p) => y(p.upper))
      .curve(curveMonotoneX)(points) ?? "";
  const estimate =
    line<Point>()
      .x((p) => cx(p.date))
      .y((p) => y(p.estimated))
      .curve(curveMonotoneX)(points) ?? "";
  const measured =
    line<Point>()
      .x((p) => cx(p.date))
      .y((p) => y(p.measured))(points) ?? "";
  const ticks = days.filter((_, i) => (days.length - 1 - i) % 7 === 0);
  const flagged = points.filter((p) => p.flagged);

  return (
    <figure className={styles.figure}>
      <figcaption id={captionId} className="visually-hidden">
        Measured accuracy over rolling weeks of labelled predictions against the estimate's range.{" "}
        {flagged.length > 0
          ? `Measured fell below the range on ${flagged.length} days, first on ${shortDate(flagged[0]?.date ?? "")}.`
          : "Measured stayed inside the range every day."}
      </figcaption>
      <div ref={ref} className={styles.frame} role="group" aria-labelledby={captionId}>
        <svg width={width} height={HEIGHT + MARGIN.top + MARGIN.bottom} aria-hidden="true">
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            {y.ticks(4).map((t) => (
              <g key={t} transform={`translate(0,${y(t)})`}>
                <line className={styles.grid} x2={innerWidth} />
                <text className={styles.label} x={-10} dy="0.32em" textAnchor="end">
                  {percent(t, 0)}
                </text>
              </g>
            ))}
            <path className={styles.band} d={band} />
            <path className={styles.estimate} d={estimate} />
            <path className={styles.measured} d={measured} />
            {points.map((p) => (
              <circle
                key={p.date}
                className={p.flagged ? styles.out : styles.ring}
                cx={cx(p.date)}
                cy={y(p.measured)}
                r={p.flagged ? 4.5 : 3.5}
              />
            ))}
            {flagged.map((p) => (
              <path
                key={p.date}
                className={styles.flag}
                transform={`translate(${cx(p.date)},${-10})`}
                d="M0 -5 5 0 0 5 -5 0z"
              />
            ))}
            {ticks.map((d) => (
              <text key={d.date} className={styles.label} x={cx(d.date)} y={HEIGHT + 20} textAnchor="middle">
                {shortDate(d.date)}
              </text>
            ))}
            {active && (
              <line
                className={styles.crosshair}
                x1={cx(active.date)}
                x2={cx(active.date)}
                y1={-4}
                y2={HEIGHT}
              />
            )}
            <rect
              className={styles.hit}
              width={innerWidth}
              height={HEIGHT}
              onPointerMove={(e) => {
                const px = e.clientX - e.currentTarget.getBoundingClientRect().left;
                const nearest = points.reduce((best, p) =>
                  Math.abs(cx(p.date) - px) < Math.abs(cx(best.date) - px) ? p : best,
                );
                setActive(nearest);
              }}
              onPointerLeave={() => setActive(null)}
            />
          </g>
        </svg>
        {active && (
          <div
            className={styles.readout}
            style={
              MARGIN.left + cx(active.date) > width - 230
                ? { right: width - MARGIN.left - cx(active.date) + 12 }
                : { left: MARGIN.left + cx(active.date) + 12 }
            }
          >
            <strong>Week ending {shortDate(active.date)}</strong>
            <span>
              Measured {percent(active.measured)} on {count(active.labelled)} labels
            </span>
            <span>
              Expected {percentRange(active.lower, active.upper)}
            </span>
            {active.flagged && <span className={styles.outText}>Below the expected range</span>}
          </div>
        )}
      </div>
    </figure>
  );
}
