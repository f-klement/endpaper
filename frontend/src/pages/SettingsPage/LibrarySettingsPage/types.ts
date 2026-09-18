/**
 * What a record read off somebody's own library becomes on the wire.
 *
 * The same job `ScanPage/types.ts` does for a scanned or picked book, in the
 * page folder that owns the other end of it. `lib/calibre.ts` and
 * `lib/stores.ts` stay pure and know nothing about the API, which is what lets
 * them be tested against a database or an archive rather than against a schema.
 *
 * **Two builders and not one**, because Calibre answers a `CalibreBook` and a
 * store answers a `StoreBook`, and what differs between them is not
 * bibliographic: a store says what kind of copy it holds and whether the member
 * owns it, and a Calibre library says neither and has a file list to derive the
 * first from. Merging them would give one function two shapes to tell apart to
 * no end.
 *
 * **What they share they do not restate.** Both are a `SourceRecord`, so the
 * fields every source states go through `lib/bookRequest.boundRecord`, and
 * both send their identifiers through `boundIdentifiers` beside it. What is
 * written out here is what one of them can say and the other cannot.
 *
 * **Every value is bounded on the way through.** A `metadata.db` is somebody
 * else's data whatever route it took to the disk it is on, so the rule is the
 * one `lib/bookBounds.ts` carries: a value the column cannot hold loses that
 * field, never the book, and never turns into a 422 in the middle of a member's
 * own import of nine hundred books.
 */

import type { BookCreate } from "../../../api/generated/model";
import { BookFormat, OwnershipStatus } from "../../../api/generated/model";
import { boundIdentifiers, boundRecord } from "../../../lib/bookRequest";
import { identifiersWithScheme, type CalibreBook } from "../../../lib/calibre";
import type {
  StoreBook,
  StoreFormat,
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
 * to a 422 halfway through the batch. `lib/bookRequest.boundRecord` answers
 * `null` for the title and says nothing about what that means, because the
 * three callers mean three different things by it.
 *
 * **No cover, no tags, no files, and that is scope rather than a rule.** Each
 * is a second request a book against a route that already makes one; whether an
 * import should make them is a decision about the import flow. `lib/calibre.ts`
 * lists what the reader deliberately leaves behind and why.
 */
export function toBookCreate(book: CalibreBook): BookCreate | null {
  const bound = boundRecord(book);
  if (bound.title === null) return null;

  return {
    ...bound,
    title: bound.title,
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
 * assumes exists. `lib/bookRequest.STORE_SCHEMES` is the same discipline for
 * the other enum a store answers with, and it is there rather than here
 * because the scan page reaches it too.
 */
const STORE_FORMATS: Record<StoreFormat, BookFormat> = {
  ebook: BookFormat.ebook,
  audiobook: BookFormat.audiobook,
  comic: BookFormat.comic,
};

/** One book a store read, paired with what that store could say about owning it. */
export interface StoreBookFromSource {
  readonly book: StoreBook;
  readonly ownershipStated: boolean;
}

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
 * a per entry rule rather than a per field one: see
 * `lib/bookRequest.boundIdentifiers`.
 *
 * @param ownershipStated Whether the store established that the member owns
 * what it listed. `false` sends `unknown`, which is what stops a three week
 * Adobe Digital Editions loan being written as a book somebody owns.
 */
export function storeToBookCreate(
  book: StoreBook,
  ownershipStated: boolean,
): BookCreate | null {
  const bound = boundRecord(book);
  if (bound.title === null) return null;

  return {
    ...bound,
    title: bound.title,
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
