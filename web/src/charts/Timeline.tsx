import { scaleTime } from "d3-scale";
import { useState } from "react";
import { Link } from "react-router";
import type { IncidentRef } from "../data/schema";
import { shortDate } from "../lib/format";
import { useElementWidth } from "../lib/useElementWidth";
import styles from "./Timeline.module.css";
import { Tooltip } from "./Tooltip";

interface Props {
  lanes: { id: string; label: string }[];
  incidents: IncidentRef[];
  from: string;
  to: string;
  label: string;
}

const LANE = 26;
const AXIS = 22;
const LABEL_WIDTH = 150;
const date = (iso: string) => new Date(`${iso}T00:00:00Z`);

/** One lane per model; each incident is a bar from the day it opened to the day it resolved. */
export function Timeline({ lanes, incidents, from, to, label }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(900);
  const [hover, setHover] = useState<{ incident: IncidentRef; x: number; y: number } | null>(null);
  // Room on the right so the last date label isn't cut off.
  const plot = Math.max(width - LABEL_WIDTH - 24, 80);
  const x = scaleTime()
    .domain([date(from), new Date(date(to).getTime() + 86_400_000)])
    .range([0, plot]);
  const ticks = x.ticks(Math.max(2, Math.floor(plot / 110)));
  const height = lanes.length * LANE + AXIS;

  return (
    <div ref={ref} className={styles.wrap} style={{ height }} role="figure" aria-label={label}>
      <svg width={width} height={height} onPointerLeave={() => setHover(null)}>
        <g transform={`translate(${LABEL_WIDTH},0)`}>
          {ticks.map((t) => (
            <g key={t.toISOString()}>
              <line x1={x(t)} x2={x(t)} y1={0} y2={lanes.length * LANE} className={styles.grid} />
              <text x={x(t)} y={lanes.length * LANE + 15} className={styles.tick} textAnchor="middle">
                {shortDate(t.toISOString().slice(0, 10))}
              </text>
            </g>
          ))}
        </g>
        {lanes.map((lane, i) => (
          <g key={lane.id} transform={`translate(0,${i * LANE})`}>
            <text x={0} y={LANE / 2 + 4} className={styles.laneLabel}>
              {lane.label}
            </text>
            <line x1={LABEL_WIDTH} x2={width} y1={LANE - 0.5} y2={LANE - 0.5} className={styles.rule} />
            {incidents
              .filter((inc) => inc.modelId === lane.id)
              .map((inc) => {
                const start = Math.max(x(date(inc.openedOn)), 0);
                const endIso = inc.resolvedOn ?? to;
                const end = Math.min(x(new Date(date(endIso).getTime() + (inc.resolvedOn ? 0 : 86_400_000))), plot);
                if (end < 0 || start > plot) return null;
                return (
                  <Link key={inc.id} to={`/incidents/${inc.id}`} aria-label={`${inc.title}, ${inc.modelId}`}>
                    <rect
                      x={LABEL_WIDTH + start}
                      y={6}
                      width={Math.max(end - start, 4)}
                      height={LANE - 12}
                      rx={2}
                      className={styles.bar}
                      data-severity={inc.severity}
                      data-status={inc.status}
                      onPointerEnter={() => setHover({ incident: inc, x: LABEL_WIDTH + start, y: i * LANE + LANE / 2 })}
                    />
                  </Link>
                );
              })}
          </g>
        ))}
      </svg>
      {hover && (
        <Tooltip x={hover.x} y={hover.y} width={width}>
          <strong>{hover.incident.title}</strong>
          {hover.incident.modelId}, {hover.incident.severity}
          <br />
          {shortDate(hover.incident.openedOn)} to{" "}
          {hover.incident.resolvedOn ? shortDate(hover.incident.resolvedOn) : "now (open)"}
        </Tooltip>
      )}
    </div>
  );
}
