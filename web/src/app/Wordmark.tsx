import { NavLink } from "react-router";
import styles from "./Wordmark.module.css";

/** The product mark: an estimate band with its tick, beside the name. */
export function Wordmark({ to, label }: { to: string; label: string }) {
  return (
    <NavLink to={to} end className={styles.wordmark ?? ""} aria-label={label}>
      <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden="true">
        <rect x="1" y="4" width="20" height="6" rx="1.5" className={styles.band} />
        <line x1="12" x2="12" y1="0.5" y2="13.5" className={styles.tick} />
      </svg>
      <span>Sentinel</span>
    </NavLink>
  );
}
