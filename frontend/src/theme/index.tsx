/**
 * Light and dark, resolved the same way the language is.
 *
 * The order of precedence is deliberate and matches `src/i18n`:
 *
 *   1. An explicit choice, stored per device.
 *   2. The system's own setting, via `prefers-color-scheme`.
 *   3. Light.
 *
 * Following the system by default is the point: somebody who has set their
 * phone to dark at night should not have to set it again here. The stored
 * choice exists for the case where they want this app to differ, and choosing
 * "system" puts them back on the setting that follows.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { patternDataUri, randomPattern, type Pattern } from "./patterns";

/** What a person can pick. `system` is a real option, not the absence of one. */
export type ThemePreference = "light" | "dark" | "system";

/** What is actually on screen once `system` has been resolved. */
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

interface ThemeContextValue {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  /** The theme in force. Use this to render, never `preference`. */
  theme: ResolvedTheme;
  /** The wallpaper chosen for this visit. */
  pattern: Pattern;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function isPreference(value: string | null): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

export function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isPreference(stored) ? stored : "system";
  } catch {
    // Unavailable in a private window. Following the system is the right
    // fallback anyway.
    return "system";
  }
}

/** What the operating system is asking for, defaulting to light. */
export function systemTheme(): ResolvedTheme {
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === "system" ? systemTheme() : preference;
}

/**
 * Put the resolved theme on the document.
 *
 * Exported because `main.tsx` calls it before React mounts. Doing it only in an
 * effect means the first paint is light and then flips, which is exactly the
 * flash everyone notices on a dark-themed site.
 */
export function applyTheme(theme: ResolvedTheme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

interface ThemeProviderProps {
  children: ReactNode;
  /** Forces a starting preference. Tests use it; the app does not. */
  initialPreference?: ThemePreference;
  /** Forces the wallpaper, so a test is not at the mercy of Math.random. */
  initialPattern?: Pattern;
}

export function ThemeProvider({
  children,
  initialPreference,
  initialPattern,
}: ThemeProviderProps) {
  const [preference, setStoredPreference] = useState<ThemePreference>(
    () => initialPreference ?? readStoredPreference(),
  );
  const [theme, setTheme] = useState<ResolvedTheme>(() =>
    resolveTheme(preference),
  );
  // Chosen once per mount and never stored: a different one each time somebody
  // comes back is the whole idea, and remembering it would defeat that.
  const [pattern] = useState<Pattern>(() => initialPattern ?? randomPattern());

  // Follow the system while, and only while, nobody has chosen. Someone who
  // picked dark should not be flipped back at sunrise by their laptop.
  useEffect(() => {
    const resolved = resolveTheme(preference);
    setTheme(resolved);
    applyTheme(resolved);

    if (preference !== "system") return;

    const query = window.matchMedia?.(DARK_QUERY);
    if (!query) return;

    const onChange = () => {
      const next = systemTheme();
      setTheme(next);
      applyTheme(next);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The choice lasts for this session only, which beats refusing to switch.
    }
    setStoredPreference(next);
  }, []);

  // Painted on the body rather than a wrapper div, so it covers the viewport
  // even where the content is shorter than the screen.
  useEffect(() => {
    document.body.style.backgroundImage = patternDataUri(pattern, theme);
    return () => {
      document.body.style.backgroundImage = "";
    };
  }, [pattern, theme]);

  const context = useMemo(
    () => ({ preference, setPreference, theme, pattern }),
    [preference, setPreference, theme, pattern],
  );

  return (
    <ThemeContext.Provider value={context}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error("useTheme must be used inside a ThemeProvider");
  }
  return context;
}
