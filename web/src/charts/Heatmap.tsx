import { type ReactNode, useState } from "react";
import { Link } from "react-router";
import { shortDate } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./Heatmap.module.css";
import { Tooltip } from "./Tooltip";

export interface HeatmapRow {
  id: string;
  label: string;
  href?: string;
}

interface Props {
  rows: HeatmapRow[];
  /** ISO dates, oldest first. */
  columns: string[];
  value: (rowId: string, date: string) => number | null;
  /** CSS colour for a value. */
  color: (value: number) => string;
  /** The readout for one cell. */
  describe: (rowId: string, date: string, value: number | null) => ReactNode;
  /** Where clicking a cell goes (drill-down). */
  cellHref?: (rowId: string, date: string) => string;
  /** Marks on top of cells, e.g. an incident opening. */
  marker?: (rowId: string, date: string) => boolean;
  label: string;
  labelWidth?: number;
}

const ROW_HEIGHT = 24;
const AXIS = 22;

/** A grid of rows by days. Rows are links; each cell drills down; a table view comes from the tile. */
export function Heatmap({
  rows,
  columns,
  value,
  color,
  describe,
  cellHref,
  marker,
  label,
  labelWidth = 150,
}: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(900);
  const [hover, setHover] = useState<{ row: string; col: number; x: number; y: number } | null>(null);
  const plot = Math.max(width - labelWidth, 60);
  const cell = plot / Math.max(columns.length, 1);
  const height = rows.length * ROW_HEIGHT + AXIS;
  const tickEvery = Math.max(1, Math.ceil(70 / cell));

  return (
    <div ref={ref} className={styles.wrap} role="figure" aria-label={label}>
      <div className={styles.labels} style={{ width: labelWidth }}>
        {rows.map((row) => (
          <div key={row.id} className={styles.rowLabel} style={{ height: ROW_HEIGHT }}>
            {row.href ? <Link to={row.href}>{row.label}</Link> : row.label}
          </div>
        ))}
      </div>
      <svg
        width={plot}
        height={height}
        className={styles.svg}
        aria-hidden="true"
        style={{ left: labelWidth }}
        onPointerLeave={() => setHover(null)}
      >
        {rows.map((row, r) =>
          columns.map((date, c) => {
            const v = value(row.id, date);
            const x = c * cell;
            const y = r * ROW_HEIGHT;
            const rect = (
              <rect
                x={x + 0.5}
                y={y + 1}
                width={Math.max(cell - 1, 0.5)}
                height={ROW_HEIGHT - 2}
                fill={v === null ? "var(--wash)" : color(v)}
                className={styles.cell}
                data-active={hover?.row === row.id && hover.col === c}
                onPointerEnter={() => setHover({ row: row.id, col: c, x: x + labelWidth + cell / 2, y: y + ROW_HEIGHT / 2 })}
              />
            );
            const mark = marker?.(row.id, date) ? (
              <path
                d={`M${x + cell / 2} ${y + 6} l4 6 h-8z`}
                className={styles.marker}
                pointerEvents="none"
              />
            ) : null;
            const href = cellHref?.(row.id, date);
            return (
              <g key={`${row.id}-${date}`}>
                {href ? (
                  <Link to={href} tabIndex={-1} aria-hidden="true">
                    {rect}
                  </Link>
                ) : (
                  rect
                )}
                {mark}
              </g>
            );
          }),
        )}
        {columns.map((date, c) =>
          c % tickEvery === 0 ? (
            <text key={date} x={c * cell + 1} y={rows.length * ROW_HEIGHT + 15} className={styles.tick}>
              {shortDate(date)}
            </text>
          ) : null,
        )}
      </svg>
      <div style={{ height }} aria-hidden="true" />
      {hover && (
        <Tooltip x={hover.x} y={hover.y} width={width}>
          {describe(hover.row, columns[hover.col] ?? "", value(hover.row, columns[hover.col] ?? ""))}
        </Tooltip>
      )}
    </div>
  );
}

/** A legend for a colour scale: labelled swatches, in order. */
export function ScaleLegend({ items }: { items: { color: string; label: string }[] }) {
  return (
    <ul className={styles.legend}>
      {items.map((item) => (
        <li key={item.label}>
          <span className={styles.swatch} style={{ background: item.color }} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
