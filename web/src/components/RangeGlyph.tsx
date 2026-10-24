import { scaleLinear } from "d3-scale";
import { percent, percentRange } from "../lib/format";
import styles from "./RangeGlyph.module.css";

/** Horizontal inset so axis labels centred on the first and last tick are not clipped. */
export const GLYPH_PAD = 16;

interface Props {
  value: number;
  lower: number;
  upper: number;
  /** Accuracy on reference data, drawn as a thin rule. */
  reference?: number;
  /** Measured accuracy, drawn as a hollow ring. */
  measured?: number | null;
  domain: readonly [number, number];
  width: number;
  height?: number;
  label: string;
}

/**
 * The signature mark: an estimate drawn with its likely range (band + tick), against the
 * reference (rule), with measured accuracy as a hollow ring when labels exist.
 */
export function RangeGlyph({
  value,
  lower,
  upper,
  reference,
  measured,
  domain,
  width,
  height = 22,
  label,
}: Props) {
  const x = scaleLinear().domain(domain).range([GLYPH_PAD, width - GLYPH_PAD]).clamp(true);
  const mid = height / 2;
  const description = [
    `${label}: estimated ${percent(value)}, likely ${percentRange(lower, upper)}`,
    reference === undefined ? null : `reference ${percent(reference)}`,
    measured === null || measured === undefined ? null : `measured ${percent(measured)}`,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <svg
      className={styles.glyph}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={description}
    >
      <line className={styles.track} x1={x(domain[0])} x2={x(domain[1])} y1={mid} y2={mid} />
      {reference !== undefined && (
        <line className={styles.reference} x1={x(reference)} x2={x(reference)} y1={2} y2={height - 2} />
      )}
      <rect
        className={styles.band}
        x={x(lower)}
        y={mid - 5}
        width={Math.max(x(upper) - x(lower), 2)}
        height={10}
        rx={2}
      />
      <line className={styles.tick} x1={x(value)} x2={x(value)} y1={mid - 7} y2={mid + 7} />
      {measured !== null && measured !== undefined && (
        <circle className={styles.ring} cx={x(measured)} cy={mid} r={4.5} />
      )}
    </svg>
  );
}
