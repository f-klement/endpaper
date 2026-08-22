import {
  BookFormat,
  BookSort,
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
  location: string | null;
  /** Hardback, paperback, ebook, audiobook. "Do we have this on audio". */
  format: BookFormat | null;
  sort: BookSort;
  tagIds: number[];
}

export const DEFAULT_FILTERS: BookFilters = {
  query: "",
  status: null,
  ownership: null,
  series: null,
  location: null,
  format: null,
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
 * Covers or metadata.
 *
 * Two whole words rather than two icons: a grid glyph and a table glyph are
 * near enough identical at 16 pixels that the label is what actually says
 * which is which, and there are only two of them.
 */
export const VIEW_OPTIONS: { label: MessageKey; value: LibraryView }[] = [
  { label: "library.viewGrid", value: "grid" },
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
    filters.location ||
    filters.format ||
    filters.tagIds.length,
  );
}
