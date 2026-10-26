import { useEffect, useId, useState } from "react";
import { StatusMark } from "../components/StatusMark";
import type { Status } from "../data/schema";
import { shortDate } from "../lib/format";
import { activeCount, type Filters, PERIODS } from "./filters";
import styles from "./FilterBar.module.css";
import { useFilters } from "./useFilters";

const STATUS_OPTIONS: Status[] = ["critical", "warning", "healthy"];
const STATUS_LABEL: Record<Status, string> = {
  critical: "Critical",
  warning: "Warning",
  healthy: "Healthy",
};

interface Props {
  /** "fleet" shows every slicer; "model" only the period and comparison. */
  scope?: "fleet" | "model";
  teams?: string[];
}

/** The global slicers. Changes apply at once and are kept in the address bar. */
export function FilterBar({ scope = "fleet", teams = [] }: Props) {
  const { filters, update, reset } = useFilters();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const panelId = useId();
  const active = activeCount(scope === "model" ? { ...filters, teams: [], statuses: [], q: "" } : filters);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1800);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <div className={styles.bar} role="region" aria-label="Filters">
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        Filters{active > 0 ? ` (${active})` : ""}
      </button>
      <div id={panelId} className={styles.panel} data-open={open}>
        <Period filters={filters} update={update} />

        <button
          type="button"
          className={styles.chip}
          aria-pressed={filters.compare}
          onClick={() => update({ compare: !filters.compare })}
        >
          Compare with previous period
        </button>

        {scope === "fleet" && (
          <>
            <TeamPicker teams={teams} selected={filters.teams} onChange={(t) => update({ teams: t })} />
            <fieldset className={styles.group}>
              <legend className={styles.label}>Status</legend>
              {STATUS_OPTIONS.map((status) => {
                const on = filters.statuses.includes(status);
                return (
                  <button
                    key={status}
                    type="button"
                    className={styles.chip}
                    aria-pressed={on}
                    onClick={() =>
                      update({
                        statuses: on
                          ? filters.statuses.filter((s) => s !== status)
                          : [...filters.statuses, status],
                      })
                    }
                  >
                    <span aria-hidden="true">
                      <StatusMark status={status} compact />
                    </span>
                    {STATUS_LABEL[status]}
                  </button>
                );
              })}
            </fieldset>
            <label className={styles.search}>
              <span className="visually-hidden">Find a model</span>
              <input
                type="search"
                placeholder="Find a model"
                value={filters.q}
                onChange={(e) => update({ q: e.target.value })}
              />
            </label>
          </>
        )}

        <div className={styles.end}>
          {active > 0 && (
            <button type="button" className={styles.plain} onClick={reset}>
              Clear filters
            </button>
          )}
          <button
            type="button"
            className={styles.plain}
            onClick={() => {
              // Undefined outside secure contexts, whatever the DOM types say.
              const clipboard = navigator.clipboard as Clipboard | undefined;
              void clipboard?.writeText(window.location.href).then(() => setCopied(true));
            }}
          >
            {copied ? "Link copied" : "Copy link"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Period({
  filters,
  update,
}: {
  filters: Filters;
  update: (patch: Partial<Filters>) => void;
}) {
  const custom = filters.from !== null && filters.to !== null;
  return (
    <fieldset className={styles.group}>
      <legend className={styles.label}>Period</legend>
      <div className={styles.segmented}>
        {PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={!custom && filters.period === p}
            onClick={() => update({ period: p, from: null, to: null })}
          >
            {p} days
          </button>
        ))}
      </div>
      {custom && filters.from && filters.to && (
        <span className={styles.range}>
          {shortDate(filters.from)} to {shortDate(filters.to)}
          <button
            type="button"
            className={styles.clear}
            aria-label="Clear the selected dates"
            onClick={() => update({ from: null, to: null })}
          >
            ×
          </button>
        </span>
      )}
    </fieldset>
  );
}

function TeamPicker({
  teams,
  selected,
  onChange,
}: {
  teams: string[];
  selected: string[];
  onChange: (teams: string[]) => void;
}) {
  const summary =
    selected.length === 0 ? "All teams" : selected.length === 1 ? selected[0] : `${selected.length} teams`;
  return (
    <details className={styles.picker}>
      <summary>
        <span className={styles.label}>Team</span> {summary}
      </summary>
      <div className={styles.menu}>
        {teams.map((team) => (
          <label key={team} className={styles.option}>
            <input
              type="checkbox"
              checked={selected.includes(team)}
              onChange={(e) =>
                onChange(e.target.checked ? [...selected, team] : selected.filter((t) => t !== team))
              }
            />
            {team}
          </label>
        ))}
        {selected.length > 0 && (
          <button type="button" className={styles.plain} onClick={() => onChange([])}>
            All teams
          </button>
        )}
      </div>
    </details>
  );
}
