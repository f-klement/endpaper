/**
 * What a Kobo device says about the books on it.
 *
 * **Not an integration with a company.** A Kobo mounts as mass storage and
 * keeps its library in `.kobo/KoboReader.sqlite`, so this reads a file the
 * member already has on hardware they own. Nothing here talks to Kobo, nothing
 * here opens a book, and nothing here touches DRM: it reads catalogue metadata
 * about what somebody owns.
 *
 * Pure, in `calibre.ts`'s shape: it takes something that answers SQL and
 * returns records. `sqlite.ts` opens the file and says why it could not,
 * `bookBounds.ts` decides what the API will hold, and the engine those two need
 * is the one the Calibre import already ships. `docs/device-libraries.md`
 * carries what a second store over that engine costs.
 *
 * ## The schema is not a supported interface, and the reader is built for that
 *
 * Kobo publishes nothing about this file and changes it in firmware updates.
 * calibre's own driver, which is the closest thing to documentation that
 * exists, substitutes a default for sixteen columns that arrived at one schema
 * version or another. The five gates this reader stands on: `Accessibility`
 * from 16, `Language` and `IsDownloaded` from 33, `ISBN` from 46, `Series` and
 * `SeriesNumber` from 65, `SeriesNumberFloat` from 136. **Recount from the
 * driver rather than from this paragraph**, which named ten and then listed
 * seven on its first draft.
 *
 * So nothing below names a column it has not first found. `WANTED` is this
 * module's own list, the device's `content` table decides which of them are
 * read, and a column that is not there costs its field and is reported in
 * `missing` rather than costing the library. **A store that cannot be read is
 * one skipped source and never a broken import**: every outcome here is a value
 * in a closed union, so a caller importing from several places at once loses
 * this one and keeps the rest.
 *
 * ## Where the schema was read, and what was not done
 *
 * Verified against calibre's KoboTouch driver,
 * `src/calibre/devices/kobo/driver.py` and `db.py`, at commit `71a1997` of
 * 2026-09-08, read on 2026-09-10. That is a working implementation of this
 * exact read against real devices, which is why it is the source.
 *
 * **No Kobo device was read.** The fixtures in `tests/lib/kobo.test.ts` are
 * constructed from that driver rather than captured from hardware, and they say
 * so at their own site. What that leaves untested is whether a real device
 * carries a value none of this expects, which is the same thing every paragraph
 * above is about.
 *
 * ## What a Kobo cannot supply, stated rather than discovered
 *
 * - **Authors as separate values.** `Attribution` is one string and Kobo keeps
 *   no author list, so `authors` has at most one member. Splitting it would
 *   need a separator Kobo does not document, and a wrong guess turns one person
 *   into two.
 * - **A format for everything.** `MimeType` settles EPUB, kepub and PDF. It
 *   does not settle an audiobook: calibre reads `application/octet-stream` as
 *   one only in combination with a zero file size, which is a fact about the
 *   file rather than about the row, so that mime type is left unmapped here.
 * - **Reading progress, shelves, covers and the description.** `ReadStatus`,
 *   `___PercentRead`, `DateLastRead` and the bookshelf tables are real and are
 *   not read: a read status in this app belongs to a member rather than to a
 *   book, and whether an import writes one is a decision about the import flow.
 */

import { leadingYear } from "./year";
import { parseIsbn } from "./isbn";
import type { SqliteDatabase, SqliteRow } from "./sqlite";
import { columnsIn, decimal, integer, text } from "./sqliteRow";

/** What `MimeType` settles. Everything else is left unsaid. */
export type KoboFormat = "EPUB" | "KEPUB" | "PDF";

/** One book the device says this member owns. */
export interface KoboBook {
  /**
   * The device's own reference for this book, and the stable one.
   *
   * A purchased book carries a store UUID and a sideloaded book carries a
   * `file:///mnt/onboard/...` URL, so this is unique on the device either way
   * and survives a title being edited.
   */
  readonly contentId: string;
  readonly title: string | null;
  /** At most one, and the docstring above says why. */
  readonly authors: readonly string[];
  readonly isbn: string | null;
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
  readonly format: KoboFormat | null;
  /**
   * A book the member put on the device themselves rather than bought, or
   * `null` on a device too old to have recorded which it was.
   */
  readonly sideloaded: boolean | null;
}

/** A field this device's schema could not fill. */
export type KoboField =
  | "title"
  | "authors"
  | "isbn"
  | "publisher"
  | "year"
  | "language"
  | "series"
  | "format";

/** Why a database yielded no library. Closed, one sentence each on screen. */
export type KoboFailure =
  /** Opens as SQLite, and is not a Kobo device database. */
  | "not-a-kobo-device"
  /** A Kobo device with no book rows on it at all. */
  | "empty";

export interface KoboLibrary {
  /**
   * The books, which can be none of them.
   *
   * **A device whose every row was refused is a library with no books in it and
   * not an empty device**, and the two are different sentences: a Kobo carrying
   * two hundred store recommendations and nothing else has plenty on it, none
   * of which the member owns. Reporting that as `empty` would throw away
   * `skipped`, which is the count that makes the true sentence sayable.
   */
  readonly books: readonly KoboBook[];
  /**
   * Rows under `content` that were not a book this member owns.
   *
   * Store recommendations, previews, the expired row a firmware bug leaves
   * behind for a deleted book, a sideloaded book that has been removed, a row
   * carrying an `Accessibility` this reader does not know, and a row with no
   * `ContentID`. A number rather than a list: it exists so a member can be told
   * the device held more than this, and which of those a row was is a fact
   * about Kobo rather than about their library.
   */
  readonly skipped: number;
  /** The device's schema version, where the device carries one. */
  readonly schemaVersion: number | null;
  /** Fields no column on this device could fill. Sorted, so it compares. */
  readonly missing: readonly KoboField[];
}

export type KoboReading =
  | { readonly ok: true; readonly library: KoboLibrary }
  | { readonly ok: false; readonly failure: KoboFailure };

/** The file a Kobo keeps its library in, below `.kobo/` on the device. */
export const DATABASE_FILENAME = "KoboReader.sqlite";

/**
 * The columns this reader will use, and this module is the only place they are
 * spelled.
 *
 * **Nothing outside this list is ever put into a statement.** The names that
 * reach the `SELECT` below are the members of this array that the device also
 * has, so a member supplied file decides which of these literals are used and
 * never what they are. That is the whole of the injection argument: a column
 * called `x FROM sqlite_master; DROP` on a hostile file matches no member here
 * and is not read.
 */
const WANTED = [
  "ContentID",
  "BookID",
  "MimeType",
  "Title",
  "Attribution",
  "Publisher",
  "Language",
  "ISBN",
  "Series",
  "SeriesNumber",
  "SeriesNumberFloat",
  "DateCreated",
  "Accessibility",
  "IsDownloaded",
  "___ExpirationStatus",
] as const;

/**
 * The two columns without which this is not a Kobo device.
 *
 * **A `content` table is not a signature.** Plenty of things keep one; what is
 * Kobo's own is a `content` table whose rows carry a `ContentID` and a
 * `BookID`, which is the pair the layout is built on: a book is a row with no
 * `BookID`, and its chapters are rows pointing back at it.
 */
const SIGNATURE = ["ContentID", "BookID"] as const;

/**
 * `Accessibility` values that mean the member has the book.
 *
 * From calibre's own query: `1` and `2` are a Kobo store purchase, `8` is Kobo
 * Plus and `9` is OverDrive. `4` and `6` are a recommendation and a
 * preview, which are books the store is advertising rather than books anybody
 * owns, and importing one would tell a member they own something they do not.
 *
 * **An unrecognised value is skipped rather than kept**, and that direction is
 * the decision. This is an inclusion list, which is the shape that goes stale,
 * and the alternative goes stale in the direction where a future firmware's new
 * advert becomes a book on somebody's shelf. Losing a real book is visible in
 * `skipped`; gaining a book nobody bought is not visible at all.
 */
const OWNED_ACCESSIBILITY = new Set([1, 2, 8, 9]);

/** A book the member loaded themselves, which is owned when it is still there. */
const SIDELOADED_ACCESSIBILITY = -1;

/** The expired row a firmware bug leaves behind for a book that was deleted. */
const EXPIRED = 3;

/**
 * What `MimeType` settles.
 *
 * `application/x-kobo-epub+zip` is Kobo's own kepub, which is an EPUB with
 * Kobo's markup in it and is worth telling apart from one: a member importing
 * both would otherwise see the same format twice for two different files.
 */
const FORMATS = new Map<string, KoboFormat>([
  ["application/epub+zip", "EPUB"],
  ["application/x-kobo-epub+zip", "KEPUB"],
  ["application/pdf", "PDF"],
]);

/**
 * A Kobo boolean, which is two different things.
 *
 * `IsDownloaded` is the string `'true'` on the firmware calibre supports and a
 * real `1` on a Tolino at schema version 188 or later, which is the one
 * combination calibre gates its own boolean on. A reader that tests one of them
 * calls every book on the other kind of device deleted and imports nothing, so
 * calibre's own statement asks for `in ('true', 1)`.
 *
 * **`'1'` is read as well, and it is not a fourth spelling.** SQLite gives a
 * column with text affinity to a value written as `1`, so the same firmware
 * that writes an integer stores a string wherever the column was declared as
 * text. Testing the value rather than the storage class is what makes this
 * independent of a declaration no vendor documents.
 */
function isTrue(value: unknown): boolean {
  if (typeof value === "number") return value === 1;
  const written = text(value)?.toLowerCase();
  return written === "true" || written === "1";
}

/**
 * The device's schema version, where it has one.
 *
 * Informational, and read rather than acted on: every decision below is taken
 * from the columns that are actually there, which is the same question asked of
 * the file rather than of a number the file states about itself. calibre reads
 * this table too and falls back to 0 when it is absent, so an absent one is an
 * old device rather than a broken file.
 */
function schemaVersionOf(db: SqliteDatabase): number | null {
  return integer(db.query("SELECT version FROM dbversion")[0]?.["version"]);
}

/** Which of `WANTED` this device does not have, as the fields they fill. */
function missingFields(present: Set<string>): KoboField[] {
  const fields = new Map<KoboField, readonly string[]>([
    ["title", ["Title"]],
    ["authors", ["Attribution"]],
    ["isbn", ["ISBN"]],
    ["publisher", ["Publisher"]],
    ["year", ["DateCreated"]],
    ["language", ["Language"]],
    ["series", ["Series"]],
    ["format", ["MimeType"]],
  ]);
  return [...fields]
    .filter(([, columns]) => !columns.some((column) => present.has(column)))
    .map(([field]) => field)
    .sort();
}

/**
 * Whether a row is a book this member owns, or one of the things a Kobo keeps
 * beside one.
 *
 * **A column this device does not have costs a distinction, never the book.**
 * `Accessibility` arrived at schema version 16 and `IsDownloaded` at 33, so on
 * a device older than either the row cannot be an advert: there was nowhere to
 * record that it was one. calibre substitutes exactly these defaults for the
 * same reason.
 */
function isOwned(row: SqliteRow, present: Set<string>): boolean {
  if (present.has("___ExpirationStatus")) {
    if (integer(row["___ExpirationStatus"]) === EXPIRED) return false;
  }
  if (!present.has("Accessibility")) return true;
  const accessibility = integer(row["Accessibility"]);
  if (accessibility === SIDELOADED_ACCESSIBILITY) {
    // A sideloaded book that is no longer downloaded is one the member deleted:
    // Kobo keeps the row and clears the flag rather than removing it.
    return !present.has("IsDownloaded") || isTrue(row["IsDownloaded"]);
  }
  return accessibility !== null && OWNED_ACCESSIBILITY.has(accessibility);
}

/**
 * The publication year, or `null` where a book could not have one.
 *
 * `DateCreated` is an ISO timestamp as text, and `year.leadingYear` is
 * the one home of what a leading four digit run means and which of them is a
 * year. **What is left here is the half that knows it is reading a SQLite
 * cell**, which is the same shape `calibre.readYear` keeps for the same
 * reason.
 */
function readYear(value: unknown): number | null {
  return leadingYear(text(value));
}

/**
 * Where in a series, read only where a series is named.
 *
 * `SeriesNumberFloat` arrived at schema version 136 and `SeriesNumber` is text
 * on every version, so the number is taken from whichever is there. Structural
 * rather than by value, `calibre.ts`'s rule: a position on a book in no series
 * is not a first volume.
 */
function readSeriesIndex(row: SqliteRow, present: Set<string>): number | null {
  if (present.has("SeriesNumberFloat")) {
    const float = decimal(row["SeriesNumberFloat"]);
    if (float !== null) return float;
  }
  const written = text(row["SeriesNumber"]);
  if (written === null) return null;
  const parsed = Number(written);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Read a Kobo device's library, or say why there is not one.
 *
 * Never throws for anything a file can contain. Every way this can fail is a
 * value in `KoboReading`, because the caller's job is the same for all of them:
 * report one source it could not read and carry on with the others.
 * `tests/lib/kobo.test.ts` asserts that against databases built to break it.
 */
export function readKoboLibrary(db: SqliteDatabase): KoboReading {
  const present = columnsIn(db, "content");
  if (!SIGNATURE.every((column) => present.has(column))) {
    return { ok: false, failure: "not-a-kobo-device" };
  }

  // Only the members of `WANTED` this device has, which is what makes the
  // interpolation below an interpolation of this module's own literals.
  const columns = WANTED.filter((column) => present.has(column));
  const rows = db.query(
    `SELECT ${columns.join(", ")} FROM content WHERE BookID IS NULL`,
  );
  if (rows.length === 0) return { ok: false, failure: "empty" };

  let skipped = 0;
  const books: KoboBook[] = [];
  for (const row of rows) {
    const contentId = text(row["ContentID"]);
    if (contentId === null || !isOwned(row, present)) {
      skipped += 1;
      continue;
    }
    const attribution = text(row["Attribution"]);
    const seriesName = text(row["Series"]);
    books.push({
      contentId,
      title: text(row["Title"]),
      authors: attribution === null ? [] : [attribution],
      isbn: parseIsbn(text(row["ISBN"])),
      publisher: text(row["Publisher"]),
      year: readYear(row["DateCreated"]),
      language: text(row["Language"]),
      seriesName,
      seriesIndex: seriesName === null ? null : readSeriesIndex(row, present),
      format: FORMATS.get(text(row["MimeType"]) ?? "") ?? null,
      sideloaded: present.has("Accessibility")
        ? integer(row["Accessibility"]) === SIDELOADED_ACCESSIBILITY
        : null,
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
