/**
 * How the library is drawn: covers, a table of metadata, or dense rows.
 *
 * localStorage rather than the account, for the same reason saved searches are:
 * this is a habit rather than library data, it needs no endpoint, no schema
 * and no migration, and the cost of getting it wrong is one click. If it turns
 * out people want the choice to follow them onto a phone, that is the moment to
 * move it, not before.
 *
 * Three readers of a library want three different things from it. Somebody
 * browsing for something to read recognises covers. Somebody auditing what the
 * library holds wants publisher, condition and what it cost, all visible at
 * once, which is a table. Somebody looking for a book they know they have wants
 * as many of them on the screen as will fit, with just enough to recognise one,
 * which is the list.
 *
 * **The default and the memory are both per mode**, which is the argument
 * `libraryColumns.ts` makes for the column set and it holds here unchanged: a
 * counter wants the dense view every morning, a household wants whatever it
 * picked, and one key holding both means turning library mode on overwrites the
 * household's choice and turning it off again leaves somebody looking at a view
 * they never picked. Two keys make that structural rather than remembered:
 * writing one cannot touch the other, so there is no merge to get wrong.
 *
 * **Adding a view is this array and nothing else.** The type is derived from
 * it, the decode below validates against it, and a browser holding a value a
 * later version removed falls back to the default rather than breaking, so no
 * migration is possible or needed.
 */

// Imported rather than re-declared: two spellings of "is this a cataloguer"
// is exactly the fact-stored-twice this module's two keys exist to avoid.
import type { CatalogueMode } from "./catalogueMode";
import { declareScopedPreference } from "./preference";

export const LIBRARY_VIEWS = ["grid", "table", "list"] as const;

export type LibraryView = (typeof LIBRARY_VIEWS)[number];

/**
 * What each mode opens on until somebody says otherwise.
 *
 * A household recognises its books by their covers. A counter wants records:
 * small covers, more of them, more metadata per row, which is the list. That is
 * the whole of this ticket, and it is one entry in this record rather than a
 * branch anywhere else.
 */
export const DEFAULT_LIBRARY_VIEWS: Record<CatalogueMode, LibraryView> = {
  household: "grid",
  cataloguer: "list",
};

/**
 * **The household's key is unprefixed where `libraryColumns`' is not**, and the
 * asymmetry is deliberate. Those keys shipped together with the modes; this one
 * is already in every browser that has ever chosen a view. Renaming it would
 * reset every existing household to the grid, which is the clobber the two keys
 * exist to prevent, arriving from the other direction.
 */
const STORAGE_KEYS: Record<CatalogueMode, string> = {
  household: "libraryView",
  cataloguer: "libraryView.cataloguer",
};

function isLibraryView(value: string | null): value is LibraryView {
  return LIBRARY_VIEWS.includes(value as LibraryView);
}

/**
 * This mode's remembered view, behind the door every stored choice goes through.
 *
 * What the door supplies, so that it is not restated here: neither reading nor
 * writing throws, absence means this mode's default, and so does a value this
 * version cannot read, whether it was written by a later version or by hand. A
 * remembered view is a convenience and none of those is a reason to fail to
 * draw a library.
 *
 * **`encode` always returns a string, so a choice equal to the default is
 * stored where the column preference clears its key instead.** That rule has two
 * halves: a stored copy of the default stops following the default if a later
 * version changes it, and a reader who turns a column off and straight back on
 * would be left holding that copy with no control offered to clear it.
 *
 * The second half does not reach here, because there is no reset control for
 * the view. The first half does, and is **accepted rather than absent**: a
 * cataloguer who picks the dense view is pinned to it if a later version opens
 * library mode on something else, and there is nothing in the interface that
 * clears the key. That is the intended trade, because the pick is one of three
 * named buttons rather than a set of twenty three, so choosing again is one
 * click and a reader can see which one is on. Add a reset control and this
 * should become the column preference's rule instead.
 *
 * **The asymmetry lives in this declaration and not in the door**, so that
 * teaching the door to clear a key on the default cannot reverse it here
 * without anybody editing this file.
 *
 * `whenUnknown` is the household, which is the reading answer
 * `catalogueMode()` already gives and the reason it is not a writing one.
 * Storage is the single copy: a pick that storage refused reads back as
 * whatever was there before, and the library still draws. That sentence said
 * the opposite until 2026-09-05 and was true when it was written, because the
 * view was React state then and the write was a side effect.
 */
export const libraryViewPreference = declareScopedPreference<
  CatalogueMode,
  LibraryView
>(STORAGE_KEYS, "household", {
  decode: (raw) => (isLibraryView(raw) ? raw : undefined),
  encode: (view) => view,
  fallback: (mode) => DEFAULT_LIBRARY_VIEWS[mode],
});
