/**
 * What a record read off somebody's own library becomes on the wire.
 *
 * The same job `ScanPage/types.ts` does for a scanned or picked book, in the
 * page folder that owns the other end of it: this module is where what a reader
 * produced becomes what a request carries. `lib/calibre.ts` and `lib/stores.ts`
 * stay pure and know nothing about the API, which is what lets them be tested
 * against a database or an archive rather than against a schema.
 *
 * **Two builders and not one**, because Calibre answers a `CalibreBook` and a
 * store answers a `StoreBook`, and the second is already the common record
 * `lib/stores.ts` adapts every store into. Merging them would mean either
 * putting Calibre through that adapter, which is a different ticket, or giving
 * one function two shapes to tell apart.
 *
 * **Every value is bounded on the way through.** A `metadata.db` is somebody
 * else's data whatever route it took to the disk it is on, so the rule is the
 * one `lib/bookBounds.ts` carries: a value the column cannot hold loses that
 * field, never the book, and never turns into a 422 in the middle of a member's
 * own import of nine hundred books.
 */

import type {
  BookCreate,
  BookIdentifierIn,
} from "../../../api/generated/model";
import {
  BookFormat,
  BookIdentifierScheme,
  OwnershipStatus,
} from "../../../api/generated/model";
import {
  AUTHOR_SEPARATOR,
  boundNumber,
  boundText,
} from "../../../lib/bookBounds";
import type { CalibreBook } from "../../../lib/calibre";
import type {
  StoreBook,
  StoreFormat,
  StoreIdentifier,
  StoreIdentifierScheme,
} from "../../../lib/stores";

/**
 * Calibre formats that mean a recording rather than a book to read.
 *
 * Calibre files an audiobook as an ordinary book with an audio file attached,
 * so the format column is the only thing that separates the two. Everything
 * else with a file is an ebook, and a record with no file at all is neither:
 * see `formatOf`.
 */
const AUDIO_FORMATS = new Set(["M4A", "M4B", "MP3", "OGG", "OPUS", "AAC"]);

/**
 * Calibre formats that mean a comic rather than a book to read.
 *
 * The same shape as the audio set above and for the same reason: Calibre files
 * a comic as an ordinary book with a comic file attached, so the format column
 * is the only thing that separates it. **`CBR` is here although this app will
 * not parse one**, because `formatOf` is answering what a copy is rather than
 * what can be read: the refusal in `lib/cbz.ts` is a refusal of a parser, and
 * `csv_import.FORMAT_GUESSES` already reads the word the same way.
 */
const COMIC_FORMATS = new Set(["CBZ", "CBR", "CB7", "CBT"]);

/**
 * What kind of object this copy is, or `null` when the library does not say.
 *
 * **A book with no file is not an ebook**, and answering `ebook` for one would
 * assert something the library does not: a Calibre record with no file is a
 * book somebody catalogued, which is exactly what an unowned record looks like
 * here. `null` is the value the column takes for "not said".
 */
export function formatOf(book: CalibreBook): BookFormat | null {
  if (book.formats.length === 0) return null;
  const every = (kinds: ReadonlySet<string>) =>
    book.formats.every((format) => kinds.has(format.trim().toUpperCase()));

  // **`every`, not `some`, for both**, which is the rule the audio arm already
  // had: a record carrying an EPUB and a CBZ is a book that also has a comic
  // file, and calling the whole record a comic on the strength of one file
  // would be answering about the file rather than about the copy.
  if (every(AUDIO_FORMATS)) return BookFormat.audiobook;
  // Without this a CBZ imported from a Calibre library is an ebook while the
  // same file picked on the scan page is a comic, which is one question with
  // two answers. `lib/fileName.FORMAT_FOR_EXTENSION` is the other half.
  if (every(COMIC_FORMATS)) return BookFormat.comic;
  return BookFormat.ebook;
}

/**
 * One Calibre book as `POST /api/books/scan` takes it, or `null`.
 *
 * `null` for a book with no title, which is the one field the API requires. A
 * Calibre library carries them: `Unknown` is what Calibre writes where nobody
 * said, `lib/calibre.ts` refuses that placeholder by name, and the record left
 * over has nothing to file it under. Reported before the write rather than left
 * to a 422 halfway through the batch.
 *
 * **No cover, no tags, no files, and that is scope rather than a rule.** Each
 * is a second request a book against a route that already makes one; whether an
 * import should make them is a decision about the import flow. `lib/calibre.ts`
 * lists what the reader deliberately leaves behind and why.
 */
export function toBookCreate(book: CalibreBook): BookCreate | null {
  const title = boundText("title", book.title);
  if (title === null) return null;

  return {
    title,
    author: boundText("author", book.authors.join(AUTHOR_SEPARATOR)),
    isbn: boundText("isbn", book.isbn),
    publisher: boundText("publisher", book.publisher),
    year: boundNumber("year", book.year),
    description: boundText("description", book.description),
    language: boundText("language", book.language),
    series_name: boundText("series_name", book.seriesName),
    series_index: boundNumber("series_index", book.seriesIndex),
    format: formatOf(book),
    // Calibre has no shelf and no notion of a private book, so both take the
    // value the column has for "not said" rather than one invented here.
    location: null,
    is_private: false,
    // The library names none of the three, and an empty list is what the
    // endpoint already takes. **Calibre's `identifiers` table is a real one and
    // this is not it**: `lib/calibre.ts` reads the ISBN out of it and nothing
    // else, so what a row here could carry is a decision about that reader
    // rather than a line in this builder.
    classifications: [],
    identifiers: [],
  };
}

/**
 * What a store's answer about a copy is called on the wire.
 *
 * **A total `Record` rather than a cast**, although the two vocabularies spell
 * their members identically today: a kind added to `StoreFormat` with no home
 * here is a compile error, where a cast would send the endpoint a value its
 * enum does not have and get a 422 in the middle of somebody's device.
 *
 * It sits here rather than in `lib/stores.ts` because that module may not name
 * the API at all: `tests/houseRules.test.ts` denies every reader in that
 * directory the generated client, and this translation is the seam that rule
 * assumes exists.
 */
const STORE_FORMATS: Record<StoreFormat, BookFormat> = {
  ebook: BookFormat.ebook,
  audiobook: BookFormat.audiobook,
  comic: BookFormat.comic,
};

/**
 * What a store's name for a book is called on the wire.
 *
 * **A total `Record` rather than a cast**, `STORE_FORMATS`' rule and its
 * reason: the two vocabularies spell their members identically today, and a
 * scheme added to `StoreIdentifierScheme` with no home here is a compile error
 * where a cast would send the endpoint a value its enum does not have and get a
 * 422 in the middle of somebody's device.
 *
 * It sits here for `STORE_FORMATS`' other reason too: `lib/stores.ts` may not
 * name the API at all.
 */
const STORE_SCHEMES: Record<StoreIdentifierScheme, BookIdentifierScheme> = {
  asin: BookIdentifierScheme.asin,
  google_books: BookIdentifierScheme.google_books,
};

/**
 * How wide an identifier the column takes.
 *
 * **Not in `lib/bookBounds.ts`**, and the split is where that module's own rule
 * puts it: it holds `BookCreate`'s scalar `maxLength`s, keyed by field name, and
 * this bound is on the `value` inside a list rather than on a field. Recomputed
 * from `openapi.json` by this page's tests rather than restated, which is the
 * discipline `bookBounds.ts` keeps for every number in it.
 */
const IDENTIFIER_VALUE_MAX = 60;

/**
 * How many identifiers one request may carry.
 *
 * `BookCreate.identifiers` declares `maxItems`, and a payload over it is a 422
 * for the **whole book** rather than for the extra entry, which is the outcome
 * `storeIdentifiers` exists to prevent. No store produces more than one today;
 * this binds the case where one grows to.
 *
 * Recomputed from `openapi.json` beside the width above, for its reason.
 */
const IDENTIFIER_LIMIT = 8;

/**
 * Every character the endpoint refuses inside an identifier.
 *
 * **The families, not a list of spellings**, which is what lets this be checked
 * against the server's rule rather than against a set of examples somebody
 * thought of. `BookIdentifierIn.an_opaque_token` refuses whitespace and every
 * character in the Unicode categories `Cc` and `Cf`; this is that same rule in
 * the one notation JavaScript has for it.
 *
 * **It has to be the same rule, and a narrower one here costs the book.** This
 * filter used to be `/\s/u` alone. Measured over all 1,112,064 non surrogate
 * code points by both critic seats independently: **229 passed this filter and
 * were refused by the server**, among them SOFT HYPHEN, ZERO WIDTH SPACE, NUL
 * and U+0085, and none went the other way. `importing.writeBooks` files the 422
 * under `failures`, so each one lost a book. With the categories added the two
 * rules are equal sets, 0 code points in either direction.
 *
 * Wider than the server's would be safe and is not free either: it would drop
 * an identifier the endpoint would have taken, silently.
 */
const REFUSED_INSIDE_AN_IDENTIFIER = /[\s\p{Cc}\p{Cf}]/u;

/**
 * The identifiers the endpoint will take, out of what a store gave.
 *
 * **A value the endpoint would refuse loses that identifier, never the book**,
 * which is `lib/bookBounds.ts`' rule applied to a field it does not cover: an
 * import of nine hundred books must not turn into a 422 over one row whose
 * catalogue held something odd. The Kindle catalogue is where that can happen:
 * `kindle.ts` takes the `ASIN` element's text as written, so the value is
 * whatever that file said.
 *
 * **So this has to refuse everything the endpoint refuses**, which is four
 * rules and not three: empty, too wide, anything invisible inside, and more
 * entries than one request may carry. A rule missing here does not fail
 * anywhere; it turns into a lost book on somebody's own import.
 *
 * **Trimmed first, and the server does not**: `max_length` is a field
 * constraint and runs before `BookIdentifierIn`'s validator, so the server
 * measures what arrived and this measures what it is about to send. Trimming
 * here is therefore the thing that makes a padded value survive at all, rather
 * than a copy of the server's order. The two agree on every value inside the
 * budget, which is every value any reader here produces: the widest is 12
 * characters.
 *
 * **Whitespace inside is dropped rather than removed**, which is the server's
 * rule and the reason for it: an identifier is an opaque token, so whitespace
 * in the middle means the reader picked up something that is not the
 * identifier, and closing it up here would send a value this app invented.
 */
export function storeIdentifiers(
  identifiers: readonly StoreIdentifier[],
): BookIdentifierIn[] {
  const kept: BookIdentifierIn[] = [];
  for (const identifier of identifiers) {
    if (kept.length >= IDENTIFIER_LIMIT) break;
    const value = identifier.value.trim();
    // Code points, never UTF-16 units, `bookBounds.boundText`'s measurement:
    // the ceiling belongs to a Python `str` and to a SQLite column and both
    // count code points.
    if (value.length === 0 || [...value].length > IDENTIFIER_VALUE_MAX)
      continue;
    if (REFUSED_INSIDE_AN_IDENTIFIER.test(value)) continue;
    kept.push({ scheme: STORE_SCHEMES[identifier.scheme], value });
  }
  return kept;
}

/**
 * One book off a store as `POST /api/books/scan` takes it, or `null`.
 *
 * `null` for a book with no title, `toBookCreate`'s rule and its reason: the
 * API requires one and a record without it has nothing to file it under.
 * Reported in the preview rather than left to a 422 halfway through a device.
 *
 * **The store already said what kind of copy this is**, so `format` is carried
 * rather than derived. `lib/stores.ts` is where each store answers that
 * question, because the answer is the store's: a Kobo says it in a mime type
 * and a Takeout says it by the file having read as an EPUB.
 *
 * **`is_private` is `false` and `location` is `null`** for `toBookCreate`'s
 * reason: no store here carries a shelf or a notion of a private book, so both
 * take the value the column has for "not said" rather than one invented here.
 *
 * **`identifiers` is the one field that is not one line**, because a list needs
 * a per entry rule rather than a per field one: see `storeIdentifiers`. It is
 * also the one field a Calibre library has no counterpart for, which is why
 * `toBookCreate` above sends none.
 */
/** One book a store read, paired with what that store could say about owning it. */
export interface StoreBookFromSource {
  readonly book: StoreBook;
  readonly ownershipStated: boolean;
}

/**
 * @param ownershipStated Whether the store established that the member owns
 * what it listed. `false` sends `unknown`, which is what stops a three week
 * Adobe Digital Editions loan being written as a book somebody owns.
 */
export function storeToBookCreate(
  book: StoreBook,
  ownershipStated: boolean,
): BookCreate | null {
  const title = boundText("title", book.title);
  if (title === null) return null;

  return {
    title,
    author: boundText("author", book.authors.join(AUTHOR_SEPARATOR)),
    isbn: boundText("isbn", book.isbn),
    publisher: boundText("publisher", book.publisher),
    year: boundNumber("year", book.year),
    description: boundText("description", book.description),
    language: boundText("language", book.language),
    series_name: boundText("series_name", book.seriesName),
    series_index: boundNumber("series_index", book.seriesIndex),
    format: book.format === null ? null : STORE_FORMATS[book.format],
    identifiers: storeIdentifiers(book.identifiers),
    location: null,
    is_private: false,
    classifications: [],
    // **`unknown` rather than omitting the field**, because omitting it is what
    // the default means and the default is `owned`. A store that could not say
    // has to say so.
    ownership: ownershipStated
      ? OwnershipStatus.owned
      : OwnershipStatus.unknown,
  };
}
