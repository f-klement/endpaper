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
 *   `google`, `goodreads`, `doi` and whatever a plugin invented; `BookCreate`
 *   has one identifier column and it is the ISBN. Of the 897 book reference
 *   library that is 568 books served and 244 more carrying only an identifier
 *   with no home here.
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
 */

import { parseIsbn } from "./isbn";
import type { OpfRecord } from "./opf";
import type { SqliteDatabase, SqliteRow } from "./sqlite";

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
 * the second century. `bookBounds` would not catch it: 101 is inside the
 * `year` column's range, which is what makes this a value to refuse by name
 * rather than a value to bound.
 */
const CALIBRE_UNDEFINED_YEAR = 101;

/** What Calibre writes where a person did not say. Not a title and not a name. */
const CALIBRE_UNKNOWN = "Unknown";

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

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function integer(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.trunc(value);
}

function decimal(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

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
 * The columns one table has, so a Calibre that renamed one loses a field.
 *
 * **Exported for its own test and for nothing else.** The refusal below has one
 * call site and that site passes a literal, so no name that fails the check is
 * ever constructed inside this module: a test going through `readCalibreLibrary`
 * is green whether the check is there or not. A guard nothing can reach is a
 * guard on the "stated" rung wearing a test's name.
 */
export function columnsIn(db: SqliteDatabase, table: string): Set<string> {
  // **A table name cannot be a bound parameter in `PRAGMA`, so it is checked
  // rather than trusted.** Every value passed here today is a literal in this
  // module, and a comment saying so is what stops holding when somebody passes
  // a name out of `tablesIn`, which is read from a member supplied file.
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(table)) return new Set();
  const rows = db.query(`PRAGMA table_info(${table})`);
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
          return name === CALIBRE_UNKNOWN ? null : name;
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
      title: title === CALIBRE_UNKNOWN ? null : title,
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
 * The publication year, or `null` for Calibre's way of saying it has none.
 *
 * `pubdate` is an ISO timestamp as text. Only the leading four digits are read,
 * for `opf.readYear`'s reason: a timezone offset makes the day either side of
 * midnight ambiguous and no book's year turns on it.
 */
function readYear(value: unknown): number | null {
  const match = /^(\d{4})/.exec(text(value) ?? "");
  if (match === null) return null;
  const year = Number(match[1]);
  return year === CALIBRE_UNDEFINED_YEAR ? null : year;
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
 * **Disagreements are counted and not resolved.** The reference library is
 * recorded as carrying damage in 57 books that the OPF corrects, and what that
 * damage is has not been characterised here: the library was not reachable from
 * where this was written. Inventing a rule for it would be inventing which of
 * two values is the wrong one, so the count is reported to the member before
 * the write instead, and `docs/decisions.md` carries the open question.
 */
export function crossCheck(
  book: CalibreBook,
  opf: OpfRecord,
): CalibreCrossCheck {
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
