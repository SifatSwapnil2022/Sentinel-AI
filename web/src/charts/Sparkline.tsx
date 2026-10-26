import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";

/** A small line for a KPI: shape only, no axes. The value it ends on is printed beside it. */
export function Sparkline({
  values,
  width = 120,
  height = 30,
  label,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  label: string;
}) {
  const known = values.filter((v): v is number => v !== null);
  if (known.length < 2) return null;
  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.05 || 1;
  const x = scaleLinear().domain([0, values.length - 1]).range([1, width - 3]);
  const y = scaleLinear().domain([lo - pad, hi + pad]).range([height - 2, 2]);
  const path = line<number | null>()
    .defined((v) => v !== null)
    .x((_, i) => x(i))
    .y((v) => y(v ?? 0))(values);
  const last = known.at(-1) ?? 0;
  return (
    <svg width={width} height={height} role="img" aria-label={label}>
      <path d={path ?? ""} fill="none" stroke="var(--estimate)" strokeWidth={1.5} />
      <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} fill="var(--estimate)" />
    </svg>
  );
}
