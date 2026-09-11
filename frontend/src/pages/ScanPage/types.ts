import { BookFormat } from "../../api/generated/model";
import type {
  BookCreate,
  BookIdentifierIn,
  BookLookup,
  BookMatch,
  CopyCreate,
} from "../../api/generated/model";
import { AUTHOR_SEPARATOR, boundNumber, boundText } from "../../lib/bookBounds";
import { normaliseLocation } from "../../lib/lastLocation";
import type { FileIdentifier, FileMetadata } from "../../lib/fileReaders";
import type { StoreIdentifier, StoreIdentifierScheme } from "../../lib/stores";
import { boundIdentifiers } from "../SettingsPage/LibrarySettingsPage/types";
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
  /**
   * What the file said this book is called elsewhere, already bounded.
   *
   * **Not part of `BookLookup`, because no catalogue answers one.** It is here
   * rather than beside `coverFile` on the pending book for the opposite reason
   * to that one: a cover is a second request after the book exists and this is
   * a field of the same body, so it rides the draft the confirm step edits and
   * reaches `toScanRequest` with the rest.
   *
   * Absent on every draft but a file's, which is what keeps it off the wire for
   * a barcode: `lib/isbn.ts` and the two catalogues name no store's number.
   */
  identifiers?: BookIdentifierIn[];
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
 * Labels a file may write that name a scheme this app stores.
 *
 * **Four spellings, closed, and every other label a real library carries is
 * refused.** The set is small because it was measured rather than reasoned
 * about: over 931 EPUBs of the household's own library, none unreadable, the
 * `opf:scheme` values are `uuid` in either case 79 times, `calibre` 51, the
 * four ISBN spellings 47 together, `MOBI-ASIN` 31, `ASIN` 4, `AMAZON` 4, `URI`
 * 4, `BARNESNOBLE` 2, `GOODREADS` 2, and two that are not scheme names at all.
 * **Three of those fifteen spellings are admitted and twelve are refused.**
 *
 * **`GOOGLE` is the fourth and occurs in none of the 931**, which is stated
 * because it is the one admission no count supports. It is admitted on the
 * mechanism rather than on a measurement: Calibre writes that type beside a
 * book, and a conversion carries a type into the package document, which is how
 * `GOODREADS` and `BARNESNOBLE` reached files whose producer has no such
 * notion.
 *
 * **`MOBI-ASIN` is admitted and judged by its value, which is a departure from
 * calibre's own default and not a correction of it.** Calibre refuses that type
 * unless asked, `use_mobi_asin` being `False`, with a help text warning that the
 * value may be another store's, and as a blanket rule over a whole field that
 * is right: the type names where a value was found, EXTH record 113, whose own
 * comment in calibre's reader says `ASIN or other id`. Measured over the same
 * library, the two halves separate by length: **16 values are a `B` followed by
 * nine alphanumerics and 15 are a uuid or hex string of 32 to 40 characters**,
 * which is the filler calibre mints into that record when a file has no ASIN.
 * A label cannot tell those apart and `PRODUCED_VALUE` can, so the row is kept
 * on the value and never on the label alone. Owner's decision, 2026-09-11.
 *
 * **What that buys and what it does not.** This library's filler is refused on
 * its length, and `lib/calibre.identifiersWithScheme` records the limit that
 * leaves: the shape cannot tell a ten character ASIN from a ten character
 * something else, which is why the decline there is on the type. So a filler
 * ten characters long would be kept, and that is the risk this admission
 * accepts rather than one it closes.
 *
 * **Why each of the refused spellings is refused**, stated here because a
 * refusal nobody wrote down is a gap somebody fills back in:
 *
 * - `uuid` in either case, `calibre` and `URI`. No reader here produces a value
 *   anything consumes, which is `BookIdentifierScheme`'s own gate on a member.
 * - The four ISBN spellings. An ISBN belongs in `books.isbn`, and
 *   `opf.readIsbn` already puts it there having tested its check digit.
 * - `GOODREADS` and `BARNESNOBLE`, for the reason `goodreads` was refused a
 *   scheme member: nothing here reads one.
 * - `9781641701709` and `URN:ISBN/9781407061597`. **Two of the fifteen
 *   spellings a real library carries are an identifier in the slot where a
 *   scheme name goes**, which is the argument for admitting a closed set
 *   rather than parsing what is found.
 *
 * **EPUB 3 says this in a second vocabulary, and none of it lands here.** An
 * `identifier-type` refinement carries a number from ONIX code list 5, measured
 * over the same library as `15` 28 times, `22` 4 times and `uuid` 3 times. A
 * number names no store, so nothing here could tell which one a proprietary
 * code meant, and `opf.readIdentifiers` puts both spellings in one field, so
 * the closed set refuses the numbers without an arm of its own.
 *
 * **This vocabulary and `lib/calibre.CALIBRE_TYPES` differ in both directions,
 * deliberately, and the reason is the producer.** That rule admits a
 * marketplace suffix, `amazon_de` and its family, because the calibre plugin
 * writing that column was read and every such key holds an ASIN by
 * construction; no suffixed spelling occurs in the 931, so this one has no
 * population to admit it on. This rule admits `mobi-asin`, which that one
 * refuses on the type, because the value rule reaches a distinction a Calibre
 * type column cannot make on its own.
 */
const LABELS_OF_SCHEME: Record<StoreIdentifierScheme, readonly string[]> = {
  asin: ["asin", "amazon", "mobi-asin"],
  google_books: ["google"],
};

/**
 * The same, keyed the way a file is read: one lower cased label to one scheme.
 *
 * A `Map` rather than an object, so a file labelling itself `__proto__` or
 * `constructor` reaches no inherited member.
 */
const SCHEME_OF_LABEL = new Map<string, StoreIdentifierScheme>(
  Object.entries(LABELS_OF_SCHEME).flatMap(([scheme, labels]) =>
    labels.map((label) => [label, scheme as StoreIdentifierScheme] as const),
  ),
);

/**
 * What a value has to look like for the scheme's own readers to have made it.
 *
 * **The same fact `lib/calibre.PRODUCED_VALUE` holds**, because it is a
 * property of the scheme rather than of whoever wrote the label: ten characters
 * of Amazon's alphabet for an ASIN, twelve of the URL safe alphabet for a
 * volume id. This module's mirrored test reads both out of source and requires
 * them to be the same text, which is what `takeout.VOLUME_ID` and that table
 * already do for the Google half. A single home for it beside
 * `StoreIdentifierScheme` is raised rather than taken here.
 *
 * **It is what carries `mobi-asin`**, so the shape is load bearing rather than
 * a sanity check: the label is admitted and the value decides, 16 of that
 * library's 31 such rows kept and 15 refused. **The same ten characters as the
 * other three labels**, and nothing measured supports a narrower rule for this
 * one: what refuses those 15 is their length.
 *
 * **No matcher for the filler, which is the deliberate half.** Recognising a
 * uuid would be an inclusion list over an open set, and calibre is free to mint
 * a different filler tomorrow. A rule saying what an Amazon code is refuses
 * every filler that is not ten characters of this alphabet, which is every
 * filler that library holds and not every filler there could be.
 *
 * **The ASIN alphabet is not narrowed to a `B` prefix.** Amazon issues a
 * printed edition's ISBN-10 as its ASIN, and in that library **four of the
 * eight `ASIN` and `AMAZON` values are exactly that**, so a `B` rule would drop
 * half of what this admits. What it costs is that such a value is also the
 * book's ISBN.
 *
 * **Two columns and two different tokens, which is the answer to that.**
 * `opf.readIsbn` runs every candidate through `parseIsbn`, which answers the
 * canonical ISBN-13, so the book carries the thirteen digit form while the
 * identifier row carries the ten character one Amazon issued. Neither is a copy
 * of the other, and the row records what Amazon knows the book by rather than
 * restating the edition's number. **Written without the worked pair**: the
 * first draft carried one and its ISBN-13 was wrong, which is what a literal
 * nothing recomputes does.
 *
 * **A padded value is refused rather than trimmed.** The shape is anchored and
 * whitespace is not in either alphabet, and closing one up would send a value
 * this app invented rather than one the file carried.
 *
 * Total over `StoreIdentifierScheme`, `LABELS_OF_SCHEME`' discipline: a scheme
 * added to that union with no shape here is a compile error rather than a label
 * admitted on its name alone.
 */
const PRODUCED_VALUE: Record<StoreIdentifierScheme, RegExp> = {
  asin: /^[A-Za-z0-9]{10}$/,
  google_books: /^[A-Za-z0-9_-]{12}$/,
};

/**
 * The identifiers a picked file labelled with a scheme this app stores.
 *
 * **A name rule decides the scheme and a value rule decides whether the row is
 * kept**, which is `lib/calibre.identifiersWithScheme`'s shape and its reason: a
 * label is a claim a file makes, and a file is untrusted input. Both rules are
 * above.
 *
 * **The label is trimmed and the value is not.** `opf.ts` reads `opf:scheme`
 * with `getAttribute`, which trims nothing, while its EPUB 3 route and every
 * other reader in the family hand over a label that is already trimmed; the
 * value needs no trim because `PRODUCED_VALUE` refuses whitespace outright.
 * Lower cased for the reason calibre's own readers lower case a type: the
 * spelling is whatever a producer felt like, and this library holds `ASIN`
 * beside `isbn`.
 *
 * **One entry a matching label, folded and capped nowhere here.**
 * `LibrarySettingsPage/types.boundIdentifiers` is where a repeat of one scheme
 * and value becomes one row and where the request's ceiling of eight is, and
 * the two belong together: the ceiling truncates, so a repeat left standing
 * would spend a slot. Two labels naming **different** values stay two rows,
 * which is what `models.BookIdentifier` says two rows are for.
 *
 * **A file carrying no label this admits yields an empty list and never a
 * missing book.** That is `lib/bookBounds.ts`' rule on a field it does not
 * cover, and it is the ordinary outcome. Across the 931 files measured the
 * admitted labels occur 39 times, of which the value rule keeps 24.
 */
export function identifiersFromFile(
  identifiers: readonly FileIdentifier[],
): StoreIdentifier[] {
  const kept: StoreIdentifier[] = [];
  for (const identifier of identifiers) {
    if (identifier.scheme === null) continue;
    const scheme = SCHEME_OF_LABEL.get(identifier.scheme.trim().toLowerCase());
    if (scheme === undefined) continue;
    if (!PRODUCED_VALUE[scheme].test(identifier.value)) continue;
    kept.push({ scheme, value: identifier.value });
  }
  return kept;
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
 * **The identifiers a file labelled `ASIN`, `AMAZON` or `GOOGLE` are sent, and
 * every other label is refused.** `identifiersFromFile` is that rule and says
 * what each refusal was measured against; `boundIdentifiers` is the same door
 * the store import passes through, so what may cross the wire is one rule
 * rather than a second copy of four.
 *
 * **Four of the five readers can still produce nothing this admits**, and that
 * is a property of the code rather than of a corpus. Three write `ISBN` and
 * `cbz.ts` writes `GTIN`, a barcode that is an ISBN on a collected volume and a
 * product code on an issue; `BookIdentifierScheme` has a member for neither, an
 * ISBN being the thing that enum exists to keep out of itself. **The fifth is
 * `opf.ts`, which repeats whatever label the file wrote**, so the whole of this
 * flow's yield is what an EPUB says about itself.
 *
 * `tests/lib/fileReaders.test.ts` fails if a reader starts writing a scheme
 * this app stores instead of repeating the file's own label, which is what
 * stops a reader inventing a row out of a record that names a different fact.
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
export function draftFromFile(record: FileMetadata): BookDraft {
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
    // **Two rules and not one**, the same pair the Calibre import builds with:
    // which scheme a label names is this flow's decision and what may cross the
    // wire is one door both flows pass.
    identifiers: boundIdentifiers(identifiersFromFile(record.identifiers)),
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
