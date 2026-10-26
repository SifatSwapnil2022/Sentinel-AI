import type { ReactNode } from "react";
import styles from "./Tooltip.module.css";

/** A readout that follows the pointer inside a chart; positioned in the chart's own box. */
export function Tooltip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const left = x > width - 220 ? x - 12 : x + 12;
  return (
    <div
      className={styles.tip}
      style={{ left, top: y, transform: x > width - 220 ? "translate(-100%, -50%)" : "translateY(-50%)" }}
      role="status"
    >
      {children}
    </div>
  );
}
