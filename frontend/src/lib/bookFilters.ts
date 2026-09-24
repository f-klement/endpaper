/**
 * A `BookFilters` as URL parameters, and as the query `GET /api/books` is asked.
 *
 * Both directions in one module. A link somebody was handed carries filters in,
 * the listing endpoint takes them out, and the two used to be written in
 * different files with nothing saying they described the same set: the reading
 * half sat in `pages/Home/hooks.ts` next to its only caller, and the writing
 * half beside it in a function the page could not test without a query client.
 *
 * Pure and React free, so `tests/lib/bookFilters.test.ts` can compare what
 * `toParams` produces against the committed `openapi.json`. That comparison is
 * the point: a filter the UI sends and the API ignores, or one the API accepts
 * and the UI cannot send, is silent in every other test.
 *
 * **The shape lives here too**, and that was argued rather than assumed. Keeping
 * it on the page does not survive this module's own guard: the wire test
 * asserts every one of the twelve fields becomes a query parameter and its
 * client-only allowlist is empty, so nothing in `BookFilters` is view state and
 * it is not a view model. `lib/libraryView.ts` already holds `LibraryView` by
 * the same logic. `pages/Home/types.ts` re-exports both, so no consumer moved.
 *
 * `toggledFilter` is here for that reason and not as a convenience: which
 * fields hold a list, and what picking one of their values a second time means,
 * are facts about the filter set rather than about whichever control offers it.
 */

import {
  BookFormat,
  BookSort,
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
  type ListBooksParams,
} from "../api/generated/model";

/** The filter state the grid is driven by, and the set the listing endpoint takes. */
export interface BookFilters {
  query: string;
  status: ReadStatus | null;
  /** Whether a copy is physically here. Independent of `status`. */
  ownership: OwnershipStatus | null;
  series: string | null;
  /**
   * One person, as a name or as the key `GET /api/books/authors` issues.
   *
   * Whichever the link carried, kept verbatim so the chip can show it. Neither
   * is durable: a merge moves the key as surely as it moves the display name,
   * and an older link keeps working because the API resolves a folded spelling
   * back to whoever it was folded into, not because a key is an identity.
   */
  author: string | null;
  location: string | null;
  /** Hardback, paperback, ebook, audiobook. "Do we have this on audio". */
  format: BookFormat | null;
  /** Would the library lend it. Nothing to do with whether it is out now. */
  lending: LendingWillingness | null;
  /**
   * Which collection to show, `"unfiled"` for the books in none, or null for
   * all of them.
   *
   * Three states in one field rather than an id plus a boolean, because the
   * three are alternatives: the API refuses a request naming both a collection
   * and the unfiled books, so a shape that can express both is a shape the UI
   * can put into an error.
   */
  collection: number | "unfiled" | null;
  /**
   * Only books somebody has offered to talk about.
   *
   * **Anybody's offer, not the reader's own.** It is a boolean rather than a
   * three-way, because the useful question is "what can we talk about"; the
   * opposite view, books nobody has offered, is the rest of the library.
   */
  discuss: boolean;
  sort: BookSort;
  tagIds: number[];
  /**
   * Exact headings, each `scheme:number`, ANDed like tags.
   *
   * Strings rather than ids, and that is the data rather than a shortcut: a
   * classification row belongs to one book, so two books sharing a heading
   * share no row and there is no id to name. The pair is the identity.
   */
  headings: string[];
  /**
   * Dewey divisions, three digits ending in zero, ORed.
   *
   * ORed where `headings` is ANDed, because a division is a shelf location and
   * a book has essentially one: see `docs/decisions.md`.
   */
  ddcDivisions: string[];
}

/**
 * The whole library, unnarrowed.
 *
 * **Frozen, and so are its three lists.** It is exported, spread into every
 * rebuilt filter set and handed out as the fallback for a field a stored search
 * does not carry, so a caller that pushed into one of those lists would edit the
 * default for every later reader in the document. Nothing does today, and a
 * frozen list refuses it rather than leaving that resting on nobody trying: a
 * saved search's filters reach a component through a shared snapshot, and the
 * type carries no `readonly` to refuse it there.
 */
const NO_TAG_IDS: number[] = [];
const NO_HEADINGS: string[] = [];
const NO_DIVISIONS: string[] = [];

// Declared and then frozen, rather than frozen in place: `Object.freeze([])` is
// a `readonly never[]`, which the field types refuse, and casting it back would
// be claiming the opposite of what this is for.
Object.freeze(NO_TAG_IDS);
Object.freeze(NO_HEADINGS);
Object.freeze(NO_DIVISIONS);

export const DEFAULT_FILTERS: BookFilters = Object.freeze({
  query: "",
  status: null,
  ownership: null,
  series: null,
  author: null,
  location: null,
  format: null,
  lending: null,
  collection: null,
  discuss: false,
  sort: BookSort.title_asc,
  tagIds: NO_TAG_IDS,
  headings: NO_HEADINGS,
  ddcDivisions: NO_DIVISIONS,
});

/**
 * A filter whose value is a list.
 *
 * Read off the shape rather than written out, so a fourth list filter is
 * covered by existing. A named list is what goes stale beside the type it
 * claims to describe.
 */
export type ListFilterKey = {
  [K in keyof BookFilters]: BookFilters[K] extends unknown[] ? K : never;
}[keyof BookFilters];

/**
 * The patch that puts one value into a list filter, or takes it back out.
 *
 * A patch rather than a new filter set, because the library hook takes patches
 * through one door.
 *
 * **The filters handed in must be the ones currently rendered**, since the
 * patch is computed here rather than inside the state update: two toggles
 * landing in one React batch keep the last only, so a control that fires two
 * folds them into one patch.
 *
 * Which fields are lists is this module's business rather than a caller's, so
 * naming a field that is not one is a compile error rather than a filter that
 * quietly stops narrowing. Whether a list is ANDed or ORed does not reach here:
 * that is the server's, and it is recorded on the fields above.
 */
export function toggledFilter<K extends ListFilterKey>(
  filters: BookFilters,
  field: K,
  value: BookFilters[K][number],
): Pick<BookFilters, K> {
  const current: BookFilters[K][number][] = filters[field];
  const next = current.includes(value)
    ? current.filter((entry) => entry !== value)
    : [...current, value];
  // The cast is the computed key alone: TypeScript types `{ [field]: next }` as
  // a partial record whatever `field` is, and the element type is already
  // checked by the signature. Widening the return instead would let a caller
  // spread a patch that names no field at all.
  return { [field]: next } as Pick<BookFilters, K>;
}

/**
 * A filter set rebuilt from something stored, field by field.
 *
 * **A rebuild, never a cast.** A saved search is JSON a browser has been
 * holding since whichever version wrote it, and `JSON.parse` narrowed by a type
 * assertion is a promise about a string nobody checked. A stored `tagIds` that
 * is a string rather than a list passes such an assertion, then reaches
 * `toParams`, where its `length` is truthy and its `join` is not a function, so
 * applying that saved search throws while the page is drawing. That is the
 * class this closes, and it closes it for every list filter at once rather than
 * for the one that was found.
 *
 * **The fields are read off `DEFAULT_FILTERS` rather than written out**, so a
 * thirteenth filter is covered by existing, and an unknown key in the stored
 * object is dropped rather than carried into a request.
 *
 * **What this checks is the shape that would break the browser, not the value.**
 * A list has to be a list of strings or numbers, a string a string, a boolean a
 * boolean, and a field whose default is null may also carry a string or a
 * number, because three of those hold an identifier or one of `collection`'s
 * three states. Whether `status` names a reading status this API knows is the
 * API's question and it answers 422; whether `tagIds` can be joined is this
 * browser's, and nothing else was asking it.
 */
export function sanitiseFilters(value: unknown): BookFilters {
  // **Built from the defaults outwards rather than from the stored object
  // inwards.** Every field is present and of the right kind before anything
  // stored is looked at, so a missing field is the default by construction and a
  // key the shape does not have is never carried into a request.
  const rebuilt: BookFilters = { ...DEFAULT_FILTERS };
  if (value === null || typeof value !== "object") return rebuilt;
  const stored = value as Record<string, unknown>;
  const defaults: Record<string, unknown> = { ...DEFAULT_FILTERS };
  for (const key of Object.keys(defaults)) {
    const given = stored[key];
    // `Object.assign` rather than an indexed write, so nothing here is cast to
    // a shape it does not have. What is checked is the kind, one field at a
    // time, against the default that field already holds.
    //
    // **A list taken from storage is frozen as it is accepted**, because the
    // whole set is about to be shared: a saved search's filters are handed to a
    // component through one snapshot, and the caller that pushed into a list
    // would edit it for every later reader. Frozen here rather than by a walk
    // afterwards, so a thirteenth list filter is covered by existing, which is
    // the property the field walk above already has.
    if (keepsShape(given, defaults[key]))
      Object.assign(rebuilt, {
        // **Copied before it is frozen.** Freezing the argument's own list in
        // place would be a side effect on the caller's graph, in a function
        // whose whole claim is that it builds outwards from the defaults and
        // touches nothing it was handed. One caller passes a `JSON.parse` graph
        // nobody else holds, so it is latent; the signature takes `unknown` and
        // invites the caller that makes it real.
        [key]: Array.isArray(given) ? Object.freeze([...given]) : given,
      });
  }
  return rebuilt;
}

function keepsShape(given: unknown, fallback: unknown): boolean {
  if (Array.isArray(fallback))
    return (
      Array.isArray(given) &&
      given.every(
        (item) => typeof item === "string" || typeof item === "number",
      )
    );
  if (fallback === null)
    return (
      given === null || typeof given === "string" || typeof given === "number"
    );
  return typeof given === typeof fallback;
}

function isStatus(value: string | null): value is ReadStatus {
  return (
    value !== null && (Object.values(ReadStatus) as string[]).includes(value)
  );
}

function isSort(value: string | null): value is BookSort {
  return (
    value !== null && (Object.values(BookSort) as string[]).includes(value)
  );
}

function isFormat(value: string | null): value is BookFormat {
  return (
    value !== null && (Object.values(BookFormat) as string[]).includes(value)
  );
}

function isLending(value: string | null): value is LendingWillingness {
  return (
    value !== null &&
    (Object.values(LendingWillingness) as string[]).includes(value)
  );
}

function isOwnership(value: string | null): value is OwnershipStatus {
  return (
    value === OwnershipStatus.owned ||
    value === OwnershipStatus.not_owned ||
    value === OwnershipStatus.unknown
  );
}

function readCollection(value: string | null): BookFilters["collection"] {
  if (value === "unfiled") return "unfiled";
  if (value === null) return null;
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/**
 * The filters a link asks for, falling back to the defaults.
 *
 * `?ownership=unknown` is a real entry point rather than decoration: it is the
 * link the Goodreads import result offers, and the unconfirmed banner uses the
 * same one. An enum value, a collection id and the sort are checked before
 * they are kept; `series`, `author` and `location` are passed through and the
 * API bounds them itself (`max_length` 255, 500 and 120). An unrecognised value is
 * ignored rather than reported: a link is not a form, and there is nobody to
 * show an error to.
 */
export function readFilters(params: URLSearchParams): BookFilters {
  const ownership = params.get("ownership");
  const status = params.get("status");
  const sort = params.get("sort");
  const format = params.get("format");
  const lending = params.get("lending");

  return {
    ...DEFAULT_FILTERS,
    ...(isOwnership(ownership) ? { ownership } : {}),
    ...(isStatus(status) ? { status } : {}),
    ...(isSort(sort) ? { sort } : {}),
    ...(isFormat(format) ? { format } : {}),
    ...(isLending(lending) ? { lending } : {}),
    // Present and not "false" is on. A bare `?discuss` is what a link somebody
    // typed looks like, and treating it as off would make the link silently do
    // nothing.
    discuss: params.has("discuss") && params.get("discuss") !== "false",
    series: params.get("series"),
    author: params.get("author"),
    location: params.get("location"),
    // `?collection=4` is the link the collections page offers, and
    // `?collection=unfiled` the one the picker's empty option offers.
    collection: readCollection(params.get("collection")),
    // Repeated, not comma separated, because an LCSH heading is a phrase and
    // phrases carry commas. `getAll` is what makes that work, and it is why
    // this one field cannot follow `tags`.
    headings: params.getAll("classification").filter(Boolean),
    // Comma separated is safe here: a division is three digits.
    ddcDivisions: (params.get("ddc") ?? "").split(",").filter(Boolean),
  };
}

/**
 * The same filters as query parameters for the listing endpoint.
 *
 * Paging is not here: the caller decides how many rows it wants, and a filter
 * set does not know it is being read a page at a time.
 */
export function toParams(filters: BookFilters): ListBooksParams {
  return {
    // Empty values are omitted rather than sent blank, so the query key (and
    // therefore the cache entry) is the same as an unfiltered request.
    ...(filters.query ? { q: filters.query } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.ownership ? { ownership: filters.ownership } : {}),
    ...(filters.series ? { series: filters.series } : {}),
    ...(filters.author ? { author: filters.author } : {}),
    ...(filters.location ? { location: filters.location } : {}),
    ...(filters.format ? { format: filters.format } : {}),
    ...(filters.lending ? { lending: filters.lending } : {}),
    // The two are mutually exclusive on the server, which is why one field
    // produces one parameter or the other and never both.
    ...(typeof filters.collection === "number"
      ? { collection_id: filters.collection }
      : {}),
    ...(filters.collection === "unfiled" ? { unfiled: true } : {}),
    ...(filters.discuss ? { discuss: true } : {}),
    ...(filters.tagIds.length ? { tags: filters.tagIds.join(",") } : {}),
    ...(filters.headings.length ? { classification: filters.headings } : {}),
    ...(filters.ddcDivisions.length
      ? { ddc: filters.ddcDivisions.join(",") }
      : {}),
    sort: filters.sort,
  };
}
