import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "sentinel.theme";

/** Dark unless the viewer chose otherwise: a monitoring console is mostly read on long shifts. */
export const DEFAULT_THEME: ThemeChoice = "dark";

function read(): ThemeChoice {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "light" || stored === "system" || stored === "dark" ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

export function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
}

/** The viewer's theme choice, remembered per browser; "system" follows the OS setting. */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(read);

  useEffect(() => {
    applyTheme(choice);
    try {
      if (choice === DEFAULT_THEME) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      // Storage can be unavailable (private mode); the choice still applies for this visit.
    }
  }, [choice]);

  return [choice, useCallback((next: ThemeChoice) => setChoice(next), [])] as const;
}

/** Apply the stored choice before React renders, so there is no flash of the wrong theme. */
export function applyStoredTheme() {
  applyTheme(read());
}
