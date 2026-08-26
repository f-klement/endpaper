import {
  BookFormat,
  BookSort,
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
} from "../../api/generated/model";
import type { MessageKey } from "../../i18n";
import type { LibraryView } from "../../lib/libraryView";

/** The filter state the grid is driven by. Local to this page. */
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
}

export const DEFAULT_FILTERS: BookFilters = {
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
  tagIds: [],
};

/**
 * The wishlist is not a fourth status, it is a saved view.
 *
 * "We want this and do not have it" is already expressible: want to read, plus
 * not owned. Adding a status for it would put the same fact in two places and
 * let them disagree.
 */
export const WISHLIST_FILTERS: BookFilters = {
  ...DEFAULT_FILTERS,
  status: ReadStatus.want_to_read,
  ownership: OwnershipStatus.not_owned,
};

/**
 * Whether the current view is the wishlist.
 *
 * A saved view is still a place as far as the reader is concerned. Without
 * this the wishlist was a page headed "Library" whose empty state suggested
 * scanning a barcode, which is the opposite of what an empty wishlist means:
 * nothing is missing, not nothing is here.
 *
 * Compares only the two fields that define it, so adding a search term or a
 * tag while browsing the wishlist keeps you on the wishlist.
 */
export function isWishlist(filters: BookFilters): boolean {
  return (
    filters.status === WISHLIST_FILTERS.status &&
    filters.ownership === WISHLIST_FILTERS.ownership
  );
}

export const STATUS_FILTERS: { label: MessageKey; value: ReadStatus | null }[] =
  [
    { label: "status.all", value: null },
    { label: "status.unread", value: ReadStatus.unread },
    { label: "status.want_to_read", value: ReadStatus.want_to_read },
    { label: "status.reading", value: ReadStatus.reading },
    { label: "status.read", value: ReadStatus.read },
    { label: "status.did_not_finish", value: ReadStatus.did_not_finish },
  ];

/**
 * Covers, metadata, or dense rows.
 *
 * Whole words rather than icons: a grid glyph, a table glyph and a list glyph
 * are near enough identical at 16 pixels that the label is what actually says
 * which is which.
 *
 * The strip they sit in scrolls (`overflow-x-auto` in `BookFilters`) and
 * already overflows a phone before this group: six status pills plus the sort
 * select is roughly 850px against a 390px viewport. So the third button costs
 * about 48px of a strip that was already scrolling, rather than being the thing
 * that breaks it.
 */
export const VIEW_OPTIONS: { label: MessageKey; value: LibraryView }[] = [
  { label: "library.viewGrid", value: "grid" },
  { label: "library.viewList", value: "list" },
  { label: "library.viewTable", value: "table" },
];

export const OWNERSHIP_FILTERS: {
  label: MessageKey;
  value: OwnershipStatus | null;
}[] = [
  { label: "ownership.filterAll", value: null },
  { label: "ownership.owned", value: OwnershipStatus.owned },
  { label: "ownership.unknown", value: OwnershipStatus.unknown },
  { label: "ownership.not_owned", value: OwnershipStatus.not_owned },
];

export const FORMAT_FILTERS: {
  label: MessageKey;
  value: BookFormat | null;
}[] = [
  { label: "format.filterAll", value: null },
  { label: "copy.format.hardcover", value: BookFormat.hardcover },
  { label: "copy.format.paperback", value: BookFormat.paperback },
  { label: "copy.format.ebook", value: BookFormat.ebook },
  { label: "copy.format.audiobook", value: BookFormat.audiobook },
  { label: "copy.format.other", value: BookFormat.other },
];

export const LENDING_FILTERS: {
  label: MessageKey;
  value: LendingWillingness | null;
}[] = [
  { label: "lending.filterAll", value: null },
  { label: "lending.happy", value: LendingWillingness.happy },
  { label: "lending.in_use", value: LendingWillingness.in_use },
  { label: "lending.never", value: LendingWillingness.never },
];

export const SORT_OPTIONS: { label: MessageKey; value: BookSort }[] = [
  { label: "sort.title_asc", value: BookSort.title_asc },
  { label: "sort.title_desc", value: BookSort.title_desc },
  { label: "sort.author", value: BookSort.author },
  { label: "sort.year_desc", value: BookSort.year_desc },
  { label: "sort.year_asc", value: BookSort.year_asc },
  { label: "sort.newest", value: BookSort.newest },
  { label: "sort.series", value: BookSort.series },
];

/** True when the grid is showing a narrowed view rather than everything. */
export function hasActiveFilters(filters: BookFilters): boolean {
  return Boolean(
    filters.query ||
    filters.status ||
    filters.ownership ||
    filters.series ||
    filters.author ||
    filters.location ||
    filters.format ||
    filters.lending ||
    filters.collection !== null ||
    filters.discuss ||
    filters.tagIds.length,
  );
}
