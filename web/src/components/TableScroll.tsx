import type { ReactNode } from "react";
import layout from "../pages/layout.module.css";

/**
 * Wrapper for wide tables. On narrow screens the table scrolls sideways inside it, so the
 * region is focusable and named: keyboard users can reach it and scroll with the arrow keys.
 */
export function TableScroll({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={layout.tableWrap} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}
