import type { Severity, Status } from "../data/schema";
import { STATUS_LABELS } from "../lib/describe";
import styles from "./StatusMark.module.css";

interface Props {
  status: Status | Severity;
  /** Hide the word visually (it stays available to screen readers). */
  compact?: boolean;
}

/** Status is always a shape plus a word, never colour alone. */
export function StatusMark({ status, compact = false }: Props) {
  return (
    <span className={styles.mark} data-status={status}>
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className={styles.shape}>
        {status === "healthy" && <circle cx="6" cy="6" r="4.5" />}
        {status === "warning" && <path d="M6 1.2 11 10.4H1z" />}
        {status === "critical" && <path d="M6 0.8 11.2 6 6 11.2 0.8 6z" />}
      </svg>
      <span className={compact ? "visually-hidden" : styles.word}>{STATUS_LABELS[status]}</span>
    </span>
  );
}
