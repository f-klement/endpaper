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
 * it, `readLibraryView` validates against it, and a browser holding a value a
 * later version removed falls back to the default rather than breaking, so no
 * migration is possible or needed.
 */

// The mode is the library's rather than the table's, and it lives in
// `libraryColumns.ts` because that is where it was first needed. Imported
// rather than re-declared: two spellings of "is this a cataloguer" is exactly
// the fact-stored-twice this module's two keys exist to avoid.
import type { CatalogueMode } from "./libraryColumns";

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
 * This mode's remembered view, or its default.
 *
 * Every failure path returns the default rather than throwing: a private
 * window that refuses to answer, a value written by a future version, storage
 * that has been cleared. None of those is a reason to fail to render a library.
 */
export function readLibraryView(mode: CatalogueMode): LibraryView {
  try {
    const stored = localStorage.getItem(STORAGE_KEYS[mode]);
    return isLibraryView(stored) ? stored : DEFAULT_LIBRARY_VIEWS[mode];
  } catch {
    return DEFAULT_LIBRARY_VIEWS[mode];
  }
}

/**
 * Remember this mode's view. Silent on failure, for the reason above.
 *
 * **A choice equal to the default is stored, where `writeColumns` clears its
 * key instead.** That rule has two halves: a stored copy of the default stops
 * following the default if a later version changes it, and a reader who turns
 * a column off and straight back on would be left holding that copy with no
 * control offered to clear it.
 *
 * The second half does not reach here, because there is no reset control for
 * the view. The first half does, and is **accepted rather than absent**: a
 * cataloguer who picks the dense view is pinned to it if a later version opens
 * library mode on something else, and there is nothing in the interface that
 * clears the key. That is the intended trade, because the pick is one of three
 * named buttons rather than a set of twenty three, so choosing again is one
 * click and a reader can see which one is on. Add a reset control and this
 * should become `writeColumns`' rule instead.
 */
export function writeLibraryView(mode: CatalogueMode, view: LibraryView): void {
  try {
    localStorage.setItem(STORAGE_KEYS[mode], view);
  } catch {
    // Storage refused, and the choice goes with it. The view is derived from
    // storage rather than held in state, and the counter bumped after this
    // call re-reads it, so a pick that did not land reads back as whatever was
    // there before. The library still renders, on the stored value or this
    // mode's default.
    //
    // This said the opposite until 2026-09-05, and was true when it was
    // written: the view was React state then and this write was a side effect.
    // Deriving it removed the second source of truth and this failure path
    // with it. Restoring the old promise means keeping the pick in state
    // beside the stored value, and a second copy of a value is how the two
    // come to disagree, which is the reason `pages/Home/hooks.ts` gives for
    // storage being the only copy.
  }
}
