/**
 * The shelf location most recently used when adding a book.
 *
 * Cataloguing happens a shelf at a time: somebody stands in front of one
 * bookcase and scans thirty books that all live in the same place. Typing that
 * place thirty times is the most repetitive act in the whole app, so the last
 * one used is remembered and offered as the default for the next book.
 *
 * localStorage rather than component state, so it survives a reload halfway
 * along a shelf, and per browser rather than per account, because it records
 * where somebody is standing and not who they are.
 */

const STORAGE_KEY = "lastLocation";

/** Matches the `location` column, so a remembered value is always sendable. */
export const MAX_LOCATION_LENGTH = 120;

/** Trim, cap, trim again: cutting at the cap can leave a trailing space. */
export function normaliseLocation(raw: string | null | undefined): string {
  return (raw ?? "").trim().slice(0, MAX_LOCATION_LENGTH).trim();
}

export function readLastLocation(): string {
  try {
    return normaliseLocation(localStorage.getItem(STORAGE_KEY));
  } catch {
    // Storage is unavailable in some private windows. A forgotten default is
    // not worth failing an add over.
    return "";
  }
}

/**
 * Remember a location for the next book, or forget it when cleared.
 *
 * Forgetting on empty is deliberate. Somebody who clears the field is saying
 * the next book has no shelf yet, and silently restoring the old one would
 * file it somewhere they had just refused to name.
 */
export function rememberLastLocation(raw: string | null | undefined): void {
  const location = normaliseLocation(raw);
  try {
    if (location) localStorage.setItem(STORAGE_KEY, location);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // As above.
  }
}
