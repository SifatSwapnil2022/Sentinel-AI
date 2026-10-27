import { useId, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { source, useFleet } from "../data/api";
import { shortDate } from "../lib/format";
import styles from "./AppShell.module.css";
import { type ThemeChoice, useTheme } from "./theme";
import { Wordmark } from "./Wordmark";

const SECTIONS = [
  { to: "/overview", label: "Overview" },
  { to: "/models", label: "Models" },
  { to: "/incidents", label: "Incidents" },
  { to: "/llm", label: "LLM apps" },
  { to: "/explore", label: "Explore" },
  { to: "/reports", label: "Reports" },
] as const;

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "Auto" },
];

export function AppShell() {
  const fleet = useFleet();
  const [theme, setTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const navId = useId();
  const { search } = useLocation();
  const open = fleet.data?.alerts.length ?? 0;
  // Carry the slicers across sections, so a filtered view survives navigation.
  const carry = new URLSearchParams(search);
  carry.delete("tab");
  const keep = carry.toString() ? `?${carry.toString()}` : "";

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
          onClick={() => setMenuOpen((v) => !v)}
        >
          {menuOpen ? "Close" : "Menu"}
        </button>
        <nav
          id={navId}
          aria-label="Main"
          className={styles.nav}
          data-open={menuOpen}
          onClick={(event) => {
            if (event.target instanceof Element && event.target.closest("a")) setMenuOpen(false);
          }}
        >
          <ul>
            {SECTIONS.map((s) => (
              <li key={s.to}>
                <NavLink to={`${s.to}${keep}`} className={styles.link ?? ""}>
                  {s.label}
                  {s.to === "/incidents" && open > 0 && (
                    <span className={styles.count} aria-label={`, ${open} open`}>
                      {open}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className={styles.meta}>
            <p className={styles.source}>
              {source.live ? "Live" : "Demo data"}
              {fleet.data && <> to {shortDate(fleet.data.today)}</>}
            </p>
            <label className={styles.theme}>
              <span className="visually-hidden">Colour theme</span>
              <select value={theme} onChange={(e) => setTheme(e.target.value as ThemeChoice)}>
                {THEMES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </nav>
      </header>
      <main id="main" className={styles.main} tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
