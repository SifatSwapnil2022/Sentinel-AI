import { type MouseEvent, useId, useState } from "react";
import { NavLink, Outlet } from "react-router";
import { StatusMark } from "../components/StatusMark";
import { useFleet } from "../data/api";
import type { Status } from "../data/schema";
import { longDate } from "../lib/format";
import styles from "./AppShell.module.css";
import { Wordmark } from "./Wordmark";
import { type ThemeChoice, useTheme } from "./theme";

const RANK: Record<Status, number> = { critical: 0, warning: 1, healthy: 2 };
const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function AppShell() {
  const fleet = useFleet();
  const [theme, setTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const navId = useId();


  const models = [...(fleet.data?.models ?? [])].sort(
    (a, b) => RANK[a.status] - RANK[b.status] || a.name.localeCompare(b.name),
  );
  const openIncidents = fleet.data?.alerts.length ?? 0;

  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        Skip to content
      </a>
      <header className={styles.bar}>
        <Wordmark to="/" label="Sentinel home" />
        <button
          type="button"
          className={styles.menuButton}
          aria-expanded={menuOpen}
          aria-controls={navId}
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? "Close" : "Menu"}
        </button>
      </header>

      <nav
        id={navId}
        className={styles.nav}
        data-open={menuOpen}
        aria-label="Main"
        onClick={(event: MouseEvent<HTMLElement>) => {
          // On phones the menu covers the page; close it once a link is chosen.
          if (event.target instanceof Element && event.target.closest("a")) setMenuOpen(false);
        }}
      >
        <div className={styles.navHead}>
          <Wordmark to="/" label="Sentinel home" />
        </div>

        <ul className={styles.primary}>
          <li>
            <NavLink to="/overview" end className={styles.link ?? ""}>
              Overview
            </NavLink>
          </li>
          <li>
            <NavLink to="/incidents" className={styles.link ?? ""}>
              Incidents
              {openIncidents > 0 && (
                <span className={styles.count} aria-label={`${openIncidents} open`}>
                  {openIncidents}
                </span>
              )}
            </NavLink>
          </li>
        </ul>

        <p className={styles.groupLabel} id={`${navId}-models`}>
          Models
        </p>
        <ul className={styles.models} aria-labelledby={`${navId}-models`}>
          {models.map((m) => (
            <li key={m.id}>
              <NavLink to={`/models/${m.id}`} className={styles.link ?? ""}>
                <StatusMark status={m.status} compact />
                <span className={styles.modelName}>{m.name}</span>
              </NavLink>
            </li>
          ))}
        </ul>

        <div className={styles.foot}>
          {fleet.data && (
            <p className={styles.asOf}>Data through {longDate(fleet.data.today)}</p>
          )}
          <fieldset className={styles.theme}>
            <legend className="visually-hidden">Colour theme</legend>
            {THEMES.map((t) => (
              <label key={t.value} className={styles.themeOption}>
                <input
                  type="radio"
                  name="theme"
                  value={t.value}
                  checked={theme === t.value}
                  onChange={() => setTheme(t.value)}
                />
                <span>{t.label}</span>
              </label>
            ))}
          </fieldset>
        </div>
      </nav>

      <main id="main" className={styles.main} tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
