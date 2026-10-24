import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import type { Feature } from "../data/schema";

const CAP = 3;

/**
 * How far a statistic sits past its threshold, on one scale for every method: 1 is the
 * threshold. Distances are statistic / threshold; p-values are threshold / p (smaller p is more
 * drift). Capped at 3 so one extreme day doesn't flatten the rest.
 */
export function driftScore(statistic: number, threshold: number, isPValue: boolean): number {
  const raw = isPValue ? threshold / Math.max(statistic, 1e-12) : statistic / threshold;
  return Math.min(Math.max(raw, 0), CAP);
}

export function DriftSpark({ feature, width = 140, height = 28 }: { feature: Feature; width?: number; height?: number }) {
  const scores = feature.series.map((s) => driftScore(s.statistic, feature.threshold, feature.isPValue));
  const x = scaleLinear().domain([0, Math.max(scores.length - 1, 1)]).range([2, width - 2]);
  const y = scaleLinear().domain([0, CAP]).range([height - 2, 2]);
  const path = line<number>()
    .x((_, i) => x(i))
    .y((s) => y(s))(scores);
  const last = scores.at(-1) ?? 0;

  return (
    <svg width={width} height={height} aria-hidden="true" style={{ display: "block", overflow: "visible" }}>
      <line x1={0} x2={width} y1={y(1)} y2={y(1)} stroke="var(--hairline-strong)" strokeWidth={1} />
      <path d={path ?? ""} fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeLinejoin="round" />
      <circle
        cx={x(scores.length - 1)}
        cy={y(last)}
        r={3.5}
        fill={last >= 1 ? "var(--warning)" : "var(--ink)"}
        stroke="var(--sheet)"
        strokeWidth={1.5}
      />
    </svg>
  );
}
