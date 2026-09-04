import { DEFAULT_FILTERS } from "../../lib/bookFilters";
import type { BookFilters } from "../../lib/bookFilters";
import {
  BookFormat,
  BookSort,
  LendingWillingness,
  OwnershipStatus,
  ReadStatus,
} from "../../api/generated/model";
import type { MessageKey } from "../../i18n";
import type { LibraryView } from "../../lib/libraryView";

// `BookFilters` and `DEFAULT_FILTERS` live in `lib/bookFilters.ts` and are
// re-exported here. The shape moved because nothing in it is view state: the
// wire test asserts every field becomes a query parameter and its client-only
// allowlist is empty. Re-exported rather than updated at every import, so the
// consumers on this page did not have to move with it.
export type { BookFilters } from "../../lib/bookFilters";
export { DEFAULT_FILTERS } from "../../lib/bookFilters";

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
  { label: "sort.ddc", value: BookSort.ddc },
  // **The scheme's own label rather than a second spelling of it.**
  // `lib/classificationLabels.ts` argues that one table naming a scheme is
  // what stops three copies drifting, and a sort named after a scheme would be
  // a fourth. `sort.ddc` above predates that table and renaming a string a
  // reader already knows is not this ticket's.
  { label: "classification.scheme.lcc", value: BookSort.lcc },
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
    filters.tagIds.length ||
    filters.headings.length ||
    filters.ddcDivisions.length,
  );
}
