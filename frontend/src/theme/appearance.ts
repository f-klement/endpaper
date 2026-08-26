/**
 * The appearance a member chose, cached per account on this device.
 *
 * The server is the authority: appearance is three columns on `users`, so it
 * follows a person from their laptop to their phone. This cache exists because
 * the server cannot answer in time for the first paint, and a page that renders
 * light and then turns dark is the flash the whole theme module exists to
 * avoid.
 *
 * The usual fix for that, an inline blocking `<script>` in the HTML, is not
 * available here: `backend/middleware.py` sets `script-src 'self'` with no
 * nonce, so an inline script would need a per-build hash in the CSP and
 * `middleware.py` would have to be generated from the frontend bundle. That was
 * considered and rejected: it couples the security headers to the asset
 * pipeline to save a network round trip that only a new account on a new device
 * ever waits for.
 *
 * So: write through. Every value the server sends is cached under the account
 * it belongs to, and the next boot on this device paints from the cache before
 * React exists, then reconciles when `/api/users/me/appearance` answers.
 *
 * Keyed by account because a library shares devices, and one member's dark
 * Gruvbox is not the other's. `last` is the account that used this browser most
 * recently, which is what the login screen paints with: a front door that looks
 * like the house you last let in. That does disclose to anyone holding the
 * device that somebody here uses Gruvbox. It is recorded here as a decision
 * rather than found later as a surprise.
 */

import { DEFAULT_PALETTE, resolvePalette, type PaletteId } from "./palettes";

const STORAGE_KEY = "appearance";

/**
 * Where the mode used to live, and still does for anyone who has not signed in
 * since this shipped. Read once as a fallback and never written again: the
 * account's own record replaces it the first time the server answers.
 */
const LEGACY_MODE_KEY = "theme";

/** What a person can pick for light and dark. `system` is a real option. */
export type ThemePreference = "light" | "dark" | "system";

/**
 * The wallpaper id that means "no wallpaper".
 *
 * A sentinel rather than a fourth field, because `wallpaper` already has three
 * states and a boolean beside it would let the two disagree: off with a pattern
 * named, or on with none. It is a tile in the picker for the same reason, and
 * `patternFor` is the one place that reads it.
 *
 * It has to satisfy the server's `^[a-z0-9-]{1,30}$`, and it has to be a word
 * no pattern will ever take. No pattern is called "none".
 */
export const WALLPAPER_OFF = "none";

export interface Appearance {
  palette: PaletteId;
  mode: ThemePreference;
  /**
   * The wallpaper's pattern id, or null for a different one every visit.
   *
   * Null is the default and is not an absence: "Surprise me" is the behaviour
   * this app was built around, and a new account keeps it.
   */
  wallpaper: string | null;
}

export const DEFAULT_APPEARANCE: Appearance = {
  palette: DEFAULT_PALETTE,
  mode: "system",
  wallpaper: null,
};

/**
 * What a device that has never signed anyone in shows.
 *
 * The same as a new account's, except that the wallpaper is named. The front
 * door never shuffles: `LoginPage.tsx` says it "is the first screen anyone
 * sees, so it is the one that decides whether the app looks made or
 * assembled", and a door that is a different pattern every visit reads as a
 * slot machine rather than as a house. Randomness is a pleasure once you are
 * inside.
 *
 * Willow Bough because it is the sparsest of the ten and the login card is
 * mostly page. An admin-set login image, where there is one, covers this
 * anyway: see `LoginPage`.
 */
export const DOOR_APPEARANCE: Appearance = {
  palette: DEFAULT_PALETTE,
  mode: "system",
  wallpaper: "willow",
};

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

/**
 * Anything at all, turned into an appearance this build can render.
 *
 * A palette this build does not have resolves to the default rather than being
 * an error, so an older client can read a newer one's choice. It cannot keep
 * it: the next deliberate change writes the whole appearance back, resolved
 * value included. Degrading on read and overwriting on write is the honest
 * pair, because a client cannot send back something it never rendered.
 */
export function resolveAppearance(value: unknown): Appearance {
  const source = (value ?? {}) as Partial<Record<keyof Appearance, unknown>>;
  return {
    palette: resolvePalette(source.palette),
    mode: isThemePreference(source.mode) ? source.mode : DEFAULT_APPEARANCE.mode,
    // Not checked against `PATTERNS` here: this module knows nothing about
    // wallpapers, and an id it cannot resolve is handled where they are drawn.
    wallpaper: typeof source.wallpaper === "string" ? source.wallpaper : null,
  };
}

interface Cache {
  last: string | null;
  accounts: Record<string, Appearance>;
}

function read(): Cache {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as Partial<Cache>) : null;
    const accounts = parsed?.accounts;
    return {
      last: typeof parsed?.last === "string" ? parsed.last : null,
      accounts:
        accounts && typeof accounts === "object" ? (accounts as Cache["accounts"]) : {},
    };
  } catch {
    // A half-written entry, or a private window with no storage at all. Both
    // mean "no cache", and neither is worth breaking the first render over.
    return { last: null, accounts: {} };
  }
}

/**
 * The appearance to paint with.
 *
 * With an account, that account's own. Without one, whoever used this device
 * last, which is what the login screen shows. With neither, the mode a previous
 * version stored per device, over the right defaults.
 *
 * The two fallbacks differ in one field and the difference is the point. A
 * named account with nothing stored has not chosen, so it gets Surprise me. A
 * device with nobody on it is the front door, which is fixed. Asking for an
 * account is what tells the two apart, so the caller does not have to.
 */
export function readCachedAppearance(accountId?: number | string | null): Appearance {
  const cache = read();
  const key = accountId != null ? String(accountId) : cache.last;
  const stored = key != null ? cache.accounts[key] : undefined;
  if (stored) return resolveAppearance(stored);

  const fallback = accountId != null ? DEFAULT_APPEARANCE : DOOR_APPEARANCE;
  try {
    return resolveAppearance({
      ...fallback,
      mode: localStorage.getItem(LEGACY_MODE_KEY) ?? fallback.mode,
    });
  } catch {
    return fallback;
  }
}

/** Remember this account's appearance, and that this account was here. */
export function cacheAppearance(
  accountId: number | string,
  appearance: Appearance,
): void {
  const cache = read();
  cache.accounts[String(accountId)] = appearance;
  cache.last = String(accountId);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // The choice lasts for this session, which beats refusing to make it.
  }
}

export function sameAppearance(a: Appearance, b: Appearance): boolean {
  return (
    a.palette === b.palette && a.mode === b.mode && a.wallpaper === b.wallpaper
  );
}
