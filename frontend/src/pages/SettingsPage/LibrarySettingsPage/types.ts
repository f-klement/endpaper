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
 * one function two shapes to tell apart. They share what is common rather than
 * restating it: `boundIdentifiers` is one rule about what may cross the wire and
 * both builders send their identifiers through it.
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
import { identifiersWithScheme, type CalibreBook } from "../../../lib/calibre";
import type {
  StoreBook,
  StoreFormat,
  StoreIdentifier,
  StoreIdentifierScheme,
  StoreOwnership,
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
    // Calibre names no classification, and an empty list is what the endpoint
    // already takes.
    classifications: [],
    // **Calibre's `identifiers` table is a real one and this is where it
    // arrives.** Which of its type strings is which scheme is the reader's
    // decision and is made in `lib/calibre.identifiersWithScheme`; what is left
    // here is the one door every request's identifiers go through.
    //
    // **`IDENTIFIER_LIMIT` is the bound that binds on this path**, and the
    // other three do not: that reader keeps 10 and 12 character values out of a
    // closed alphabet, which is inside the width and cannot hold an invisible
    // character or be empty. It is unbounded in **entries**, one per matching
    // row, and a library filing an ASIN under nine marketplaces would otherwise
    // be a 422 for the whole book. `STORE_SCHEMES`, inside this call, is the
    // other half: it is where a scheme becomes the endpoint's own name for one.
    identifiers: boundIdentifiers(identifiersWithScheme(book.identifiers)),
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
 * The form of a value each scheme's own issuer writes.
 *
 * **A property of the scheme, so it lives at the door both readers go through**
 * rather than in either of them. `lib/calibre.ts` decides which scheme a
 * Calibre type names and `lib/stores.ts` labels what a store adapter read; if
 * one of them folded a value and the other did not, one ASIN spelled two ways
 * would be two rows on one Book, which is what
 * `uq_book_identifiers_book_scheme_value` is keyed to allow and nothing on a
 * screen tells apart. Found by the design seat, 2026-09-11, against a first
 * draft that folded in one reader and claimed the benefit for both.
 *
 * **The alphabet decides, not a preference.** Amazon issues a token with no
 * lower case in it, so upper casing one recovers the value the store issued. A
 * Google Books volume id's alphabet has both cases, so folding one would name a
 * different book, and its entry is the identity for that reason rather than
 * because nobody got to it. A scheme added here has to answer the question.
 *
 * **And a fold reaches only its own alphabet, never `toUpperCase`.** This is
 * the door, and the door is the one place that cannot assume a value was
 * vetted: `kindle.ts` takes the `ASIN` element's text as written, so nothing
 * has proved the token's shape by the time it arrives here.
 *
 * **The reason is that `toUpperCase` is not one function.** It is whatever
 * Unicode table the engine was built against, so two members on browsers of
 * different vintages canonicalise one value two ways and file two rows for one
 * identifier, which is the row this table exists to prevent, reintroduced by
 * the table. Measured on one machine, 2026-09-11, over all 1,112,064 non
 * surrogate code points: node 24.10.0 at Unicode 16.0 folds 1,552 of them and
 * bun 1.4.2 at Unicode 17.0 folds 1,580, a strict superset by set difference,
 * 28 one way and none the other. Two engines is two tables, which is the claim.
 * **`[a-z]` is the same 26 in every version there will ever be**, and swept the
 * same way on both engines it changes 26, none outside `[a-z]` and none
 * changing length.
 *
 * The count also says what a wide fold would touch: 1,526 of node's 1,552 are
 * outside `[a-z]`, so it rewrites characters no scheme here has a claim on,
 * which is the refusal the whitespace paragraph below already makes. `parseIsbn`
 * is the precedent and it points the same way: it normalises only what it has
 * proved. Found by the design seat, measured by the security seat.
 *
 * Total over `StoreIdentifierScheme`, `STORE_SCHEMES`' discipline.
 */
const CANONICAL_VALUE: Record<
  StoreIdentifierScheme,
  (value: string) => string
> = {
  asin: (value) => value.replace(/[a-z]/g, (one) => one.toUpperCase()),
  google_books: (value) => value,
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
 * `boundIdentifiers` exists to prevent. No store produces more than one today;
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
 * The identifiers the endpoint will take, out of what a reader gave.
 *
 * **The bound, not the mapping.** Which scheme a row belongs to is its reader's
 * decision and is made there: a store's adapter labels what it read, and
 * `lib/calibre.identifiersWithScheme` reads a Calibre type. What is left is one
 * rule about what may cross the wire, and both readers reach it.
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
 * **Two things happen here that are not refusals**, and both are here rather
 * than in a reader because both are properties of the scheme: a value is put in
 * the form its issuer writes (`CANONICAL_VALUE`), and a repeat of one already
 * kept is folded. The fold is paired with the ceiling above it: that ceiling
 * truncates, so a repeat left standing costs the book a different identifier.
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
export function boundIdentifiers(
  identifiers: readonly StoreIdentifier[],
): BookIdentifierIn[] {
  const kept: BookIdentifierIn[] = [];
  const folded = new Set<string>();
  for (const identifier of identifiers) {
    if (kept.length >= IDENTIFIER_LIMIT) break;
    const scheme = STORE_SCHEMES[identifier.scheme];
    // **Canonical before the bounds, and that is the rule rather than a
    // detail.** What is measured has to be what is sent, the reason the trim
    // runs first. **Nothing today depends on it**, because neither fold can
    // change a length, and what makes that true is `CANONICAL_VALUE` reaching
    // only `[a-z]`: a fold spelled `toUpperCase` grows 102 of the 1,112,064 non
    // surrogate code points, 16 of them threefold (U+0390 among them), so a
    // value at the ceiling would canonicalise past it and lose the book. Those
    // two counts are the ones both engines agreed on.
    const value = CANONICAL_VALUE[identifier.scheme](identifier.value.trim());
    // Code points, never UTF-16 units, `bookBounds.boundText`'s measurement:
    // the ceiling belongs to a Python `str` and to a SQLite column and both
    // count code points.
    if (value.length === 0 || [...value].length > IDENTIFIER_VALUE_MAX)
      continue;
    if (REFUSED_INSIDE_AN_IDENTIFIER.test(value)) continue;
    // **The fold is here because the ceiling is here.** It is not to save the
    // server work: `identifiers.add_identifiers` drops an in payload repeat as
    // well as one the Book already carries, and says so. It is that
    // `IDENTIFIER_LIMIT` truncates before the server ever sees the payload, so
    // without this a library filing one ASIN under fifteen marketplaces spends
    // every slot on one fact and its volume id never crosses the wire.
    //
    // **A set and not a scan over `kept`**, though `kept` is capped at eight
    // immediately above, so a scan would be linear in rows here today. Its
    // bound would be a neighbouring rule rather than its own, and the same scan
    // in a loop without that cap cost 564,831ms on 200,000 rows for one book,
    // which is a row count `lib/sqlite.MAX_ROWS_PER_QUERY` admits and which
    // this runs on the browser's main thread. Both figures are one core of the
    // machine this repository is developed on, 2026-09-11, the first by the
    // security seat: with the set, 200,000 rows for one book is 69ms all
    // distinct and 257ms all the same value.
    //
    // The separator cannot occur inside either half: both scheme names are
    // alphanumeric with an underscore, and a value carrying whitespace was
    // refused two lines up.
    const key = `${scheme} ${value}`;
    if (folded.has(key)) continue;
    folded.add(key);
    kept.push({ scheme, value });
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
 * a per entry rule rather than a per field one: see `boundIdentifiers`.
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
/**
 * A store's word for a claim, in the endpoint's word for it.
 *
 * A total `Record`, `STORE_FORMATS`' rule: `StoreOwnership` gaining a member
 * with no answer here is a compile error rather than a book filed as whatever
 * the fallback said. It has two members and not `books.ownership`'s third,
 * because `not_owned` is a thing a member says and never a thing a catalogue
 * says.
 */
const STORE_OWNERSHIP: Record<StoreOwnership, OwnershipStatus> = {
  owned: OwnershipStatus.owned,
  unknown: OwnershipStatus.unknown,
};

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
    identifiers: boundIdentifiers(book.identifiers),
    location: null,
    is_private: false,
    classifications: [],
    // **The row's own answer where it has one, the library's where it does
    // not**, and that precedence is the whole of this expression.
    //
    // `unknown` rather than omitting the field, because omitting it is what the
    // default means and the default is `owned`. A store that could not say has
    // to say so.
    //
    // **Per row wins because it is the narrower claim.** `kobo.ts` reads
    // `Accessibility` and knows a Kobo Plus title from a purchase, so a library
    // wide `true` would overwrite a real `unknown` with a guess. A store with
    // nothing per row to say leaves `ownership` null and its books take
    // `ownershipStated`, which is what Adobe Digital Editions does: that
    // catalogue records a three week loan and a purchase identically.
    ownership:
      STORE_OWNERSHIP[
        book.ownership ?? (ownershipStated ? "owned" : "unknown")
      ],
  };
}
