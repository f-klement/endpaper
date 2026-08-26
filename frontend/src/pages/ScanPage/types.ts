import { BookFormat } from "../../api/generated/model";
import type {
  BookCreate,
  BookLookup,
  BookMatch,
  CopyCreate,
} from "../../api/generated/model";
import { normaliseLocation } from "../../lib/lastLocation";

/**
 * What the confirm step is editing.
 *
 * Either the metadata a source returned, or (when neither knew the ISBN) a
 * blank draft the member fills in themselves. `notFound` is what tells the UI
 * to show editable fields instead of a read-only summary; it is client state
 * and is never sent to the API.
 */
export interface BookDraft extends BookLookup {
  notFound?: boolean;
}

/**
 * The whole book being added: the metadata, and everything chosen about this
 * copy of it.
 *
 * One value with one door rather than six states with a setter each. Six of
 * them cost the hook's interface, the page and the confirm card a line apiece
 * to add a field, and no caller stopped knowing anything. Same shape and same
 * vocabulary as `BookFilters` and `useLibrary.update`, which is the point:
 * two of these in one app should read as one pattern.
 *
 * `draft` is nullable because the page reads it to decide whether the scanner
 * or the confirm card is on screen. The value around it is not: `location`
 * survives a cancel, so there is always a pending book even before a lookup.
 */
export interface PendingBook {
  draft: BookDraft | null;
  coverFile: File | null;
  isPrivate: boolean;
  /**
   * Where this copy goes. Carried over from the last book added rather than
   * cleared, because a shelf is catalogued in one sitting.
   */
  location: string;
  /**
   * Hardback or paperback. Offered here because the person scanning is
   * holding the book, which is the one moment they can answer without going
   * to look.
   */
  format: BookFormat | "";
  /** Selected before the book exists, applied one call each after it does. */
  tagIds: number[];
}

/**
 * Nothing chosen yet, on the given shelf.
 *
 * The shelf is a parameter rather than a blank because that is the one field
 * a reset keeps: clearing it would undo the carry-over on every cancel.
 */
export function blankPending(location: string): PendingBook {
  return {
    draft: null,
    coverFile: null,
    isPrivate: false,
    location,
    format: "",
    tagIds: [],
  };
}

/**
 * The pending book as `POST /api/books/scan` takes it.
 *
 * **What the app holds and what the request carries are two vocabularies**,
 * which is the whole reason this is one function rather than an inline
 * spread at each of the two call sites. `isPrivate` is `is_private`; an empty
 * shelf or format is `null` rather than `""`, because the column is nullable
 * and a blank string is a value; `coverFile` and `tagIds` are not in the body
 * at all, since both are separate calls made after the book has an id; and
 * `notFound` and `suggested_tag_ids` are client state that no column matches.
 *
 * `tests/pages/ScanPage/types.test.ts` compares what this produces against the
 * committed `openapi.json`, in both directions.
 */
export function toScanRequest(
  pending: PendingBook & { draft: BookDraft },
): BookCreate {
  const {
    notFound: _notFound,
    suggested_tag_ids: _suggested,
    ...fields
  } = pending.draft;

  return {
    ...fields,
    is_private: pending.isPrivate,
    location: normaliseLocation(pending.location) || null,
    format: pending.format || null,
  };
}

/**
 * The same pending book, as the **copy** endpoint takes it.
 *
 * A sibling of `toScanRequest` rather than a branch of it, because the two
 * endpoints do not accept the same fields: `CopyCreate` takes `condition`,
 * `purchase_price_minor`, `purchase_currency`, `purchase_source`,
 * `purchased_at`, `lending` and `collection_id`, none of which `BookCreate`
 * has, and `BookCreate` takes the whole bibliographic record, which a copy
 * inherits from the book it copies.
 *
 * **It exists because the second writer was a literal.** `addCopy` built its
 * body by hand from two fields, so a new per-copy field reached the scan
 * endpoint through `toScanRequest` and reached this one only if somebody
 * remembered the literal. `tests/pages/ScanPage/types.test.ts` guards both
 * against the schema now, which is the point of having one function per
 * endpoint rather than one per screen.
 *
 * **Only the per-copy fields.** The bibliographic work is taken from the book
 * being copied, which is what stops two rows claiming to be copies of each
 * other while naming different books.
 */
export function toCopyRequest(pending: PendingBook): CopyCreate {
  return {
    location: normaliseLocation(pending.location) || null,
    format: pending.format || null,
  };
}

export function draftFromLookup(lookup: BookLookup): BookDraft {
  return { ...lookup };
}

export function blankDraft(isbn: string): BookDraft {
  return { isbn, title: "", suggested_tag_ids: [], notFound: true };
}

/**
 * Prefill the confirm step from a chosen search result.
 *
 * `notFound` is deliberately left off: the fields came from a real record, so
 * the summary view is right, and someone who wants to change one can still
 * edit it. The ISBN falls back to empty rather than being dropped, because a
 * book found by title genuinely may not have one, and the server treats a
 * blank ISBN as absent rather than invalid.
 */
export function draftFromMatch(match: BookMatch): BookDraft {
  return {
    isbn: match.isbn13 ?? "",
    title: match.title ?? "",
    subtitle: match.subtitle,
    author: match.author,
    publisher: match.publisher,
    year: match.year,
    description: match.description,
    cover_url: match.cover_url,
    // Both sources carry these and the confirm step persists them, so dropping
    // them here would throw away a record already paid for.
    language: match.language,
    page_count: match.page_count,
    series_name: match.series_name,
    series_index: match.series_index,
    // Carried for the same reason, and it is the half of a catalogue heading
    // that survives a language: the confirm step posts these back and the
    // server writes a row each.
    classifications: match.classifications ?? [],
    suggested_tag_ids: match.suggested_tag_ids ?? [],
  };
}
