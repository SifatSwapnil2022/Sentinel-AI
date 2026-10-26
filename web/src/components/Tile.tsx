import { type ReactNode, useId, useRef, useState } from "react";
import { type Row, download, toCsv } from "../lib/csv";
import styles from "./Tile.module.css";

export interface CsvExport {
  name: string;
  rows: readonly Row[];
  columns?: readonly string[];
}

interface Props {
  title: string;
  /** One line under the title: what the numbers are, and over which dates. */
  note?: ReactNode;
  /** Controls specific to this tile (a metric picker), shown in the header. */
  controls?: ReactNode;
  /** The same data as a table: the accessible and exact view of every chart. */
  table?: () => ReactNode;
  csv?: () => CsvExport;
  /** Columns of the 12-column grid this tile spans on wide screens. */
  span?: 3 | 4 | 5 | 6 | 7 | 8 | 12;
  headingLevel?: 2 | 3;
  children: ReactNode;
}

/** A panel with a BI-style header: chart or table, download the data, open it full screen. */
export function Tile({ title, note, controls, table, csv, span = 12, headingLevel = 2, children }: Props) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const dialog = useRef<HTMLDialogElement>(null);
  const [expanded, setExpanded] = useState(false);
  const titleId = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const body = view === "table" && table ? table() : children;

  const header = (inDialog: boolean) => (
    <header className={styles.header}>
      <div className={styles.titles}>
        <Heading id={inDialog ? undefined : titleId} className={styles.title}>
          {title}
        </Heading>
        {note && <p className={styles.note}>{note}</p>}
      </div>
      <div className={styles.actions}>
        {controls}
        {table && (
          <button
            type="button"
            className={styles.action}
            aria-pressed={view === "table"}
            onClick={() => setView(view === "table" ? "chart" : "table")}
          >
            <Icon name={view === "table" ? "chart" : "table"} />
            <span>{view === "table" ? "Chart" : "Table"}</span>
          </button>
        )}
        {csv && (
          <button
            type="button"
            className={styles.action}
            onClick={() => {
              const { name, rows, columns } = csv();
              download(name, toCsv(rows, columns));
            }}
          >
            <Icon name="download" />
            <span>CSV</span>
          </button>
        )}
        {inDialog ? (
          <button type="button" className={styles.action} onClick={() => dialog.current?.close()}>
            <Icon name="close" />
            <span>Close</span>
          </button>
        ) : (
          <button
            type="button"
            className={styles.action}
            aria-label={`Expand ${title}`}
            onClick={() => {
              setExpanded(true);
              dialog.current?.showModal();
            }}
          >
            <Icon name="expand" />
          </button>
        )}
      </div>
    </header>
  );

  return (
    <section className={styles.tile} data-span={span} aria-labelledby={titleId}>
      {header(false)}
      <div className={styles.body}>{expanded ? null : body}</div>
      <dialog
        ref={dialog}
        className={styles.dialog}
        aria-label={title}
        onClose={() => setExpanded(false)}
      >
        {expanded && (
          <>
            {header(true)}
            <div className={styles.body}>{body}</div>
          </>
        )}
      </dialog>
    </section>
  );
}

type IconName = "table" | "chart" | "download" | "expand" | "close";

function Icon({ name }: { name: IconName }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" className={styles.icon}>
      {name === "table" && (
        <path d="M1.5 2.5h11v9h-11zM1.5 5.5h11M1.5 8.5h11M5.5 5.5v6" />
      )}
      {name === "chart" && <path d="M1.5 12.5h11M2.5 10l3-4 3 2 3.5-5" />}
      {name === "download" && <path d="M7 1.5v8M3.5 6l3.5 3.5L10.5 6M2 12.5h10" />}
      {name === "expand" && <path d="M8.5 1.5h4v4M5.5 12.5h-4v-4M12.5 1.5 8 6M1.5 12.5 6 8" />}
      {name === "close" && <path d="M2.5 2.5l9 9M11.5 2.5l-9 9" />}
    </svg>
  );
}
