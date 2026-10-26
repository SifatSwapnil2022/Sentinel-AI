import { scaleBand, scaleLinear } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import { type KeyboardEvent, type PointerEvent, useId, useMemo, useState } from "react";
import type { Day, MetricName } from "../data/schema";
import { percent, percentRange, shortDate } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./AccuracyChart.module.css";

/** A day's measured value is drawn once this share of its labels has arrived. */
export const MIN_COVERAGE_FOR_MEASURED = 0.2;

const MARGIN = { top: 14, right: 16, bottom: 0, left: 44 };
const PLOT_HEIGHT = 260;
const STRIP_HEIGHT = 44;
const STRIP_GAP = 46;
const AXIS_HEIGHT = 26;

interface Props {
  days: Day[];
  metric: MetricName;
  reference: number | null;
  /** Human name of the metric for labels, e.g. "Accuracy". */
  label: string;
  /** The period before, drawn as a dashed line under this one, day by day. */
  compare?: Day[] | undefined;
  /** Called with the dates the reader drags across (or marks with Enter), to zoom to them. */
  onSelectRange?: (from: string, to: string) => void;
  /** Dates to mark with a labelled vertical rule, such as an incident opening. */
  markers?: { date: string; label: string }[] | undefined;
}

interface Point {
  date: string;
  value: number | null;
  lower: number | null;
  upper: number | null;
  measured: number | null;
  coverage: number;
  rows: number;
}

export function toPoints(days: Day[], metric: MetricName): Point[] {
  return days.map((d) => {
    const estimate = d.estimate[metric];
    const measured =
      d.measured && d.labelCoverage >= MIN_COVERAGE_FOR_MEASURED ? d.measured[metric] : null;
    return {
      date: d.date,
      value: estimate.value,
      lower: estimate.lower,
      upper: estimate.upper,
      measured,
      coverage: d.labelCoverage,
      rows: d.rows,
    };
  });
}

export function AccuracyChart({ days, metric, reference, label, compare, onSelectRange, markers = [] }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(900);
  const [active, setActive] = useState<number | null>(null);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const titleId = useId();
  const points = useMemo(() => toPoints(days, metric), [days, metric]);

  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 120);
  const height = MARGIN.top + PLOT_HEIGHT + STRIP_GAP + STRIP_HEIGHT + AXIS_HEIGHT;

  const x = scaleBand()
    .domain(points.map((p) => p.date))
    .range([0, innerWidth])
    .paddingInner(0.25)
    .paddingOuter(0.1);
  const cx = (date: string) => (x(date) ?? 0) + x.bandwidth() / 2;

  const previous = useMemo(() => (compare ? toPoints(compare, metric) : []), [compare, metric]);
  const values = points.flatMap((p) => [p.lower, p.upper, p.measured]).filter(isNumber);
  for (const p of previous) if (p.value !== null) values.push(p.value);
  if (reference !== null) values.push(reference);
  const lo = Math.max(0, Math.floor((Math.min(...values) - 0.01) * 50) / 50);
  const hi = Math.min(1, Math.ceil((Math.max(...values) + 0.01) * 50) / 50);
  const y = scaleLinear().domain([lo, hi]).range([PLOT_HEIGHT, 0]).nice(5);
  const yTicks = y.ticks(5);

  const withRange = points.filter((p) => p.lower !== null && p.upper !== null && p.value !== null);
  const bandPath =
    area<Point>()
      .x((p) => cx(p.date))
      .y0((p) => y(p.lower ?? 0))
      .y1((p) => y(p.upper ?? 0))
      .curve(curveMonotoneX)(withRange) ?? "";
  const linePath =
    line<Point>()
      .x((p) => cx(p.date))
      .y((p) => y(p.value ?? 0))
      .curve(curveMonotoneX)(withRange) ?? "";

  const strip = scaleLinear().domain([0, 1]).range([STRIP_HEIGHT, 0]);
  const barWidth = Math.min(x.bandwidth(), 12);
  const stripTop = MARGIN.top + PLOT_HEIGHT + STRIP_GAP;
  // Label as many days as fit, always including the latest.
  const tickStep = Math.max(1, Math.ceil(points.length / Math.max(innerWidth / 64, 2)));
  const dateTicks = points.filter((_, i) => (points.length - 1 - i) % tickStep === 0);
  const comparePath =
    previous.length > 0
      ? (line<Point>()
          .defined((p) => p.value !== null)
          .x((_, i) => cx(points[i + Math.max(points.length - previous.length, 0)]?.date ?? ""))
          .y((p) => y(p.value ?? 0))
          .curve(curveMonotoneX)(previous.slice(-points.length)) ?? "")
      : "";

  const indexAt = (event: PointerEvent<SVGRectElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - bounds.left;
    let best = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    points.forEach((p, i) => {
      const distance = Math.abs(cx(p.date) - px);
      if (distance < bestDistance) {
        best = i;
        bestDistance = distance;
      }
    });
    return best;
  };

  const select = (a: number, b: number) => {
    const [from, to] = [Math.min(a, b), Math.max(a, b)];
    const start = points[from];
    const end = points[to];
    if (onSelectRange && start && end && to > from) onSelectRange(start.date, end.date);
  };

  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const last = points.length - 1;
    if (event.key === "ArrowLeft") setActive((i) => Math.max(0, (i ?? last + 1) - 1));
    else if (event.key === "ArrowRight") setActive((i) => Math.min(last, (i ?? -1) + 1));
    else if (event.key === "Home") setActive(0);
    else if (event.key === "End") setActive(last);
    else if (event.key === "Escape") {
      setActive(null);
      setAnchor(null);
    } else if (event.key === "Enter" && onSelectRange && active !== null) {
      // Enter on one day, then another, zooms to the days between.
      if (anchor === null) setAnchor(active);
      else {
        select(anchor, active);
        setAnchor(null);
      }
    } else return;
    event.preventDefault();
  };
  const selection =
    anchor !== null && active !== null
      ? [Math.min(anchor, active), Math.max(anchor, active)]
      : null;

  const activePoint = active === null ? undefined : points[active];
  const latest = points.at(-1);

  return (
    <figure className={styles.figure}>
      <figcaption id={titleId} className="visually-hidden">
        {label} over {points.length} days. Latest estimate {percent(latest?.value)}, likely{" "}
        {percentRange(latest?.lower ?? null, latest?.upper ?? null)}. Use the arrow keys to read
        each day{onSelectRange ? "; press Enter on two days to zoom to them" : ""}. The table
        view has every value.
      </figcaption>
      <div
        ref={ref}
        className={styles.frame}
        tabIndex={0}
        role="group"
        aria-labelledby={titleId}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        <svg width={width} height={height} className={styles.svg} aria-hidden="true">
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            {yTicks.map((t) => (
              <g key={t} transform={`translate(0,${y(t)})`}>
                <line className={styles.grid} x2={innerWidth} />
                <text className={styles.yLabel} x={-10} dy="0.32em" textAnchor="end">
                  {Math.round(t * 100)}%
                </text>
              </g>
            ))}

            {reference !== null && (
              <g>
                <line
                  className={styles.reference}
                  x1={0}
                  x2={innerWidth}
                  y1={y(reference)}
                  y2={y(reference)}
                />
                <text className={styles.refLabel} x={innerWidth} y={y(reference) - 6} textAnchor="end">
                  Reference {percent(reference)}
                </text>
              </g>
            )}

            {selection && (
              <rect
                className={styles.selection}
                x={cx(points[selection[0] ?? 0]?.date ?? "") - x.bandwidth() / 2}
                width={
                  cx(points[selection[1] ?? 0]?.date ?? "") - cx(points[selection[0] ?? 0]?.date ?? "") + x.bandwidth()
                }
                y={-8}
                height={PLOT_HEIGHT + 8}
              />
            )}
            {markers
              .filter((m) => x(m.date) !== undefined)
              .map((m) => (
                <g key={m.date} transform={`translate(${cx(m.date)},0)`}>
                  <line className={styles.marker} y1={-8} y2={PLOT_HEIGHT} />
                  <text className={styles.markerLabel} x={4} y={-1}>
                    {m.label}
                  </text>
                </g>
              ))}
            {comparePath && <path className={styles.compare} d={comparePath} />}
            <path className={styles.band} d={bandPath} />
            <path className={styles.line} d={linePath} />

            {points.map((p) =>
              p.measured === null ? null : (
                <circle
                  key={p.date}
                  className={styles.ring}
                  cx={cx(p.date)}
                  cy={y(p.measured)}
                  r={4.5}
                />
              ),
            )}

            {activePoint && (
              <line
                className={styles.crosshair}
                x1={cx(activePoint.date)}
                x2={cx(activePoint.date)}
                y1={-8}
                y2={PLOT_HEIGHT + STRIP_GAP + STRIP_HEIGHT}
              />
            )}
          </g>

          <g transform={`translate(${MARGIN.left},${stripTop})`}>
            <line className={styles.baseline} x2={innerWidth} y1={STRIP_HEIGHT} y2={STRIP_HEIGHT} />
            {points.map((p) => (
              <rect
                key={p.date}
                className={styles.coverage}
                x={cx(p.date) - barWidth / 2}
                y={strip(p.coverage)}
                width={barWidth}
                height={Math.max(STRIP_HEIGHT - strip(p.coverage), p.coverage > 0 ? 1 : 0)}
              />
            ))}
            <text className={styles.yLabel} x={-10} y={0} dy="0.7em" textAnchor="end">
              100%
            </text>
            <text className={styles.yLabel} x={-10} y={STRIP_HEIGHT} textAnchor="end">
              0
            </text>
            {dateTicks.map((p) => (
              <text
                key={p.date}
                className={styles.xLabel}
                x={cx(p.date)}
                y={STRIP_HEIGHT + 18}
                textAnchor="middle"
              >
                {shortDate(p.date)}
              </text>
            ))}
          </g>

          <rect
            className={styles.hit}
            x={MARGIN.left}
            y={0}
            width={innerWidth}
            height={height - AXIS_HEIGHT}
            style={onSelectRange ? { cursor: "crosshair" } : undefined}
            onPointerDown={(event) => {
              if (!onSelectRange) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              setAnchor(indexAt(event));
              setDragging(true);
            }}
            onPointerMove={(event) => setActive(indexAt(event))}
            onPointerUp={(event) => {
              if (dragging && anchor !== null) select(anchor, indexAt(event));
              setDragging(false);
              setAnchor(null);
            }}
            onPointerLeave={() => {
              if (!dragging) setActive(null);
            }}
          />
        </svg>

        <p className={styles.stripLabel} style={{ top: stripTop - 4, left: MARGIN.left }}>
          Share of each day's predictions with labels
        </p>

        {activePoint && (
          <Readout
            point={activePoint}
            label={label}
            left={MARGIN.left + cx(activePoint.date)}
            width={width}
          />
        )}
      </div>
    </figure>
  );
}

function Readout({
  point,
  label,
  left,
  width,
}: {
  point: Point;
  label: string;
  left: number;
  width: number;
}) {
  const flip = left > width - 240;
  return (
    <div
      className={styles.readout}
      style={flip ? { right: width - left + 14 } : { left: left + 14 }}
      role="status"
    >
      <p className={styles.readoutDate}>{shortDate(point.date)}</p>
      <dl>
        <div>
          <dt>
            <span className={styles.keyLine} aria-hidden="true" />
            Estimated {label.toLowerCase()}
          </dt>
          <dd>
            <strong>{percent(point.value)}</strong>
            <span>{percentRange(point.lower, point.upper)}</span>
          </dd>
        </div>
        <div>
          <dt>
            <span className={styles.keyRing} aria-hidden="true" />
            Measured
          </dt>
          <dd>
            <strong>{point.measured === null ? "Not enough labels" : percent(point.measured)}</strong>
          </dd>
        </div>
        <div>
          <dt>Labels in</dt>
          <dd>
            <strong>{percent(point.coverage, 0)}</strong>
            <span>of {point.rows.toLocaleString("en-US")} predictions</span>
          </dd>
        </div>
      </dl>
    </div>
  );
}

function isNumber(v: number | null): v is number {
  return v !== null && Number.isFinite(v);
}
