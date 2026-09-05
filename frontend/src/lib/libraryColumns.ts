/**
 * Which columns the table view offers, and which of them are drawn.
 *
 * **Two readers, two sets.** `catalogueMode.ts` owns which two readers, and
 * this is what each wants from a table: who is willing to lend what, what it
 * cost and who has read it, against where a book files on a shelf, what
 * published schemes say it is about, and whether the record itself is
 * finished. Half of each set is noise to the other, which is what the ticket
 * means by a list that is half irrelevant.
 *
 * **This is a view configuration, not a second table.** The table renders
 * whatever `COLUMN_KEYS` order it is handed; nothing here knows how a cell is
 * drawn. `BookTable` owns the rendering and types its definitions as
 * `Record<ColumnKey, Column>`, so a key here with no definition there, or a
 * definition with no key, is a compile error rather than a column that
 * silently disappears.
 *
 * **localStorage rather than the account**, which is the argument
 * `libraryView.ts` already makes and it holds here unchanged: this is a habit
 * rather than library data, it needs no endpoint, no schema and no migration.
 * It is also the only shape available. `GET /api/settings` is admin only, and
 * a column choice is one person's, not the library's.
 *
 * **Two storage keys, not one record holding both.** The household's choice
 * has to survive a switch into library mode and back, and separate keys make
 * that structural: writing one cannot touch the other, so there is no merge to
 * get wrong. It also means a browser that has only ever run one mode stores
 * only that mode.
 */

import type { MessageKey } from "../i18n/en";
import { CATALOGUE_MODES, type CatalogueMode } from "./catalogueMode";

/**
 * Every column the table can draw, in the order it draws them.
 *
 * **The order is the household's existing table with two columns inserted into
 * it**, rather than an order chosen fresh. Those two are not offered in
 * household mode at all, so filtering them out reproduces today's table column
 * for column, and this ticket does not rearrange anybody's catalogue.
 */
export const COLUMN_KEYS = [
  "title",
  "author",
  "series",
  "year",
  "publisher",
  "callNumber",
  "classification",
  "format",
  "condition",
  "lending",
  "discuss",
  "location",
  "pageCount",
  "language",
  "status",
  "rating",
  "tags",
  "ownership",
  "addedBy",
  "addedAt",
  "price",
  "purchasedAt",
  "purchaseSource",
] as const;

export type ColumnKey = (typeof COLUMN_KEYS)[number];

/**
 * The column that is always drawn and cannot be turned off.
 *
 * It is the only cell that links to the book, so a table without it is a table
 * you cannot leave. Enforced in `normalise`, so the rule holds for a set read
 * from storage and a set the reader just built alike.
 *
 * **Every mode must offer this column, and no type says so.** `normalise`
 * filters over `AVAILABLE_COLUMNS[mode]`, so its forced-title arm cannot fire
 * for a key that mode does not offer: giving this column an `offeredTo` of one
 * mode compiles, and hands the other a table with no link to any book.
 * `libraryColumns.test.ts` pins it for both modes, because a test is the only
 * place this can be said.
 */
export const ALWAYS_SHOWN: ColumnKey = "title";

interface ColumnSpec {
  label: MessageKey;
  /** The modes that offer this column at all. */
  offeredTo: readonly CatalogueMode[];
  /** The modes that draw it until somebody says otherwise. */
  defaultIn: readonly CatalogueMode[];
}

const BOTH = CATALOGUE_MODES;
const CATALOGUER = ["cataloguer"] as const;
const HOUSEHOLD = ["household"] as const;

/**
 * What each column is called, who is offered it, and who starts with it.
 *
 * **One table with three facts per column, rather than a label map beside two
 * lists of keys.** The lists were an exclusion literal: a third cataloguer
 * column would have been a compile error in the label map and in `BookTable`,
 * and no error at all in the household's list, so it would have reached every
 * household silently. Here a new entry in `COLUMN_KEYS` cannot compile without
 * saying which modes it belongs to.
 *
 * The label is here for a second reason. Two things name a column: the table's
 * own header and the picker that turns it on and off. A picker offering "Where
 * it is" against a header reading "Location" is one column presented as two,
 * and the reader cannot tell which one they just turned off.
 *
 * **`offeredTo` is wider than `defaultIn` on purpose for thirteen of these.** A
 * small archive still lends books and still records what a copy cost, so the
 * household's own columns are turned off for a cataloguer rather than taken
 * away.
 */
export const COLUMN_SPECS: Record<ColumnKey, ColumnSpec> = {
  title: { label: "field.title", offeredTo: BOTH, defaultIn: BOTH },
  author: { label: "field.author", offeredTo: BOTH, defaultIn: BOTH },
  series: { label: "series.label", offeredTo: BOTH, defaultIn: BOTH },
  year: { label: "field.year", offeredTo: BOTH, defaultIn: BOTH },
  publisher: { label: "field.publisher", offeredTo: BOTH, defaultIn: BOTH },
  callNumber: {
    label: "field.callNumber",
    offeredTo: CATALOGUER,
    defaultIn: CATALOGUER,
  },
  classification: {
    label: "field.classification",
    offeredTo: CATALOGUER,
    defaultIn: CATALOGUER,
  },
  format: { label: "copy.format", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  condition: { label: "copy.condition", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  lending: { label: "lending.label", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  discuss: { label: "discuss.label", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  location: { label: "location.label", offeredTo: BOTH, defaultIn: BOTH },
  pageCount: { label: "field.pageCount", offeredTo: BOTH, defaultIn: BOTH },
  language: { label: "field.language", offeredTo: BOTH, defaultIn: BOTH },
  status: {
    label: "field.readingStatus",
    offeredTo: BOTH,
    defaultIn: HOUSEHOLD,
  },
  rating: { label: "field.rating", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  tags: { label: "library.tags", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  ownership: {
    label: "field.ownership",
    offeredTo: BOTH,
    defaultIn: HOUSEHOLD,
  },
  addedBy: { label: "field.addedBy", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  addedAt: { label: "field.addedAt", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  price: { label: "copy.price", offeredTo: BOTH, defaultIn: HOUSEHOLD },
  purchasedAt: {
    label: "copy.purchasedAt",
    offeredTo: BOTH,
    defaultIn: HOUSEHOLD,
  },
  purchaseSource: {
    label: "copy.purchaseSource",
    offeredTo: BOTH,
    defaultIn: HOUSEHOLD,
  },
};

function keysWhere(
  mode: CatalogueMode,
  field: "offeredTo" | "defaultIn",
): readonly ColumnKey[] {
  return COLUMN_KEYS.filter((key) => COLUMN_SPECS[key][field].includes(mode));
}

/** Which columns each mode offers at all. Derived from `COLUMN_SPECS`. */
export const AVAILABLE_COLUMNS: Record<CatalogueMode, readonly ColumnKey[]> = {
  household: keysWhere("household", "offeredTo"),
  cataloguer: keysWhere("cataloguer", "offeredTo"),
};

/** What each mode draws until somebody says otherwise. */
export const DEFAULT_COLUMNS: Record<CatalogueMode, readonly ColumnKey[]> = {
  household: keysWhere("household", "defaultIn"),
  cataloguer: keysWhere("cataloguer", "defaultIn"),
};

const STORAGE_KEYS: Record<CatalogueMode, string> = {
  household: "libraryColumns.household",
  cataloguer: "libraryColumns.cataloguer",
};

/**
 * The keys, in canonical order, with the ones this mode does not offer dropped
 * and the title forced back in.
 *
 * One door for both the stored value and a toggle, so a set read from storage
 * and a set the reader just built cannot be ordered or bounded differently.
 */
function normalise(mode: CatalogueMode, chosen: Iterable<string>): ColumnKey[] {
  const wanted = new Set<string>(chosen);
  return AVAILABLE_COLUMNS[mode].filter(
    (key) => key === ALWAYS_SHOWN || wanted.has(key),
  );
}

/**
 * Whether this set is the one the mode starts with.
 *
 * Both sides are in `COLUMN_KEYS` order by construction, so comparing the
 * joined strings compares the sets. One door, because two callers ask this and
 * the second is `writeColumns` refusing to store a copy of the default.
 */
export function isDefaultColumns(
  mode: CatalogueMode,
  columns: readonly ColumnKey[],
): boolean {
  return columns.join(",") === DEFAULT_COLUMNS[mode].join(",");
}

/**
 * This mode's remembered columns, or its default.
 *
 * Every failure path returns the default rather than throwing, for the reasons
 * `readLibraryView` lists: a private window that refuses to answer, a value
 * written by a version that had other columns, storage that has been cleared.
 * A column choice is not worth failing to render a library over.
 *
 * A stored key this mode does not offer is dropped rather than honoured, which
 * is what keeps a hand-edited `libraryColumns.household` from producing a call
 * number column in a household.
 */
export function readColumns(mode: CatalogueMode): ColumnKey[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEYS[mode]);
    if (stored === null) return [...DEFAULT_COLUMNS[mode]];

    // **Decided on the stored tokens, never on the result.** The result always
    // carries the forced title, so a length test on it cannot tell a reader who
    // turned every other column off from a value naming nothing this version
    // knows. Testing the tokens keeps a title-only table storable, which is a
    // choice the picker can produce, while a set written by a version whose
    // columns were all called something else still falls back.
    const known = new Set<string>(AVAILABLE_COLUMNS[mode]);
    const tokens = stored.split(",").filter((token) => known.has(token));
    return tokens.length > 0
      ? normalise(mode, tokens)
      : [...DEFAULT_COLUMNS[mode]];
  } catch {
    return [...DEFAULT_COLUMNS[mode]];
  }
}

/**
 * Remember this mode's columns. Silent on failure, for the reason above.
 *
 * **Storing the default clears the key instead.** A stored copy of the default
 * stops following the default the moment a later version changes it, which is
 * the one thing "back to the usual columns" must not do, and a reader who turns
 * a column off and straight back on would otherwise be left holding a frozen
 * copy with no control offered to clear it. Here rather than at the call site,
 * so the invariant is one nobody has to remember.
 */
export function writeColumns(mode: CatalogueMode, keys: ColumnKey[]): void {
  try {
    // **Normalised first, so the guard below holds for any input.**
    // `isDefaultColumns` compares joined strings, so a set equal to the
    // default in another order, or carrying a key this mode does not offer,
    // would slip past it and be stored raw: the key would then hold a frozen
    // copy of the default while `canResetColumns`, which asks the same
    // question about the already-normalised set on screen, answered false and
    // hid the control that clears it. Only `toggleColumn` calls this today and
    // it passes a normalised set, so the sentence below was true only because
    // the one call site remembered. Now it is true because the function does.
    const canonical = normalise(mode, keys);
    if (isDefaultColumns(mode, canonical)) {
      localStorage.removeItem(STORAGE_KEYS[mode]);
      return;
    }
    localStorage.setItem(STORAGE_KEYS[mode], canonical.join(","));
  } catch {
    // Storage refused, and the choice goes with it, for the reason
    // `writeLibraryView` states: the columns are derived from storage rather
    // than held in state, so a pick that did not land re-reads as the previous
    // set.
    //
    // This said the opposite from the commit that wrote it, 410ab30, which
    // introduced the derived read in the same change. Never true here, unlike
    // the view's copy of it, which was.
  }
}

/**
 * The set after turning one column on or off.
 *
 * Pure, and separate from the writing, so the rules (canonical order, the
 * forced title, a key this mode does not offer) are testable without a
 * browser and are applied identically wherever a set is built.
 */
export function toggledColumns(
  mode: CatalogueMode,
  current: readonly ColumnKey[],
  key: ColumnKey,
): ColumnKey[] {
  const wanted = new Set<string>(current);
  if (!wanted.delete(key)) wanted.add(key);
  return normalise(mode, wanted);
}

/** Forget this mode's choice, so it draws its default again. */
export function clearColumns(mode: CatalogueMode): void {
  try {
    localStorage.removeItem(STORAGE_KEYS[mode]);
  } catch {
    // As above.
  }
}
