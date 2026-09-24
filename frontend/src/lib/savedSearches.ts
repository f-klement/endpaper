/**
 * Named filter sets, kept in the browser.
 *
 * "Unread Fantasy in the loft" is a question somebody asks weekly and rebuilds
 * from four controls every time. Smart collections are what the power users of
 * every rival name first, and this is the cheap half of one: the filters
 * already exist, so all that is missing is remembering a combination.
 *
 * localStorage rather than the database, deliberately. A saved view is a
 * personal habit, not shared library data, and it needs no migration, no
 * endpoint and no sync to be useful. If it turns out people want them on their
 * phone as well as their laptop, that is the moment to move them, not before.
 *
 * **Written against `BookFilters` rather than over a type parameter.** The
 * parameter cost the one thing this module has to do: a stored entry could only
 * be cast to it, never rebuilt from it, because nothing here knew what a filter
 * set was. `sanitiseFilters` does, so the entries are rebuilt, and the four call
 * sites that spelled the parameter stopped having to.
 */

import { sanitiseFilters, type BookFilters } from "./bookFilters";
import { declarePreference } from "./preference";

/** Bumped when the stored shape changes. Anything else is dropped, not read. */
const VERSION = 1;

/** Enough for the handful of habits a library has, few enough to stay a row. */
export const MAX_SAVED = 12;

export const MAX_NAME_LENGTH = 40;

export interface SavedSearch {
  id: string;
  name: string;
  filters: BookFilters;
}

interface Stored {
  version: number;
  searches: SavedSearch[];
}

/**
 * One entry, rebuilt, or nothing.
 *
 * The id and the name decide whether there is an entry at all: an entry with no
 * name cannot be told apart from another in the list, and one with no id cannot
 * be deleted. The filters are rebuilt rather than checked, because a filter set
 * this version cannot read is still a saved search somebody named.
 */
function rebuild(entry: unknown): SavedSearch | undefined {
  if (entry === null || typeof entry !== "object") return undefined;
  const { id, name, filters } = entry as Record<string, unknown>;
  if (typeof id !== "string" || id === "") return undefined;
  if (typeof name !== "string" || name.trim() === "") return undefined;
  // **Frozen here, entry and filters both, because this is the one preference
  // whose value is nested.** The door freezes what a codec hands back, and that
  // freeze is shallow, so without this an entry or its filter set would be
  // editable by whichever reader was handed the shared snapshot first, and the
  // edit would outlive the render. Neither `SavedSearch` nor `BookFilters`
  // carries a `readonly`, so the type refuses none of it.
  return Object.freeze({
    id,
    name,
    filters: Object.freeze(sanitiseFilters(filters)),
  });
}

/**
 * The saved views, behind the door every stored choice goes through.
 *
 * What the door supplies, so it is not restated here: neither reading nor
 * writing throws, and anything unreadable reads as an empty list. A saved
 * search is a convenience, and corrupt storage, a shape from a later version
 * and a private window that refuses to answer are none of them a reason to fail
 * to draw the library.
 *
 * **The envelope version is this module's, not the door's.** Two preferences
 * happen to be at version 1 and their shapes are unrelated, so one owned
 * version would mean bumping this dropped the other's stored values for every
 * reader.
 *
 * **Every entry is rebuilt rather than cast**, which is what closes the class
 * `sanitiseFilters` describes: a version match says the envelope is this
 * version's and says nothing about what is inside it.
 *
 * **The cap drops the oldest here as well as on saving.** It read the *first*
 * twelve and saved the *last* twelve until this door was written, so a browser
 * holding more than the cap would show one set and keep another. Only a version
 * with a larger cap could produce such a browser and none has shipped, so
 * making the two agree costs nothing and removes the question.
 */
export const savedSearchesPreference = declarePreference<
  readonly SavedSearch[]
>("savedSearches", {
  decode: (raw) => {
    const parsed = JSON.parse(raw) as Partial<Stored>;
    if (parsed.version !== VERSION || !Array.isArray(parsed.searches))
      return undefined;
    const rebuilt = parsed.searches
      .map(rebuild)
      .filter((entry): entry is SavedSearch => entry !== undefined);
    return rebuilt.slice(-MAX_SAVED);
  },
  // **A save rewrites every entry in this version's shape, so a field only a
  // later version knew about does not survive one.** The rebuild carries the
  // fields `DEFAULT_FILTERS` has and drops the rest, and both verbs hand the
  // whole decoded list back here, so deleting one search rewrites the others.
  // Concretely: save on a newer build, roll the container back, delete one
  // search, and the newer field is gone from all of them.
  //
  // Accepted rather than fixed, and written down because the trade is real and
  // the old code had the opposite one silently. Casting preserved unknown fields
  // and let a value of the wrong kind through, which threw while the page was
  // drawing. For a browser local convenience, losing a filter on a downgrade is
  // the cheaper failure, and carrying the raw entry beside the rebuilt one to
  // avoid it is not worth what it costs to reason about.
  encode: (searches) =>
    JSON.stringify({
      version: VERSION,
      searches: [...searches],
    } satisfies Stored),
  fallback: () => [],
});

/**
 * The list after saving one, replacing any of the same name.
 *
 * Pure, and separate from the storing, so the rules (the trim, the cap, what
 * counts as the same name) are testable without a browser and hold wherever a
 * list is built.
 *
 * Replacing rather than appending is what makes "save" mean update: saving
 * twice under one name is how somebody adjusts a view, and two entries called
 * "Loft" would leave them unable to tell which is which.
 */
export function withSearchSaved(
  current: readonly SavedSearch[],
  name: string,
  filters: BookFilters,
): SavedSearch[] {
  const trimmed = name.trim().slice(0, MAX_NAME_LENGTH).trim();
  if (!trimmed) return [...current];

  const existing = current.filter(
    (search) => search.name.toLowerCase() !== trimmed.toLowerCase(),
  );
  return [
    ...existing,
    { id: `${Date.now()}-${trimmed.toLowerCase()}`, name: trimmed, filters },
  ].slice(-MAX_SAVED);
}

/** The list after forgetting one. Pure, for the reason above. */
export function withSearchDeleted(
  current: readonly SavedSearch[],
  id: string,
): SavedSearch[] {
  return current.filter((search) => search.id !== id);
}
