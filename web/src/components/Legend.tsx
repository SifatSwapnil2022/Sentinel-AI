import styles from "./Legend.module.css";

type Key = "band" | "ring" | "reference" | "line" | "flag" | "bar" | "barReference";

const LABEL_FOR: Record<Key, string> = {
  band: "Estimated, with likely range",
  ring: "Measured from labels",
  reference: "Reference accuracy",
  line: "Estimate",
  flag: "Measured outside the estimate",
  bar: "Current",
  barReference: "Reference",
};

/** Legend keys mirror the marks they name. */
export function Legend({ items, labels }: { items: Key[]; labels?: Partial<Record<Key, string>> }) {
  return (
    <ul className={styles.legend}>
      {items.map((item) => (
        <li key={item}>
          <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden="true">
            {item === "band" && (
              <>
                <rect x="1" y="2" width="20" height="10" rx="2" className={styles.band} />
                <line x1="11" x2="11" y1="0.5" y2="13.5" className={styles.tick} />
              </>
            )}
            {item === "line" && <line x1="1" x2="21" y1="7" y2="7" className={styles.tick} />}
            {item === "ring" && <circle cx="11" cy="7" r="4.5" className={styles.ring} />}
            {item === "reference" && <line x1="11" x2="11" y1="1" y2="13" className={styles.reference} />}
            {item === "flag" && <path d="M11 2 16 7 11 12 6 7z" className={styles.flag} />}
            {item === "bar" && <rect x="3" y="2" width="16" height="10" rx="1" className={styles.bar} />}
            {item === "barReference" && (
              <rect x="3" y="2" width="16" height="10" rx="1" className={styles.barReference} />
            )}
          </svg>
          <span>{labels?.[item] ?? LABEL_FOR[item]}</span>
        </li>
      ))}
    </ul>
  );
}
