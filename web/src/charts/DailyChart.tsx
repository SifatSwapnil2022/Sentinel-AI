import { scaleBand, scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { type PointerEvent, useState } from "react";
import { shortDate } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./DailyChart.module.css";
import { Tooltip } from "./Tooltip";

export interface Series {
  id: string;
  label: string;
  /** One value per date, aligned with ``dates``; null for no data. */
  values: (number | null)[];
  /** A categorical slot (1-8); omit for the estimate colour. */
  slot?: number | undefined;
}

interface Props {
  dates: string[];
  series: Series[];
  kind: "bar" | "line";
  /** The previous period, aligned day by day with ``dates`` (first series only). */
  compare?: (number | null)[] | undefined;
  format: (v: number) => string;
  label: string;
  height?: number;
  /** Start the axis at zero (counts); otherwise fit the data (rates, latency). */
  zero?: boolean;
  /** Stack bars of several series (amounts that add up) instead of placing them side by side. */
  stacked?: boolean;
}

const MARGIN = { top: 10, right: 12, bottom: 24, left: 52 };

/** Bars or lines over days, one shared axis, a readout on hover. */
export function DailyChart({
  dates,
  series,
  kind,
  compare,
  format,
  label,
  height = 220,
  zero = kind === "bar",
  stacked = false,
}: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(800);
  const [active, setActive] = useState<number | null>(null);
  const inner = Math.max(width - MARGIN.left - MARGIN.right, 80);
  const plotHeight = height - MARGIN.top - MARGIN.bottom;
  const x = scaleBand().domain(dates).range([0, inner]).paddingInner(kind === "bar" ? 0.25 : 0).paddingOuter(0.1);
  const cx = (d: string) => (x(d) ?? 0) + x.bandwidth() / 2;
  const stack = kind === "bar" && stacked && series.length > 1;
  const sums = dates.map((_, i) => series.reduce((t, s) => t + Math.max(s.values[i] ?? 0, 0), 0));
  const values = [...(stack ? sums : series.flatMap((s) => s.values)), ...(compare ?? [])].filter(
    (v): v is number => v !== null && Number.isFinite(v),
  );
  const max = values.length ? Math.max(...values) : 1;
  const min = values.length ? Math.min(...values) : 0;
  const pad = (max - min) * 0.1 || Math.abs(max) * 0.1 || 1;
  const y = scaleLinear()
    .domain([zero ? 0 : Math.max(0, min - pad), max + pad])
    .range([plotHeight, 0])
    .nice(4);
  const ticks = y.ticks(4);
  const step = Math.max(1, Math.ceil(dates.length / Math.max(inner / 64, 2)));
  const barWidth = x.bandwidth() / (kind === "bar" && !stack ? series.length : 1);
  // Running totals for stacked bars: where each series' segment starts on each day.
  const base = series.map((_, k) => dates.map((_, i) => series.slice(0, k).reduce((t, s) => t + Math.max(s.values[i] ?? 0, 0), 0)));
  const color = (s: Series) => `var(--series-${s.slot ?? 1})`;

  const pick = (event: PointerEvent<SVGRectElement>) => {
    const px = event.clientX - event.currentTarget.getBoundingClientRect().left;
    let best = 0;
    let distance = Number.POSITIVE_INFINITY;
    dates.forEach((d, i) => {
      const dd = Math.abs(cx(d) - px);
      if (dd < distance) {
        distance = dd;
        best = i;
      }
    });
    setActive(best);
  };

  return (
    <div ref={ref} className={styles.wrap}>
      {series.length > 1 && (
        <ul className={styles.legend}>
          {series.map((s) => (
            <li key={s.id}>
              <span className={styles.key} style={{ background: color(s) }} aria-hidden="true" />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <svg width={width} height={height} role="img" aria-label={label}>
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {ticks.map((t) => (
            <g key={t} transform={`translate(0,${y(t)})`}>
              <line x2={inner} className={styles.grid} />
              <text x={-8} dy="0.32em" textAnchor="end" className={styles.tick}>
                {format(t)}
              </text>
            </g>
          ))}
          {kind === "bar" &&
            compare?.map((v, i) =>
              v === null ? null : (
                <rect
                  key={`c${dates[i]}`}
                  x={(x(dates[i] ?? "") ?? 0) - 1}
                  y={y(v)}
                  width={x.bandwidth() + 2}
                  height={Math.max(plotHeight - y(v), 0)}
                  className={styles.compareBar}
                />
              ),
            )}
          {kind === "line" && compare && (
            <path
              d={
                line<number | null>()
                  .defined((v) => v !== null)
                  .x((_, i) => cx(dates[i] ?? ""))
                  .y((v) => y(v ?? 0))(compare) ?? ""
              }
              className={styles.compareLine}
            />
          )}
          {series.map((s, k) =>
            stack ? (
              <g key={s.id} fill={color(s)}>
                {s.values.map((v, i) => {
                  if (v === null || v <= 0) return null;
                  const start = base[k]?.[i] ?? 0;
                  const top = y(start + v);
                  // A 1px gap of surface between stacked segments.
                  const h = Math.max(y(start) - top - (k > 0 ? 1 : 0), 0.5);
                  return <rect key={dates[i]} x={x(dates[i] ?? "") ?? 0} y={top} width={x.bandwidth()} height={h} />;
                })}
              </g>
            ) : kind === "bar" ? (
              <g key={s.id} fill={color(s)}>
                {s.values.map((v, i) =>
                  v === null ? null : (
                    <rect
                      key={dates[i]}
                      x={(x(dates[i] ?? "") ?? 0) + k * barWidth}
                      y={y(Math.max(v, 0))}
                      width={Math.max(barWidth - (series.length > 1 ? 1 : 0), 1)}
                      height={Math.max(plotHeight - y(Math.max(v, 0)), v > 0 ? 1 : 0)}
                      rx={Math.min(2, barWidth / 4)}
                    />
                  ),
                )}
              </g>
            ) : (
              <path
                key={s.id}
                d={
                  line<number | null>()
                    .defined((v) => v !== null)
                    .x((_, i) => cx(dates[i] ?? ""))
                    .y((v) => y(v ?? 0))(s.values) ?? ""
                }
                stroke={color(s)}
                className={styles.line}
              />
            ),
          )}
          {active !== null && (
            <line
              x1={cx(dates[active] ?? "")}
              x2={cx(dates[active] ?? "")}
              y1={0}
              y2={plotHeight}
              className={styles.crosshair}
            />
          )}
          {dates.map((d, i) =>
            (dates.length - 1 - i) % step === 0 ? (
              <text key={d} x={cx(d)} y={plotHeight + 16} textAnchor="middle" className={styles.tick}>
                {shortDate(d)}
              </text>
            ) : null,
          )}
          <rect
            width={inner}
            height={plotHeight}
            fill="transparent"
            onPointerMove={pick}
            onPointerLeave={() => setActive(null)}
          />
        </g>
      </svg>
      {active !== null && (
        <Tooltip x={MARGIN.left + cx(dates[active] ?? "")} y={MARGIN.top + 20 + (series.length > 1 ? 28 : 0)} width={width}>
          <strong>{shortDate(dates[active] ?? "")}</strong>
          {series.map((s) => {
            const v = s.values[active];
            return (
              <span key={s.id} className={styles.row}>
                {series.length > 1 && <span className={styles.key} style={{ background: color(s) }} aria-hidden="true" />}
                {series.length > 1 ? `${s.label}: ` : ""}
                {v === null || v === undefined ? "No data" : format(v)}
              </span>
            );
          })}
          {stack && <span className={styles.row}>Total: {format(sums[active] ?? 0)}</span>}
          {compare && (
            <span className={styles.row}>
              Previous period:{" "}
              {compare[active] === null || compare[active] === undefined ? "No data" : format(compare[active] ?? 0)}
            </span>
          )}
        </Tooltip>
      )}
    </div>
  );
}
