/**
 * What an Apple Books library says about the books in it.
 *
 * **Not an integration with a company.** Apple Books keeps its library on the
 * member's own machine as a Core Data SQLite store, so this reads a file they
 * already have on hardware they own. Nothing here talks to Apple, nothing here
 * opens a book, and nothing here touches protection: it reads catalogue
 * metadata about what somebody owns. A protected book is a row like any other
 * and is read as a row.
 *
 * Pure, in `kobo.ts`'s shape: it takes something that answers SQL and returns
 * records. `sqlite.ts` opens the file and says why it could not, and the engine
 * it needs is the one the Calibre import already ships.
 * `docs/device-libraries.md` carries what a second store over that engine costs.
 *
 * ## The plist was measured, and nothing reads one
 *
 * Apple Books is the store that comes as a plist **and** a database, and which
 * of them carries the metadata was the question this reader was blocked on.
 * Measured 2026-09-10, and the answer is that they are not two halves of one
 * library: `Books.plist` is the **iOS** library and this store is the macOS one.
 * Even taken together the plist is a strict subset, carrying four fields a
 * catalogue needs where the table below carries seven. So no plist is parsed
 * here and none has to be.
 *
 * The one plist inside this file is `Z_METADATA.Z_PLIST`, and `schemaVersionOf`
 * says why it is not opened either.
 *
 * ## The schema is not a supported interface, and the reader is built for that
 *
 * Apple publishes nothing about this file and Core Data regenerates it from a
 * model that ships inside the application. So nothing below names a column it
 * has not first found: `WANTED` is this module's own list, the store's
 * `ZBKLIBRARYASSET` table decides which of them are read, and a column that is
 * not there costs its field and is reported in `missing` rather than costing
 * the library. **A store that cannot be read is one skipped source and never a
 * broken import**: every outcome here is a value in a closed union, so a caller
 * importing from several places at once loses this one and keeps the rest.
 *
 * ## Where the schema was read, and what was not done
 *
 * Verified against `github.com/tnahs/readstor` at `main`, read on 2026-09-10:
 * `src/lib/applebooks/macos/mod.rs` is a working implementation of this same
 * read, and `data/databases/books-annotated/BKLibrary/` in that repository is a
 * store it is tested against, whose `CREATE TABLE ZBKLIBRARYASSET` has **86
 * columns and not one named for an ISBN**. `github.com/vgnshiyer/py-apple-books`
 * is the second reading and reaches **7 of the 10 columns `WANTED` names**,
 * measured against its `py_apple_books/models/mappings.ini` on the same day.
 * The three it does not reach are `ZEPUBID`, `ZYEAR` and `ZLANGUAGE`, which are
 * the three whose meaning this module leans on hardest, so those rest on the
 * store's own values and on the column names.
 *
 * **No Mac was read.** The fixtures in `tests/lib/appleBooks.test.ts` are
 * constructed from those sources rather than captured from a machine, and they
 * say so at their own site. What that leaves untested is whether a real library
 * carries a value none of this expects, which is the same thing every paragraph
 * above is about.
 *
 * **A copy taken without its `-wal` sidecar reads as `empty`, and that is
 * correct rather than a bug.** Apple Books keeps the store in write ahead
 * logging mode, so rows written since the last checkpoint live in a second
 * file: all 3 rows of the store above are in the `-wal` and the `.sqlite` on
 * its own answers zero. A member handing over one file gets the sentence
 * `empty` names, which is what their copy says.
 *
 * ## What an Apple Books library cannot supply, stated rather than discovered
 *
 * - **Authors as separate values.** `ZAUTHOR` is one string and there is no
 *   author table, so `authors` has at most one member. Splitting it would need
 *   a separator Apple does not document, and a wrong guess turns one person
 *   into two.
 * - **A publisher.** No column carries one. `ZSTOREID` says the book came from
 *   the store and not who published it.
 * - **A series, on the evidence there is.** Nine column names carry `SERIES` or
 *   `SEQUENCE`, which is the rule rather than the count to trust, and the two
 *   that would answer this are `ZSERIESID`, an identifier rather than a name,
 *   and `ZSEQUENCEDISPLAYNAME`, which reads like the name and is null on every
 *   row of the store measured. So nothing settles what a series is called, and
 *   `calibre.ts`'s rule decides the rest: a position on a book in no series is
 *   not a first volume.
 * - **A description.** `ZBOOKDESCRIPTION` is real and is HTML, and turning HTML
 *   into the text this app stores is `calibre.ts::plainText`. Reading it here
 *   would pull that module's whole chunk into this one, so the field waits on
 *   that helper moving somewhere both readers can reach.
 * - **Telling a series container from a book.** A multi volume series is filed
 *   under a row of its own. `ZCONTENTTYPE` and `ZSERIESCONTAINER` are the two
 *   columns that would distinguish it, and the store measured leaves both at
 *   one constant across every row, so neither is settled by anything read here
 *   and no published source settles either. So a container is read as a book
 *   named for the series, and inventing a value to refuse it would be a guess
 *   that costs real books when it is wrong.
 * - **An audiobook.** `ZKIND` and `ZDURATION` are the columns that might name
 *   one, and both are unsettled the same way: `ZKIND` is null on every row
 *   measured and `ZDURATION` is 0.0 on rows that are EPUBs. `ZISSTOREAUDIOBOOK`
 *   is not the answer either, naming where a file came from rather than what it
 *   is. So the path's extension is the one fact that is checkable, and it names
 *   no audiobook.
 */

import { parseIsbn } from "./isbn";
import type { SqliteDatabase, SqliteRow } from "./sqlite";
import { columnsIn, integer, text } from "./sqliteRow";
import { leadingYear } from "./year";

/** What the path of a book's own file settles. Everything else is left unsaid. */
export type AppleBooksFormat = "EPUB" | "PDF" | "IBOOKS";

/** One book the library says this member has. */
export interface AppleBook {
  /**
   * The library's own reference for this book, and the stable one.
   *
   * A 32 character hexadecimal value on every row of the store measured, and
   * `ZSTOREID` is a separate column, so this is the library's own reference
   * rather than the store's and it survives a title being edited.
   */
  readonly assetId: string;
  readonly title: string | null;
  /** At most one, and the docstring above says why. */
  readonly authors: readonly string[];
  readonly isbn: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly format: AppleBooksFormat | null;
}

/** A field this library's schema could not fill. */
export type AppleBooksField =
  "title" | "authors" | "isbn" | "year" | "language" | "format";

/** Why a database yielded no library. Closed, one sentence each on screen. */
export type AppleBooksFailure =
  /** Opens as SQLite, and is not an Apple Books library. */
  | "not-an-apple-books-library"
  /** An Apple Books library with no rows in it at all. */
  | "empty";

export interface AppleBooksLibrary {
  /**
   * The books, which can be none of them.
   *
   * **A library whose every row was refused is a library with no books in it
   * and not an empty one**, and the two are different sentences: a library of
   * store samples has plenty in it, none of which the member owns. Reporting
   * that as `empty` would throw away `skipped`, which is the count that makes
   * the true sentence sayable.
   */
  readonly books: readonly AppleBook[];
  /**
   * Rows under `ZBKLIBRARYASSET` that were not a book this member has.
   *
   * A store sample, a temporary asset, a book the member hid, and a row with no
   * `ZASSETID`. A number rather than a list: it exists so a member can be told
   * the library held more than this, and which of those a row was is a fact
   * about Apple Books rather than about their library.
   */
  readonly skipped: number;
  /**
   * The store's own model version, where it carries one.
   *
   * **1 on both stores measured, and null where there is none.** That is a fact
   * about Apple's stores rather than about this function, whose range is any
   * whole number a cell can hold: `schemaVersionOf` says why the number is
   * weak. Where a Kobo's version tells one device from another, this tells
   * nothing apart, and it is here because the shape is the family's.
   */
  readonly schemaVersion: number | null;
  /** Fields no column in this store could fill. Sorted, so it compares. */
  readonly missing: readonly AppleBooksField[];
}

export type AppleBooksReading =
  | { readonly ok: true; readonly library: AppleBooksLibrary }
  | { readonly ok: false; readonly failure: AppleBooksFailure };

/**
 * Whether a file name is one of these stores.
 *
 * **A predicate rather than a name, because the name is not one.** The suffix
 * is a timestamp from when the store was created, so
 * `BKLibrary-1-091020131601.sqlite` is one library's file and no other's.
 *
 * `endsWith(".sqlite")` also declines the `-wal` and `-shm` sidecars beside it,
 * which are not databases and which `sqlite.ts` would refuse anyway. The
 * docstring above says what a member handing over the store without them gets.
 */
export function isAppleBooksDatabaseName(name: string): boolean {
  const lowered = name.toLowerCase();
  return lowered.startsWith("bklibrary-") && lowered.endsWith(".sqlite");
}

/**
 * The columns this reader will use, and this module is the only place they are
 * spelled.
 *
 * **Every identifier in every statement below is a literal in this module**,
 * and this list is the only one a file has any say over. The names that reach
 * the `SELECT` are the members of this array that the store also has, so a
 * member supplied file decides which of these literals are used and never what
 * they are. That is the whole of the injection argument: a column called
 * `x FROM sqlite_master; DROP` on a hostile file matches no member here and is
 * not read.
 *
 * **The table is spelled out at each of its sites rather than held in a
 * constant**, which is `kobo.ts`'s arrangement: it writes `"content"` at its
 * `columnsIn` call and again in its own statement. There are three sites here,
 * the third being the equality in `tests/lib/appleBooks.test.ts`, and a
 * divergence between any two is loud rather than silent. Structurally, because
 * `present` comes from one literal and the statement from another: a statement
 * naming a different table reads rows at all only if that table carries every
 * member of `WANTED` the first one had. Measured, a one character divergence
 * at either site fails more than 40 of this module's 57 tests.
 */
const WANTED = [
  "ZASSETID",
  "ZTITLE",
  "ZAUTHOR",
  "ZEPUBID",
  "ZYEAR",
  "ZLANGUAGE",
  "ZPATH",
  "ZISSAMPLE",
  "ZISEPHEMERAL",
  "ZISHIDDEN",
] as const;

/**
 * The two columns without which this is not an Apple Books library.
 *
 * `Z_PK` is Core Data's primary key and is on every table it generates, so it
 * says the file was written by Core Data and nothing more. `ZASSETID` is Books'
 * own. The pair under a table named `ZBKLIBRARYASSET` is what no other
 * application's store carries.
 */
const SIGNATURE = ["Z_PK", "ZASSETID"] as const;

/**
 * Flags that mean the row is not a book this member has.
 *
 * **An exclusion where `kobo.ts` reached for an inclusion, and the direction is
 * forced rather than chosen.** A Kobo says what kind of row it is in one column
 * with an enumerated value, so a list of the values that mean a purchase can be
 * written. Apple Books has no such column: `ZCONTENTTYPE` is an integer no
 * published source settles, and what is left is booleans. There is nothing to
 * include over.
 *
 * What the direction costs, and it is a present cost rather than a future one:
 * a row filed under a boolean this list does not name reads as a book, and
 * `skipped` cannot show it, because the row was not skipped. **The store
 * measured carries 11 `ZIS*` booleans**; three are named here, two more are
 * named and declined below, and six are left: `ZISDEVELOPMENT`, `ZISEXPLICIT`,
 * `ZISFINISHED`, `ZISLOCKED`, `ZISNEW` and `ZISTRACKEDASRECENT`. **No published
 * source settles one of them**, which is the same reason `ZCONTENTTYPE` is not
 * read. Reading a name is not settling it, and a guess here runs one way:
 * `ZISDEVELOPMENT` is as plausibly a row nobody owns as it is anything else.
 *
 * `ZISPROOF` and `ZISSTOREAUDIOBOOK` are deliberately absent: a proof copy is a
 * book somebody was given rather than an advertisement for one, and where a
 * book was bought is not whether it is one.
 */
const REFUSING_FLAGS = ["ZISSAMPLE", "ZISEPHEMERAL", "ZISHIDDEN"] as const;

/**
 * What the extension of a book's own file settles.
 *
 * The path rather than a code, because the extension is checkable and
 * `ZCONTENTTYPE` is not. `.ibooks` is Apple's own Multi-Touch format, which
 * Books opens and no other reader here does.
 *
 * **No entry for an audiobook, and Apple's own page is the source.** "Import
 * books, audiobooks, or PDFs", read 2026-09-10, names what a member may add to
 * a library: PDFs, EPUB books, mp3 audiobooks and Audible audiobooks. So an
 * audiobook a member **imports** is one of the last two, neither of which this
 * list names. What that page does not settle is a store audiobook, which is
 * nothing a member added and is what `ZISSTOREAUDIOBOOK` above exists for, and
 * this list does not name one of those either.
 *
 * **Two ways a fourth entry could be wrong silently, and both are made
 * unrepresentable rather than tested**, because a test over this list would
 * assert nothing about the three entries in it today:
 *
 * - **Shadowed by an earlier entry.** `readFormat` takes the longest match
 *   rather than the first, so order decides nothing. Not academic: an entry
 *   written `"books"`, a dropped leading dot rather than an exotic input, is a
 *   suffix of `".ibooks"`, and first match answers `EPUB` for a Multi-Touch
 *   book where longest match answers `IBOOKS`.
 * - **An entry carrying a capital.** The comparison lowercases the entry as
 *   well as the path, so `".EPUB"` matches rather than silently never matching
 *   anything at all.
 *
 * **A third is left, and what it is was measured rather than reasoned about**,
 * because two entries naming one extension go wrong in two different ways and
 * neither is the obvious one. An **exact** duplicate is not a tie: the `Map`
 * keeps the last of the two and drops the other, silently, where the array this
 * replaced kept the first. Two entries differing only in **case** are two keys
 * the `Map` keeps both of, which lower to one suffix, tie on length, and let
 * order decide. **That second route is one the capital fix above opened**, and
 * it is here because the fix was checked in the dimension it was designed for
 * and not in this one.
 *
 * Both are visible on the page, two lines apart, rather than at runtime. That
 * is why there is no guard, and it is the whole of what is left for one.
 */
const FORMATS = new Map<string, AppleBooksFormat>([
  [".epub", "EPUB"],
  [".pdf", "PDF"],
  [".ibooks", "IBOOKS"],
]);

/**
 * How the EPUB identifier a store copies verbatim spells that it is an ISBN.
 *
 * `ZEPUBID` is the book's `dc:identifier` as the file wrote it, so the same
 * ISBN arrives under whichever spelling the file used. **Three are in the store
 * measured**, bare, hyphenated and `isbn_` prefixed; `urn:isbn:` is the EPUB 3
 * spelling, taken from `opf.ts::readIsbn` rather than from the store, and it is
 * here because `ZEPUBID` is that same identifier copied across.
 *
 * **Only the letters come off, and that is the whole of it.** `parseIsbn`
 * normalises away everything that is not alphanumeric, so a separator after the
 * word needs no arm here; a class matching one would be dead code that the next
 * reader takes for the thing that makes `isbn_` work.
 */
const ISBN_PREFIX = /^(?:urn:)?isbn/i;

/** A Core Data boolean, which is an integer column and not always a 0 or a 1. */
function isSet(value: unknown): boolean {
  const flag = integer(value);
  return flag !== null && flag !== 0;
}

/**
 * The store's model version, where it has one.
 *
 * Informational, and read rather than acted on: every decision below is taken
 * from the columns that are actually there, which is the same question asked of
 * the file rather than of a number the file states about itself.
 *
 * **And it is a weak number, measured rather than assumed.** Core Data writes 1
 * into `Z_VERSION` and keeps the model's real identity in `Z_PLIST` beside it:
 * **828 bytes** opening `bplist00` on the store measured, holding
 * `NSStoreModelVersionHashes`, a digest of them, and a `BKLibraryVersion_Key`.
 * Both Core Data stores Books keeps read `Z_VERSION = 1`.
 *
 * **828 is that store with its `-wal` beside it**, and the checkpointed file
 * alone answers 685: two readings of one store, and the paragraph above about
 * the sidecar is why they differ. **Which figures move is the thing to know**,
 * and it is not which file they came from. Every figure here taken from a row
 * needs the sidecar, because without it there are no rows to say anything
 * about; the counts of columns read the same either way.
 *
 * **That is the one plist inside this store and it is not opened.** It would
 * take a binary plist parser to report a number nothing acts on, which is the
 * trade this module's own measurement refused everywhere else.
 */
function schemaVersionOf(db: SqliteDatabase): number | null {
  return integer(
    db.query("SELECT Z_VERSION FROM Z_METADATA")[0]?.["Z_VERSION"],
  );
}

/** Which of `WANTED` this store does not have, as the fields they fill. */
function missingFields(present: Set<string>): AppleBooksField[] {
  const fields = new Map<AppleBooksField, readonly string[]>([
    ["title", ["ZTITLE"]],
    ["authors", ["ZAUTHOR"]],
    ["isbn", ["ZEPUBID"]],
    ["year", ["ZYEAR"]],
    ["language", ["ZLANGUAGE"]],
    ["format", ["ZPATH"]],
  ]);
  return [...fields]
    .filter(([, columns]) => !columns.some((column) => present.has(column)))
    .map(([field]) => field)
    .sort();
}

/**
 * Whether a row is a book this member has, or one of the things a library keeps
 * beside one.
 *
 * **A column this store does not have costs a distinction, never the book**,
 * which is the same reading `kobo.ts::isOwned` gives an old device: a flag that
 * is not there is not a flag that is set. **`isSet` is the whole of that**, and
 * there is deliberately no second test against the columns the store has: a
 * name outside the statement is `undefined` in the row, which `isSet` already
 * answers false for. A `present.has` term beside it reads like the guard and is
 * unobservable, since no file can make the two disagree.
 */
function isTheirs(row: SqliteRow): boolean {
  return !REFUSING_FLAGS.some((flag) => isSet(row[flag]));
}

/** The format of the file this row points at, where the path names one. */
function readFormat(value: unknown): AppleBooksFormat | null {
  const path = text(value);
  if (path === null) return null;
  const lowered = path.toLowerCase();
  // The longest match, not the first, and the entry lowered as well as the
  // path. `FORMATS` says what each of those refuses.
  let found: AppleBooksFormat | null = null;
  let matched = 0;
  for (const [extension, format] of FORMATS) {
    const suffix = extension.toLowerCase();
    if (lowered.endsWith(suffix) && suffix.length > matched) {
      matched = suffix.length;
      found = format;
    }
  }
  return found;
}

/** The ISBN, where the identifier the file carried was one. */
function readIsbn(value: unknown): string | null {
  const written = text(value);
  return written === null ? null : parseIsbn(written.replace(ISBN_PREFIX, ""));
}

/**
 * Read an Apple Books library, or say why there is not one.
 *
 * Never throws for anything a file can contain. Every way this can fail is a
 * value in `AppleBooksReading`, because the caller's job is the same for all of
 * them: report one source it could not read and carry on with the others.
 * `tests/lib/appleBooks.test.ts` asserts that against databases built to break
 * it.
 */
export function readAppleBooksLibrary(db: SqliteDatabase): AppleBooksReading {
  const present = columnsIn(db, "ZBKLIBRARYASSET");
  if (!SIGNATURE.every((column) => present.has(column))) {
    return { ok: false, failure: "not-an-apple-books-library" };
  }

  // Only the members of `WANTED` this store has, which is what makes the
  // interpolation below an interpolation of this module's own literals.
  const columns = WANTED.filter((column) => present.has(column));
  const rows = db.query(`SELECT ${columns.join(", ")} FROM ZBKLIBRARYASSET`);
  if (rows.length === 0) return { ok: false, failure: "empty" };

  let skipped = 0;
  const books: AppleBook[] = [];
  for (const row of rows) {
    const assetId = text(row["ZASSETID"]);
    if (assetId === null || !isTheirs(row)) {
      skipped += 1;
      continue;
    }
    const author = text(row["ZAUTHOR"]);
    books.push({
      assetId,
      title: text(row["ZTITLE"]),
      authors: author === null ? [] : [author],
      isbn: readIsbn(row["ZEPUBID"]),
      year: leadingYear(text(row["ZYEAR"])),
      language: text(row["ZLANGUAGE"]),
      format: readFormat(row["ZPATH"]),
    });
  }

  return {
    ok: true,
    library: {
      books,
      skipped,
      schemaVersion: schemaVersionOf(db),
      missing: missingFields(present),
    },
  };
}
