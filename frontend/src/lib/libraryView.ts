/**
 * Whether the library is drawn as a grid of covers or as a table of metadata.
 *
 * localStorage rather than the account, for the same reason saved searches are:
 * this is a habit rather than household data, it needs no endpoint, no schema
 * and no migration, and the cost of getting it wrong is one click. If it turns
 * out people want the choice to follow them onto a phone, that is the moment to
 * move it, not before.
 *
 * The two readers of a library want different things from it. Somebody
 * browsing for something to read recognises covers; somebody auditing what the
 * household owns wants publisher, condition and what it cost, all visible at
 * once, which is a table.
 */

const STORAGE_KEY = "libraryView";

export const LIBRARY_VIEWS = ["grid", "table"] as const;

export type LibraryView = (typeof LIBRARY_VIEWS)[number];

export const DEFAULT_LIBRARY_VIEW: LibraryView = "grid";

function isLibraryView(value: string | null): value is LibraryView {
  return LIBRARY_VIEWS.includes(value as LibraryView);
}

/**
 * The remembered view, or the grid.
 *
 * Every failure path returns the default rather than throwing: a private
 * window that refuses to answer, a value written by a future version, storage
 * that has been cleared. None of those is a reason to fail to render a library.
 */
export function readLibraryView(): LibraryView {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isLibraryView(stored) ? stored : DEFAULT_LIBRARY_VIEW;
  } catch {
    return DEFAULT_LIBRARY_VIEW;
  }
}

/** Remember the view. Silent on failure, for the reason above. */
export function writeLibraryView(view: LibraryView): void {
  try {
    localStorage.setItem(STORAGE_KEY, view);
  } catch {
    // Storage refused. The choice still holds for this session, which is the
    // part the reader can see.
  }
}
