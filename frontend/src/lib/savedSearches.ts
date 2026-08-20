/**
 * Named filter sets, kept in the browser.
 *
 * "Unread Fantasy in the loft" is a question somebody asks weekly and rebuilds
 * from four controls every time. Smart collections are what the power users of
 * every rival name first, and this is the cheap half of one: the filters
 * already exist, so all that is missing is remembering a combination.
 *
 * localStorage rather than the database, deliberately. A saved view is a
 * personal habit, not shared household data, and it needs no migration, no
 * endpoint and no sync to be useful. If it turns out people want them on their
 * phone as well as their laptop, that is the moment to move them, not before.
 */

/** Bumped when the stored shape changes. Anything else is dropped, not read. */
const VERSION = 1;

const STORAGE_KEY = "savedSearches";

/** Enough for the handful of habits a household has, few enough to stay a row. */
export const MAX_SAVED = 12;

export const MAX_NAME_LENGTH = 40;

export interface SavedSearch<TFilters> {
  id: string;
  name: string;
  filters: TFilters;
}

interface Stored<TFilters> {
  version: number;
  searches: SavedSearch<TFilters>[];
}

/**
 * Read the saved views, or an empty list.
 *
 * Every failure path returns empty rather than throwing: corrupt storage, a
 * shape from a future version, a private window that refuses to answer. A
 * saved search is a convenience, and none of those is a reason to fail to
 * render the library.
 */
export function readSavedSearches<TFilters>(): SavedSearch<TFilters>[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Stored<TFilters>;
    if (parsed.version !== VERSION || !Array.isArray(parsed.searches)) return [];
    return parsed.searches.slice(0, MAX_SAVED);
  } catch {
    return [];
  }
}

function write<TFilters>(searches: SavedSearch<TFilters>[]): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: VERSION, searches } satisfies Stored<TFilters>),
    );
  } catch {
    // Storage full or refused. The view is lost, the library still works.
  }
}

/**
 * Add a view, replacing one of the same name.
 *
 * Replacing rather than appending is what makes "save" mean update: saving
 * twice under one name is how somebody adjusts a view, and two entries called
 * "Loft" would leave them unable to tell which is which.
 */
export function saveSearch<TFilters>(
  name: string,
  filters: TFilters,
): SavedSearch<TFilters>[] {
  const trimmed = name.trim().slice(0, MAX_NAME_LENGTH).trim();
  if (!trimmed) return readSavedSearches<TFilters>();

  const existing = readSavedSearches<TFilters>().filter(
    (search) => search.name.toLowerCase() !== trimmed.toLowerCase(),
  );
  const next = [
    ...existing,
    { id: `${Date.now()}-${trimmed.toLowerCase()}`, name: trimmed, filters },
  ].slice(-MAX_SAVED);

  write(next);
  return next;
}

export function deleteSearch<TFilters>(id: string): SavedSearch<TFilters>[] {
  const next = readSavedSearches<TFilters>().filter(
    (search) => search.id !== id,
  );
  write(next);
  return next;
}
