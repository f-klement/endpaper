/**
 * Appearance: the palette, light or dark, and the wallpaper.
 *
 * The order of precedence for light and dark is deliberate and matches
 * `src/i18n`:
 *
 *   1. An explicit choice, stored on the account.
 *   2. The system's own setting, via `prefers-color-scheme`.
 *   3. Light.
 *
 * Following the system by default is the point: somebody who has set their
 * phone to dark at night should not have to set it again here. The stored
 * choice exists for the case where they want this app to differ, and choosing
 * "system" puts them back on the setting that follows.
 *
 * All three preferences live on the account rather than on the device, so they
 * follow a person between their phone and their laptop, with a per account
 * cache in front of the server for the first paint. See `appearance.ts` for why
 * the cache exists and what it discloses.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  cacheAppearance,
  readCachedAppearance,
  type Appearance,
  type ThemePreference,
} from "./appearance";
import { applyPalette } from "./palettes";
import {
  PATTERNS,
  patternDataUri,
  randomPattern,
  wallpaperInk,
  type Pattern,
} from "./patterns";

export {
  DEFAULT_APPEARANCE,
  readCachedAppearance,
  resolveAppearance,
  sameAppearance,
  type Appearance,
  type ThemePreference,
} from "./appearance";
export { PALETTES, isPaletteId, type PaletteId } from "./palettes";

/** What is actually on screen once `system` has been resolved. */
export type ResolvedTheme = "light" | "dark";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/**
 * Somebody who asked their operating system for more contrast.
 *
 * `index.css` answers the ink half of it. This half is the wallpaper, and it is
 * here rather than in a stylesheet so the reader can be told the system turned
 * it off. A decoration that silently vanishes reads as a bug.
 */
const CONTRAST_QUERY = "(prefers-contrast: more)";

/** A hex colour and nothing else. See `applyWallpaper`. */
const COLOUR = /^#[0-9a-f]{3,8}$/i;

function isColour(value: string): boolean {
  return COLOUR.test(value);
}

interface ThemeContextValue {
  /** What this account chose. Every screen that offers a choice writes here. */
  appearance: Appearance;
  /** Change part of it: this member's own choice, cached and pushed upstream. */
  setAppearance: (patch: Partial<Appearance>) => void;
  /**
   * Take the server's answer, or this account's cache, without treating it as
   * a new choice. Binds the account the cache is written under.
   */
  adopt: (appearance: Appearance, accountId: number | string) => void;
  /**
   * Unbind that account. Called when whatever knew who was signed in goes
   * away, so a later change is not filed under somebody who has left.
   */
  release: () => void;
  /** The theme in force. Use this to render, never `appearance.mode`. */
  theme: ResolvedTheme;
  /** The wallpaper chosen for this visit. */
  pattern: Pattern;
  /** The wallpaper is off because the system asked for more contrast. */
  wallpaperOff: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/** What the operating system is asking for, defaulting to light. */
export function systemTheme(): ResolvedTheme {
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

export function prefersMoreContrast(): boolean {
  return window.matchMedia?.(CONTRAST_QUERY).matches === true;
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

/**
 * The wallpaper for this visit, chosen once per page load.
 *
 * Module scope rather than component state, because `main.tsx` paints it before
 * React exists and the provider then has to render the one already on the page
 * rather than roll the dice a second time.
 */
let visitPattern: Pattern | null = null;

export function currentPattern(): Pattern {
  visitPattern ??= randomPattern();
  return visitPattern;
}

/**
 * The pattern a stored preference names, or a different one every visit.
 *
 * An id this build does not have is the same answer as no id at all: patterns
 * come and go between versions, and a wallpaper nobody recognises should not be
 * a blank page.
 */
export function patternFor(wallpaper: string | null): Pattern {
  const chosen = wallpaper
    ? PATTERNS.find((pattern) => pattern.id === wallpaper)
    : undefined;
  return chosen ?? currentPattern();
}

/**
 * Paint the wallpaper on the body.
 *
 * Body rather than a wrapper div, so it covers the viewport even where the
 * content is shorter than the screen. Exported because `main.tsx` calls it
 * before React mounts: painted from an effect it arrives a frame after the
 * page, which is the same flash `applyTheme` exists to avoid and is far more
 * obvious once the pattern is something a person picked.
 *
 * The ink is read at this moment rather than baked in, so it follows whatever
 * palette is on the document.
 */
export function applyWallpaper(pattern: Pattern, theme: ResolvedTheme): void {
  if (prefersMoreContrast()) {
    // Cleared rather than skipped: this also runs when the preference is turned
    // on with the page already open.
    document.body.style.backgroundImage = "";
    return;
  }

  const colours = wallpaperInk(theme);
  // No tokens, no wallpaper, and nothing but a colour ever reaches the tile.
  //
  // Two failures, one guard. An empty custom property would arrive as
  // `fill=""`, and an SVG shape with no fill is not invisible, it is black: a
  // missing stylesheet would dirty the page with 13% grey rather than leave it
  // plain. And these two values are interpolated into `stroke="{ink}"` inside
  // the tile, where a quote would close the attribute. `encodeURIComponent` is
  // not what stops that: the browser decodes the data URI and parses the
  // result as SVG, so an injected quote survives the round trip intact.
  //
  // What stops it is that the source set is closed: `data-theme` is only ever
  // set through `resolvePalette`, which checks against the seven, and both
  // stylesheets hold literal hexes. That is now an inference across two files,
  // so it is asserted here instead of being left to be re-derived.
  if (!isColour(colours.ink) || !isColour(colours.bloom)) return;

  document.body.style.backgroundImage = patternDataUri(pattern, theme, colours);
}

/**
 * Everything the document needs, in one call and in one frame.
 *
 * The three are not independent: the wallpaper's ink is read off the palette's
 * own tokens, so a palette or mode change that moves one without the other
 * leaves a frame with the new page and the old pattern on it.
 */
export function applyAppearance(
  appearance: Appearance,
  pattern: Pattern,
): ResolvedTheme {
  const theme = resolveTheme(appearance.mode);
  applyPalette(appearance.palette);
  applyTheme(theme);
  applyWallpaper(pattern, theme);
  return theme;
}

interface ThemeProviderProps {
  children: ReactNode;
  /** Forces a starting appearance. Tests use it; the app does not. */
  initialAppearance?: Appearance;
  /** Forces the wallpaper, so a test is not at the mercy of Math.random. */
  initialPattern?: Pattern;
}

export function ThemeProvider({
  children,
  initialAppearance,
  initialPattern,
}: ThemeProviderProps) {
  const [appearance, setStoredAppearance] = useState<Appearance>(
    () => initialAppearance ?? readCachedAppearance(),
  );
  const [theme, setTheme] = useState<ResolvedTheme>(() =>
    resolveTheme(appearance.mode),
  );
  const [wallpaperOff, setWallpaperOff] = useState(prefersMoreContrast);
  // Which account the cache is written under. A ref rather than state: nothing
  // renders differently because of it, and it is set on the same tick as the
  // appearance it belongs to.
  const account = useRef<number | string | null>(null);

  const pattern = useMemo(
    () => initialPattern ?? patternFor(appearance.wallpaper),
    [initialPattern, appearance.wallpaper],
  );

  // One effect, because the three parts are one paint: the wallpaper's ink is
  // read off the palette's own tokens, so moving the class without the pattern
  // leaves a frame with the new page and the old tile on it.
  //
  // The dark listener is attached only while the mode is `system`, or somebody
  // who asked for dark gets flipped back at sunrise by their laptop. The
  // contrast listener is always attached, because that preference is not one
  // this app offers and can be turned on with the page already open.
  useEffect(() => {
    setTheme(applyAppearance(appearance, pattern));
    setWallpaperOff(prefersMoreContrast());

    const contrast = window.matchMedia?.(CONTRAST_QUERY);
    const dark =
      appearance.mode === "system" ? window.matchMedia?.(DARK_QUERY) : undefined;

    const onChange = () => {
      const next = resolveTheme(appearance.mode);
      setTheme(next);
      applyTheme(next);
      applyWallpaper(pattern, next);
      setWallpaperOff(prefersMoreContrast());
    };

    contrast?.addEventListener("change", onChange);
    dark?.addEventListener("change", onChange);
    return () => {
      contrast?.removeEventListener("change", onChange);
      dark?.removeEventListener("change", onChange);
    };
  }, [appearance, pattern]);

  const setAppearance = useCallback((patch: Partial<Appearance>) => {
    setStoredAppearance((current) => {
      const next = { ...current, ...patch };
      // Nothing is written until an account has been named. A preference
      // belonging to nobody is exactly what this replaced, and one written
      // under the previous member's key would be worse than not caching at all.
      if (account.current !== null) cacheAppearance(account.current, next);
      return next;
    });
  }, []);

  const adopt = useCallback(
    (next: Appearance, accountId: number | string) => {
      account.current = accountId;
      cacheAppearance(accountId, next);
      setStoredAppearance(next);
    },
    [],
  );

  // This provider sits above the session gate and does not unmount when
  // somebody signs out, but the component that binds the account does. Without
  // this the ref goes on pointing at the member who left, and the next
  // appearance change from a signed-out screen is written into their cache and
  // moves `last` to them. Nothing can reach that today, because the only
  // control is behind the gate. Phase 3 puts a picker on the login screen.
  const release = useCallback(() => {
    account.current = null;
  }, []);

  // Unmount only. The paint itself happens with the appearance, above.
  useEffect(
    () => () => {
      document.body.style.backgroundImage = "";
    },
    [],
  );

  const context = useMemo(
    () => ({
      appearance,
      setAppearance,
      adopt,
      release,
      theme,
      pattern,
      wallpaperOff,
    }),
    [appearance, setAppearance, adopt, release, theme, pattern, wallpaperOff],
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
