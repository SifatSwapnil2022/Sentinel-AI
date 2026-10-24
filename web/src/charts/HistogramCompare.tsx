import { scaleBand, scaleLinear } from "d3-scale";
import { percent } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./HistogramCompare.module.css";

interface Props {
  feature: string;
  bins: string[];
  reference: number[];
  current: number[];
}

const MARGIN = { top: 8, right: 8, bottom: 40, left: 40 };
const HEIGHT = 150;

/** Reference vs current share of rows per bin, side by side. */
export function HistogramCompare({ feature, bins, reference, current }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 100);
  const x = scaleBand().domain(bins).range([0, innerWidth]).paddingInner(0.3).paddingOuter(0.1);
  const pair = scaleBand()
    .domain(["reference", "current"])
    .range([0, x.bandwidth()])
    .paddingInner(0.12);
  const barWidth = Math.min(pair.bandwidth(), 22);
  const max = Math.max(...reference, ...current, 0.01);
  const y = scaleLinear().domain([0, max]).range([HEIGHT, 0]).nice(3);
  const rotate = bins.length > 6 || bins.some((b) => b.length > 8);

  return (
    <div ref={ref} className={styles.frame}>
      <svg
        width={width}
        height={HEIGHT + MARGIN.top + MARGIN.bottom + (rotate ? 18 : 0)}
        role="img"
        aria-label={`${feature}: share of rows per bin, reference against the latest day`}
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {y.ticks(3).map((t) => (
            <g key={t} transform={`translate(0,${y(t)})`}>
              <line className={styles.grid} x2={innerWidth} />
              <text className={styles.label} x={-8} dy="0.32em" textAnchor="end">
                {percent(t, 0)}
              </text>
            </g>
          ))}
          {bins.map((bin, i) => {
            const left = x(bin) ?? 0;
            const refValue = reference[i] ?? 0;
            const curValue = current[i] ?? 0;
            return (
              <g key={bin}>
                <rect
                  className={styles.reference}
                  x={left + (pair("reference") ?? 0) + (pair.bandwidth() - barWidth)}
                  y={y(refValue)}
                  width={barWidth}
                  height={HEIGHT - y(refValue)}
                  rx={2}
                >
                  <title>{`${bin}: ${percent(refValue)} of reference rows`}</title>
                </rect>
                <rect
                  className={styles.current}
                  x={left + (pair("current") ?? 0)}
                  y={y(curValue)}
                  width={barWidth}
                  height={HEIGHT - y(curValue)}
                  rx={2}
                >
                  <title>{`${bin}: ${percent(curValue)} of the latest day's rows`}</title>
                </rect>
                <text
                  className={styles.label}
                  transform={
                    rotate
                      ? `translate(${left + x.bandwidth() / 2},${HEIGHT + 12}) rotate(-30)`
                      : `translate(${left + x.bandwidth() / 2},${HEIGHT + 16})`
                  }
                  textAnchor={rotate ? "end" : "middle"}
                >
                  {bin}
                </text>
              </g>
            );
          })}
          <line className={styles.baseline} x2={innerWidth} y1={HEIGHT} y2={HEIGHT} />
        </g>
      </svg>
    </div>
  );
}
