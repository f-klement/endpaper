import { BookFormat } from "../../api/generated/model";
import type {
  BookCreate,
  BookLookup,
  BookMatch,
  CopyCreate,
} from "../../api/generated/model";
import { AUTHOR_SEPARATOR, boundNumber, boundText } from "../../lib/bookBounds";
import { normaliseLocation } from "../../lib/lastLocation";
import type { OpfRecord } from "../../lib/opf";
import type { NameClues } from "../../lib/fileName";
import type { AudiobookGroup } from "../../lib/audiobookGroups";

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

/**
 * The confirm step, prefilled from a file the member picked.
 *
 * A sibling of `draftFromLookup` and `draftFromMatch` rather than a branch of
 * either, and it lives here for the reason those do: this module is where what
 * the app holds becomes what the request carries. **Every value is bounded on
 * the way through**, because the file is untrusted input and the alternative is
 * a 422 on the member's own batch rather than a book with one field missing.
 * `lib/bookBounds.ts` carries that rule and the reason for the cut or drop
 * split.
 *
 * `notFound` is set, which is what puts the confirm step into editable fields:
 * no catalogue was asked, so what is on screen is the file's own claim and the
 * member is the one who can correct it.
 *
 * **No cover, and that is scope rather than a rule.** An EPUB carries a cover
 * image inside the archive, and an image is not the book: `POST
 * /api/books/{id}/cover` already takes one. Lifting it out is a second entry
 * read with its own bounds and a second request per book, and whether an import
 * should make them is a decision about the import flow rather than about this
 * reader.
 */
export function draftFromFile(record: OpfRecord): BookDraft {
  return {
    isbn: boundText("isbn", record.isbn) ?? "",
    title: boundText("title", record.title) ?? "",
    subtitle: boundText("subtitle", record.subtitle),
    author: boundText("author", record.authors.join(AUTHOR_SEPARATOR)),
    publisher: boundText("publisher", record.publisher),
    year: boundNumber("year", record.year),
    description: boundText("description", record.description),
    language: boundText("language", record.language),
    series_name: boundText("series_name", record.seriesName),
    series_index: boundNumber("series_index", record.seriesIndex),
    // The file names neither, and an empty list is what the confirm step and
    // the batch both already handle.
    classifications: [],
    suggested_tag_ids: [],
    notFound: true,
  };
}

/**
 * The confirm step, prefilled from what a file's **name** said.
 *
 * The third sibling of `draftFromLookup` and `draftFromMatch`, and it is here
 * for the reason the other two are: this module is where what the app holds
 * becomes what the request carries. Every value is bounded on the way through
 * for the reason `draftFromFile` states, and more so: a name is somebody else's
 * text with no producer at all behind it.
 *
 * **A name answers four of the minimum field set and the exclusion is the
 * point**: title, author, ISBN and year, and never publisher, language, series,
 * description or page count. That is what the catalogue lookup is for, and what
 * a member sees when the catalogue answers nothing is a row that says only what
 * the name said.
 *
 * `notFound` is set, so the confirm step shows editable fields: no catalogue has
 * been asked yet, and the member is the one who can correct a name.
 */
export function draftFromName(clues: NameClues): BookDraft {
  return {
    isbn: boundText("isbn", clues.isbn) ?? "",
    title: boundText("title", clues.title) ?? "",
    author: boundText("author", clues.author),
    year: boundNumber("year", clues.year),
    // A name names neither, and an empty list is what the confirm step and the
    // batch both already handle.
    classifications: [],
    suggested_tag_ids: [],
    notFound: true,
  };
}

/**
 * The confirm step, prefilled from **several files that are one audiobook**.
 *
 * The fourth sibling of `draftFromLookup`, and the only one whose input is more
 * than one file: an audiobook is usually a folder of chapters, and
 * `lib/audiobookGroups.ts` holds the rule that decided which ones.
 *
 * **The album is the title and the artists are the authors**, which is what the
 * corpus says and is also why this is a function rather than a spread: the
 * mapping is a claim about real files and it belongs beside the other three.
 *
 * **Every distinct artist, joined**, because a collection is one audiobook by
 * ten writers and taking the first would file nine of them under the wrong one.
 * `boundText` cuts the line at what `BookCreate.author` holds.
 *
 * **`null` when the files named no book**, and the caller then derives the same
 * draft from the folder's name instead. Returning a blank title here would be a
 * row the API refuses in the middle of somebody's batch.
 *
 * **No year**, and it is the one omission worth naming here as well as at the
 * reader: an audiobook's date tag is the year of the recording, not of the
 * book. `lib/audiobook.ts` carries the measurement.
 */
export function draftFromAudiobook(group: AudiobookGroup): BookDraft | null {
  const title = boundText("title", group.album ?? group.title);
  if (title === null) return null;
  return {
    isbn: "",
    title,
    author: boundText("author", group.authors.join(AUTHOR_SEPARATOR)),
    classifications: [],
    suggested_tag_ids: [],
    notFound: true,
  };
}
