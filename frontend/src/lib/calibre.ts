/**
 * What a Calibre library says about its books.
 *
 * **The route that carries identifiers.** Measured over the household's own
 * reference library of 897 books: 568 carry an ISBN typed identifier and 812
 * carry an identifier of some type, where the same library's OPDS feed carries
 * none at all. That measurement is the owner's reason for building this beside
 * the network route rather than instead of it, and it is recorded in
 * `docs/decisions.md`.
 *
 * Pure: it takes something that answers SQL and returns records. It knows
 * nothing about files, WebAssembly or the API. `sqlite.ts` opens the database
 * and says why it could not; `bookBounds.ts` decides what the API will hold.
 *
 * **A member supplied `metadata.db` is untrusted input.** Nothing here believes
 * the file about its own shape: every table and column is checked against
 * `sqlite_master` before it is read, every relation is optional, and a book
 * whose row is nonsense loses fields rather than losing the library. Calibre's
 * layout is stable enough to rely on and **its schema is explicitly not
 * guaranteed**, which is the same requirement arriving from the other side.
 *
 * ## What Calibre stores that this app has nowhere to put
 *
 * Stated as an exclusion rather than left to be discovered:
 *
 * - **Identifiers other than the ISBN.** `identifiers` holds `amazon`,
 *   `google`, `goodreads`, `doi` and whatever a plugin invented. Of the 897
 *   book reference library that is 568 books served and 244 more carrying only
 *   an identifier this reader passes over. **`BookCreate` now has somewhere to
 *   put two of those types**, `amazon` and `google`, and this import still
 *   sends none: which of a plugin's type strings is which scheme is a decision
 *   about this reader rather than a line in a request builder, and it is a
 *   ticket. `LibrarySettingsPage/types.toBookCreate` says the same at the site
 *   that would carry them.
 * - **Tags, ratings and the book files themselves.** Each is a second request a
 *   book, and whether an import should make one is a decision about the import
 *   flow rather than about this reader. The `data` table is still read, for the
 *   one fact it settles that the OPF cannot: whether a book has a file at all.
 * - **Custom columns.** They live in tables named per library
 *   (`custom_column_3`), so reading them means reading `custom_columns` first
 *   and mapping names a household invented onto fields this one defines.
 *
 * ## The three Calibre placeholders, and why each is damage
 *
 * Calibre fills a blank rather than leaving one, so a naive read imports the
 * placeholder as though it were a fact. Each of these is a documented Calibre
 * constant rather than a guess about this library:
 *
 * - `pubdate` is `0101-01-01` when the date is unknown, so the year reads 101.
 * - `title` and an author's `name` are both the literal `Unknown`.
 * - `series_index` defaults to `1.0` on every book, including every book in no
 *   series at all, so it is read only where a series link exists.
 *
 * **The exclusion, because a list of three is a list somebody will extend.**
 * `CALIBRE_PLACEHOLDER` is the set and both doors are driven from it, so
 * extending it is one edit and a test that goes red until both doors apply the
 * new member. The year member is the exception and that paragraph says why.
 * What is **not** refused: every other value a
 * library carries, however empty it looks. Swept 2026-09-08 over the 897 rows
 * and 244 `metadata.opf` files of the reference library, no fourth value
 * repeats where a blank would be: 0 files carry `dc:language` of `und`,
 * Calibre's undefined language, and 0 carry a `dc:title` of exactly `Unknown`.
 * That is one library and one Calibre version, so it bounds nothing; it is why
 * the set has three members today rather than why it may only ever have three.
 */

import { leadingYear } from "./year";
import { parseIsbn } from "./isbn";
import type { FileMetadata } from "./fileReaders";
import type { SqliteDatabase, SqliteRow } from "./sqlite";
import { columnsIn, decimal, integer, text } from "./sqliteRow";

/**
 * How much of one `metadata.opf` will be read.
 *
 * The same bound `epub.ts` puts on a package document and from the same
 * measurement: 253,032 bytes was the largest of the 79 file corpus that module
 * describes, median 4,943. 4 MiB is sixteen times the largest seen. Stated here
 * rather than imported, because that one is a bound on what an entry **inflates
 * to** inside a zip and this is a bound on a file's size on disk: the same
 * number for two different quantities, and folding them into one constant would
 * make a change to either look safe.
 */
export const MAX_OPF_BYTES = 4 * 1024 * 1024;

/** The library index, at the root of a Calibre library directory. */
export const DATABASE_FILENAME = "metadata.db";

/** The file Calibre writes beside each book, when it writes one. */
export const OPF_FILENAME = "metadata.opf";

/**
 * Where in the library a picked file sits, or `null` for one that is not in a
 * library at all.
 *
 * A directory picker reports `webkitRelativePath` as
 * `<the folder that was picked>/<the path inside it>`, so the first segment is
 * the name of whatever the member pointed at and never part of the library's
 * own layout. Dropping it is what makes the answer comparable with `books.path`,
 * which Calibre writes relative to the library root.
 *
 * **Normalised to NFC**, because the database and the filesystem can spell one
 * accented directory name two ways: a name composed in the database and
 * decomposed on disk compares unequal while naming one directory, which on a
 * library of nine hundred books is a silent loss of the cross check for every
 * author with a diacritic in their name.
 */
export function libraryPathOf(file: File): string | null {
  const full = file.webkitRelativePath;
  if (!full) return null;
  const segments = full.split("/").slice(1);
  if (segments.length === 0) return null;
  return segments.join("/").normalize("NFC");
}

/**
 * The `metadata.opf` beside each book, keyed by the book's own directory.
 *
 * Keyed by directory rather than matched by title, because the directory is
 * what `books.path` names: a title match would pair the wrong copy of a book
 * a library holds twice, and would pair nothing at all for a title Calibre
 * shortened to fit a filesystem.
 */
export function indexOpfFiles(files: readonly File[]): Map<string, File> {
  const index = new Map<string, File>();
  for (const file of files) {
    if (file.name !== OPF_FILENAME) continue;
    const path = libraryPathOf(file);
    if (path === null) continue;
    const directory = path.slice(0, -(OPF_FILENAME.length + 1));
    if (directory !== "") index.set(directory, file);
  }
  return index;
}

/** One row of Calibre's `identifiers` table, as the file spelled it. */
export interface CalibreIdentifier {
  readonly type: string;
  readonly value: string;
}

/** What one row of `books` and everything linked to it asserts. */
export interface CalibreBook {
  readonly id: number;
  /**
   * The book's directory, relative to the library root: `Author/Title (id)`.
   *
   * Carried because it is how the file beside the book is found, and it is the
   * one thing the OPF cannot supply about itself.
   */
  readonly path: string;
  readonly title: string | null;
  /** Separate values, in link order. Joining them is the request's business. */
  readonly authors: readonly string[];
  readonly identifiers: readonly CalibreIdentifier[];
  /** Canonical ISBN-13, from whichever identifier carried a real one. */
  readonly isbn: string | null;
  readonly publisher: string | null;
  readonly year: number | null;
  readonly language: string | null;
  readonly description: string | null;
  readonly seriesName: string | null;
  readonly seriesIndex: number | null;
  /**
   * The formats `data` names for this book, upper case as Calibre writes them.
   *
   * The one fact the database settles that the file beside the book cannot: a
   * `metadata.opf` names no book file, so an OPF only library cannot say
   * whether a record is a book on a shelf or a book somebody wrote down.
   */
  readonly formats: readonly string[];
}

/** Why a database yielded no library. Closed, one sentence each on screen. */
export type CalibreFailure =
  /** Opens as SQLite, but is not a Calibre library. */
  | "not-a-calibre-library"
  /** A Calibre library with no books in it. */
  | "empty";

export type CalibreReading =
  | { readonly ok: true; readonly books: readonly CalibreBook[] }
  | { readonly ok: false; readonly failure: CalibreFailure };

/**
 * Calibre's `UNDEFINED_DATE`, as the year it reads back as.
 *
 * Calibre writes `0101-01-01T00:00:00+00:00` where a date is unknown rather
 * than writing NULL, so a reader that trusts `pubdate` files a library under
 * the second century. `boundNumber` would not catch it: 101 is inside the
 * `year` column's range, which is what makes this a value to refuse rather than
 * a value to bound.
 *
 * **One of this module's two doors refuses it by this name, and that door is
 * the file's.** `readYear` refuses it inside `plausibleYear`'s window instead,
 * so the member below is this constant's only remaining use.
 * `CALIBRE_PLACEHOLDER` says what that costs.
 */
const CALIBRE_UNDEFINED_YEAR = 101;

/** What Calibre writes where a person did not say. Not a title and not a name. */
const CALIBRE_UNKNOWN = "Unknown";

/**
 * What a Calibre placeholder is, decided once for both doors that meet one.
 *
 * **A library is read through two doors and they must refuse the same set.**
 * `readCalibreLibrary` meets a placeholder in a row of `metadata.db`;
 * `crossCheck` meets it again in the `metadata.opf` beside the book, which
 * Calibre wrote from those same rows. Before this the two were separate
 * literals that happened to agree, so a fourth placeholder was two edits with
 * nothing red after the first, and the pair had already drifted: the file
 * door's author refusal depended on a name's position in the list and the
 * index door's did not.
 *
 * The constants were already single homed and that was not enough, because
 * what goes wrong is the **application**, one field at a time, and a shared
 * constant says nothing about who applied it.
 *
 * **What holds the set and its test together, on which rung.** The test's case
 * list types each of its keys as one of this object's, so removing a member
 * from here fails the typecheck there, and it asserts its keys against
 * `Object.keys` of this object, so adding one with no case goes red. Each case
 * then drives both doors. Exporting this was the whole of that mechanism and
 * it is why the export exists: a first draft listed the three values in the
 * test beside this object rather than from it, which moved "two edits with
 * nothing red after the first" out of this file and into that one. Measured on
 * that draft: a fourth member added here and wired at neither door passed 52
 * of 52.
 *
 * **`series_index` is the third placeholder and is not here**, because it is
 * refused structurally rather than by value: both doors read a position only
 * where a series is named, so `1.0` on a standalone book is never reached. A
 * predicate on the number would have to refuse a real first volume.
 *
 * **The year member is applied at the file door only, and the coupling above
 * does not hold for it. This is the one home of that exception.** `readYear`
 * refuses 101 inside `plausibleYear`'s window, a wider rule that already
 * refuses everything this member does, so the index door needs no predicate for
 * it and no test at that door can see one removed: the window answers first
 * however the member is applied. What the mechanism still binds is `title` and
 * `author`, which are strings no window reaches. Written here rather than left
 * to be rediscovered by somebody adding a fourth member and trusting the
 * paragraph above.
 */
export const CALIBRE_PLACEHOLDER = {
  /** `title` is the literal `Unknown` where nobody typed one. */
  title: (value: string): boolean => value === CALIBRE_UNKNOWN,
  /** An author's `name` is the same literal, at any position in the list. */
  author: (value: string): boolean => value === CALIBRE_UNKNOWN,
  /** `pubdate` is `0101-01-01`, the year 101. The file door applies this one. */
  year: (value: number): boolean => value === CALIBRE_UNDEFINED_YEAR,
} as const;

/**
 * The tables this reader will use, and whether it can proceed without one.
 *
 * **`books` alone is not a Calibre signature.** This app's own database has a
 * `books` table, and so does most of what anybody would call a library file, so
 * recognising on that one name means answering "that is a Calibre library" for
 * a file that is not one and then reporting every field as missing.
 * `books_authors_link` is the cheapest name that is Calibre's own.
 */
const REQUIRED_TABLES = ["books", "books_authors_link"] as const;

/**
 * The names of the tables this database actually has.
 *
 * Read once and asked of afterwards, rather than letting a query fail: a
 * missing table and a table that is empty are different answers, and only one
 * of them means "this is not a Calibre library".
 */
function tablesIn(db: SqliteDatabase): Set<string> {
  const rows = db.query(
    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')",
  );
  return new Set(
    rows.map((row) => text(row["name"])).filter((name) => name !== null),
  );
}

/**
 * Rows of a link table, grouped by the book they point at.
 *
 * One query a relation and the join done here, rather than one wide `SELECT`
 * with every link table in it: a book with three authors and two identifiers
 * comes back six times from the join, and every field then has to be
 * de-duplicated by whoever reads it.
 */
function groupByBook(
  rows: readonly SqliteRow[],
  value: (row: SqliteRow) => string | null,
): Map<number, string[]> {
  const grouped = new Map<number, string[]>();
  for (const row of rows) {
    const book = integer(row["book"]);
    const one = value(row);
    if (book === null || one === null) continue;
    const existing = grouped.get(book);
    if (existing === undefined) grouped.set(book, [one]);
    else existing.push(one);
  }
  return grouped;
}

/**
 * The ISBN, from whichever identifier carried one.
 *
 * `type = 'isbn'` first, because that is the row Calibre writes it in and a
 * library carrying several identifiers uses the type to say which is which.
 * Then every other identifier, because a household that filed an ISBN under
 * `isbn10` or `ean` still filed an ISBN. Everything goes through `parseIsbn`,
 * so a value that is not a Bookland number with a holding check digit is not an
 * ISBN however it was labelled: same rule and same reason as `opf.ts`.
 */
function readIsbn(identifiers: readonly CalibreIdentifier[]): string | null {
  const declared = identifiers.filter(
    (one) => one.type.trim().toLowerCase() === "isbn",
  );
  for (const candidate of [...declared, ...identifiers]) {
    const isbn = parseIsbn(candidate.value.replace(/^urn:isbn:/i, ""));
    if (isbn !== null) return isbn;
  }
  return null;
}

/**
 * Elements whose text is not the text of the document.
 *
 * **`<script>` is the one that matters and it is not about execution.** The
 * parse below is inert, so nothing runs; what a naive walk does instead is put
 * the script's own source into the book's description, where it is stored and
 * later shown to a reader as prose. A comment carrying `<script>` came from
 * somewhere, and whatever that somewhere wanted, a description reading
 * `alert(1)` is not what the file said about the book.
 */
const SILENT_ELEMENTS = new Set([
  "script",
  "style",
  "template",
  "noscript",
  "iframe",
  "object",
]);

/** Elements that end a paragraph, so the text either side is not one. */
const PARAGRAPH_ELEMENTS = new Set([
  "blockquote",
  "div",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "p",
]);

/** Elements that end a line without ending a paragraph. */
const LINE_ELEMENTS = new Set(["br", "li", "tr"]);

function collectText(node: Node, into: string[]): void {
  if (node.nodeType === Node.TEXT_NODE) {
    into.push(node.textContent ?? "");
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const name = (node as Element).localName;
  if (SILENT_ELEMENTS.has(name)) return;
  for (const child of node.childNodes) collectText(child, into);
  if (PARAGRAPH_ELEMENTS.has(name)) into.push("\n\n");
  else if (LINE_ELEMENTS.has(name)) into.push("\n");
}

/**
 * A Calibre comment as the text it represents.
 *
 * `comments.text` is HTML: Calibre's own editor writes `<p>` and `<i>`, and a
 * description imported from a catalogue arrives with whatever that catalogue
 * used. `description` here is plain text and the detail screen renders it as
 * text, so storing the markup shows a reader their tags.
 *
 * **`DOMParser` with `text/html` rather than a regular expression.** The
 * document it builds is inert: no script runs, no resource is fetched, and an
 * `onerror` on an `<img>` fires nowhere, which is why this is a parse rather
 * than an attempt to strip tags by matching them. Walking it is what keeps a
 * paragraph boundary, where `body.textContent` alone would run a description of
 * six paragraphs into one line and would carry the source of a `<script>` into
 * it besides.
 */
export function plainText(html: string): string | null {
  const document = new DOMParser().parseFromString(html, "text/html");
  const parts: string[] = [];
  collectText(document.body, parts);
  return text(parts.join("").replace(/\n{3,}/g, "\n\n"));
}

/**
 * Read every book in the library, or say why there is none to read.
 *
 * One query a relation rather than one join, and every one of them optional:
 * a library missing `comments` yields books with no description, which is what
 * a library missing `comments` means.
 */
export function readCalibreLibrary(db: SqliteDatabase): CalibreReading {
  const tables = tablesIn(db);
  if (!REQUIRED_TABLES.every((name) => tables.has(name))) {
    return { ok: false, failure: "not-a-calibre-library" };
  }

  const bookColumns = columnsIn(db, "books");
  if (!bookColumns.has("id") || !bookColumns.has("title")) {
    return { ok: false, failure: "not-a-calibre-library" };
  }
  const has = (column: string) => bookColumns.has(column);

  const rows = db.query(
    `SELECT id, title,
            ${has("path") ? "path" : "'' AS path"},
            ${has("pubdate") ? "pubdate" : "NULL AS pubdate"},
            ${has("series_index") ? "series_index" : "NULL AS series_index"}
       FROM books ORDER BY id`,
  );
  if (rows.length === 0) return { ok: false, failure: "empty" };

  const authors = tables.has("authors")
    ? groupByBook(
        db.query(
          `SELECT link.book AS book, authors.name AS name
             FROM books_authors_link link
             JOIN authors ON authors.id = link.author
            ORDER BY link.id`,
        ),
        (row) => {
          const name = text(row["name"]);
          return name !== null && CALIBRE_PLACEHOLDER.author(name)
            ? null
            : name;
        },
      )
    : new Map<number, string[]>();

  const publishers = tables.has("books_publishers_link")
    ? groupByBook(
        db.query(
          `SELECT link.book AS book, publishers.name AS name
             FROM books_publishers_link link
             JOIN publishers ON publishers.id = link.publisher`,
        ),
        (row) => text(row["name"]),
      )
    : new Map<number, string[]>();

  const languages = tables.has("books_languages_link")
    ? groupByBook(
        db.query(
          `SELECT link.book AS book, languages.lang_code AS code
             FROM books_languages_link link
             JOIN languages ON languages.id = link.lang_code
            ORDER BY link.id`,
        ),
        (row) => text(row["code"]),
      )
    : new Map<number, string[]>();

  const series = tables.has("books_series_link")
    ? groupByBook(
        db.query(
          `SELECT link.book AS book, series.name AS name
             FROM books_series_link link
             JOIN series ON series.id = link.series`,
        ),
        (row) => text(row["name"]),
      )
    : new Map<number, string[]>();

  const comments = tables.has("comments")
    ? groupByBook(db.query("SELECT book, text FROM comments"), (row) =>
        text(row["text"]),
      )
    : new Map<number, string[]>();

  const files = tables.has("data")
    ? groupByBook(db.query("SELECT book, format FROM data"), (row) =>
        text(row["format"]),
      )
    : new Map<number, string[]>();

  const identifiers = new Map<number, CalibreIdentifier[]>();
  if (tables.has("identifiers")) {
    for (const row of db.query("SELECT book, type, val FROM identifiers")) {
      const book = integer(row["book"]);
      const type = text(row["type"]);
      const value = text(row["val"]);
      if (book === null || type === null || value === null) continue;
      const existing = identifiers.get(book);
      if (existing === undefined) identifiers.set(book, [{ type, value }]);
      else existing.push({ type, value });
    }
  }

  const books: CalibreBook[] = [];
  for (const row of rows) {
    const id = integer(row["id"]);
    if (id === null) continue;
    const title = text(row["title"]);
    const ownIdentifiers = identifiers.get(id) ?? [];
    const seriesName = series.get(id)?.[0] ?? null;

    books.push({
      id,
      path: text(row["path"]) ?? "",
      title: title !== null && CALIBRE_PLACEHOLDER.title(title) ? null : title,
      authors: authors.get(id) ?? [],
      identifiers: ownIdentifiers,
      isbn: readIsbn(ownIdentifiers),
      publisher: publishers.get(id)?.[0] ?? null,
      year: readYear(row["pubdate"]),
      language: languages.get(id)?.[0] ?? null,
      description: readDescription(comments.get(id)?.[0] ?? null),
      seriesName,
      // Only where a series exists: Calibre defaults this column to 1.0 on
      // every row, so reading it unconditionally files every standalone book
      // as the first volume of nothing.
      seriesIndex: seriesName === null ? null : decimal(row["series_index"]),
      formats: files.get(id) ?? [],
    });
  }

  return { ok: true, books };
}

function readDescription(html: string | null): string | null {
  return html === null ? null : plainText(html);
}

/**
 * The publication year, or `null` where a book could not have one.
 *
 * `pubdate` is an ISO timestamp as text, and what a leading four digit run
 * means is `year.leadingYear`'s question. **This function is the half
 * that knows it is reading a SQLite cell**, which is why it is still here: the
 * shared half took nothing of `sqliteRow`'s vocabulary with it.
 *
 * **The window it applies replaced a refusal of `CALIBRE_UNDEFINED_YEAR` by
 * name.** The name refused one value out of a band this door left open at both
 * ends, so a `pubdate` of `1200-01-01` arrived as the year 1200. The window
 * refuses that value and 101 with it, so nothing the name refused is accepted
 * now, and refusing both ways would be one fact written twice.
 * `CALIBRE_PLACEHOLDER` carries what the dropped arm cost.
 *
 * Measured 2026-09-10 over the household's 897 book reference library, every
 * `books` row: 29 carry the year 101, 0 carry any other year outside the
 * window, and the remaining 868 fall in 1967 to 2025. So the band this closes
 * is empty in that library and the window changes no book in it.
 */
function readYear(value: unknown): number | null {
  return leadingYear(text(value));
}

/**
 * The file's values with Calibre's own placeholders taken back out.
 *
 * `readCalibreLibrary` refuses the two string placeholders by name on the
 * database's side and the year one inside `plausibleYear`'s window. `opf.ts`
 * refuses the year one, by that same window, and refuses neither of the other
 * two, correctly: that module reports what an OPF file says, and `Unknown` is
 * Calibre's convention rather than the format's. A Calibre library's
 * `metadata.opf` is written by Calibre from those same rows, so without this
 * the placeholders arrive back through the gap filling door and land as facts,
 * having been refused at the other one.
 *
 * **The year arm here is the one place the year member is still applied**, and
 * it is not reachable in production: the only producer of a `FileMetadata` that
 * reaches this door is `opf.readOpf`, which applies the window before handing
 * it over. It stays because that window is another module's and is guarded
 * there rather than here, and because this function's contract is a record's
 * placeholders out, not a windowed record's. Its test drives `crossCheck`
 * directly, which is what keeps the arm covered.
 *
 * Measured over the household's 897 book library on 2026-09-08, the 243 books
 * carrying a `metadata.opf`: **57 books take the year 101 from the file**, 28
 * into an empty year and 29 as a counted disagreement against a real year the
 * database already held, and **31 books take `Unknown` back as their author**.
 * The file is right in none of those 88. Refusing here rather than arbitrating
 * is what the numbers support: 57 of the 244 files carry `0101-01-01` and not
 * one of them carries a year the database lacks.
 *
 * The exclusion, stated: `series_index` is the third placeholder and needs
 * nothing here, because `opf.ts` reads `calibre:series_index` only where a
 * `calibre:series` names a series, which is the same guard `readCalibreLibrary`
 * puts on the column. 0 of the 244 files measured carry either.
 */
function withoutPlaceholders(opf: FileMetadata): FileMetadata {
  return {
    ...opf,
    title:
      opf.title !== null && CALIBRE_PLACEHOLDER.title(opf.title)
        ? null
        : opf.title,
    authors: opf.authors.filter((name) => !CALIBRE_PLACEHOLDER.author(name)),
    year:
      opf.year !== null && CALIBRE_PLACEHOLDER.year(opf.year) ? null : opf.year,
  };
}

/** What one book's `metadata.opf` changed about it. */
export interface CalibreCrossCheck {
  readonly book: CalibreBook;
  /** Fields the file supplied where the database had none. */
  readonly filled: number;
  /** Fields both carried, differently. The database keeps its own. */
  readonly disagreed: number;
}

/**
 * One book, checked against the `metadata.opf` beside it.
 *
 * **The database wins and the file fills the gaps.** Same rule as
 * `importing._MARC_GAP_FIELDS` and the same reason: an import may add what a
 * record is missing and may not replace what is already there. Reused rather
 * than restated, because two gap filling rules in one app that differ by a
 * field is a difference nobody would find.
 *
 * **The ISBN is the one exception, and the criterion is checkable rather than a
 * preference**: whichever of the two `parseIsbn` accepts, the database first
 * where both do. A number that fails its own check digit names no book, so
 * "the database has a value" is not a reason to keep it.
 *
 * **Disagreements are counted and not resolved**, and that is now a measured
 * answer rather than a deferral. Over the household's 897 book library on
 * 2026-09-08, the 243 books carrying a `metadata.opf`, the file is right in 28
 * disagreements and the database is right in 42, so neither source wins as a
 * rule.
 *
 * **What that library is, because the numbers below are its history and not a
 * property of OPF files.** All 244 files predate the index: 233 were written
 * 2026-06-07 and 11 on 2024-11-15, against the index's own 2026-08-19. Calibre
 * writes these files from those same rows, so the file is not a second source,
 * it is what the index said two months earlier, and a later metadata
 * enrichment is what introduced the escaping the file is right about. Another
 * household, or a run of the same enrichment after a backup, inverts that. The
 * two denominators differ by the one file whose directory the index no longer
 * names: 244 files on disk, 243 of them beside a book. What each side is right
 * about:
 *
 * - **The file is right about `title` and `publisher`, 28 of 28.** Every one is
 *   an HTML entity the database escaped and the file did not, once, twice or
 *   three times over: `O&#39;Reilly Media` against `O'Reilly Media`, and
 *   `Taylor &amp;amp; Francis` against `Taylor & Francis`. Repeatedly
 *   unescaping the database's value yields the file's exactly, in all 28.
 * - **The database is right about `language`, 42 of 42.** 39 are `eng` against
 *   `en`, one language spelled in two ISO code sets rather than a disagreement
 *   about a fact, and 3 are a book the database calls `deu` and the file calls
 *   `en`. The file is right in none.
 * - **`description`, `series` and the ISBN disagreed in no book**, and 0 of the
 *   244 files carry a `calibre:series` at all.
 *
 * Neither of those two is a rule this reader can apply: unescaping the database
 * is a repair of the database rather than a gap filling rule, and preferring
 * one language code set is a decision about what the column holds. Both are
 * recorded in `docs/decisions.md`. So the count still goes to the member.
 */
export function crossCheck(
  book: CalibreBook,
  file: FileMetadata,
): CalibreCrossCheck {
  // Before anything is compared or counted: a placeholder is neither a fill
  // nor a disagreement, and counting one as either is what puts 57 books of
  // noise in front of the member.
  const opf = withoutPlaceholders(file);
  let filled = 0;
  let disagreed = 0;

  /** Keep the database's value, or take the file's where there is none. */
  function gap(mine: string | null, theirs: string | null): string | null;
  function gap(mine: number | null, theirs: number | null): number | null;
  function gap(
    mine: string | number | null,
    theirs: string | number | null,
  ): string | number | null {
    if (mine !== null && theirs !== null && mine !== theirs) disagreed += 1;
    if (mine !== null) return mine;
    if (theirs !== null) filled += 1;
    return theirs;
  }

  /**
   * The series and the position in it, together.
   *
   * **One decision rather than two**, because a position belongs to the series
   * it counts in: pairing this file's number with the database's name would
   * invent a volume neither source claims.
   */
  function readSeries(): { name: string | null; index: number | null } {
    if (book.seriesName === null) {
      if (opf.seriesName === null) return { name: null, index: null };
      // Two fields when the file supplied both. One was the count for a name
      // and an index together, which is not what `filled` means.
      filled += opf.seriesIndex === null ? 1 : 2;
      return { name: opf.seriesName, index: opf.seriesIndex };
    }
    if (opf.seriesName !== null && opf.seriesName !== book.seriesName) {
      disagreed += 1;
    }
    const sameSeries = opf.seriesName === book.seriesName;
    const index = book.seriesIndex ?? (sameSeries ? opf.seriesIndex : null);
    if (book.seriesIndex === null && index !== null) filled += 1;
    return { name: book.seriesName, index };
  }

  // **Filled and never compared.** The two spell a person differently far more
  // often than they disagree about who wrote the book, so counting `Le Guin,
  // Ursula K.` against `Ursula K. Le Guin` would bury the count this screen
  // exists to show under a difference nobody would act on.
  const authors = book.authors.length > 0 ? book.authors : opf.authors;
  if (book.authors.length === 0 && authors.length > 0) filled += 1;

  // Both sides are already `parseIsbn` output, so this is "whichever of the two
  // is a real ISBN, the database first" written as a coalesce.
  if (book.isbn === null && opf.isbn !== null) filled += 1;
  if (book.isbn !== null && opf.isbn !== null && book.isbn !== opf.isbn) {
    disagreed += 1;
  }

  const series = readSeries();
  return {
    book: {
      ...book,
      title: gap(book.title, opf.title),
      authors,
      isbn: book.isbn ?? opf.isbn,
      publisher: gap(book.publisher, opf.publisher),
      year: gap(book.year, opf.year),
      language: gap(book.language, opf.language),
      // **Through `plainText` like the database's own comment.** A Calibre
      // `metadata.opf` writes `dc:description` as escaped HTML, and `opf.ts`
      // hands back the element's text, so filling this gap raw put the markup
      // the database path exists to drop into the column by the other door.
      //
      // The exclusion, stated: a description that really was plain text and
      // happens to contain something shaped like a tag loses that much of
      // itself. It is the same trade the database's own comment already makes,
      // and the other way round is a description reading `<p>`.
      description: gap(
        book.description,
        opf.description === null ? null : plainText(opf.description),
      ),
      seriesName: series.name,
      seriesIndex: series.index,
    },
    filled,
    disagreed,
  };
}
