/**
 * What a Moon+ Reader backup says about the books on somebody's phone.
 *
 * **Not an integration with a company.** Moon+ Reader is an Android reading
 * app that keeps its library in a database of its own and writes that database
 * into a backup archive when the member asks it for one, so this reads a file
 * they already have from hardware they own. Nothing here talks to the app's
 * authors, nothing here opens a book, and nothing here touches protection: it
 * reads catalogue metadata about what somebody has.
 *
 * Pure, in `kobo.ts`'s shape: it takes something that answers SQL and returns
 * records. `sqlite.ts` opens the file and says why it could not, and the engine
 * it needs is the one the Calibre import already ships.
 * `docs/device-libraries.md` carries what a second store over that engine costs.
 *
 * ## The archive is the route, and no path on a device is claimed
 *
 * **Both published readings below start from the app's own Backup and neither
 * names a location on the phone**, so neither does this. What that Backup
 * writes is a zip in which every file is renamed to `<line>.tag`, the real
 * names being the lines of `_names.list`. So the database is found by the line
 * number its own name sits on, and never by a name the archive carries.
 *
 * **Nothing here spells a path inside a member's archive, and that is the
 * finding rather than the style.** The entries sit under one directory named
 * for the build that wrote them, and the two builds write two different names,
 * so a spelled prefix covers one of them and silently finds nothing in the
 * other. `namesEntryIn` derives that directory from the entries themselves and
 * `databaseTagName` answers the index's sibling, which is the shape
 * `takeout.ts` already uses for the same reason. `zip.ts` opens the archive;
 * which entry to ask it for is the question answered here.
 *
 * **The file a member ends up holding is named `.mrpro` or `.mrstd`**, one per
 * build, and it is a zip under either name. Worth stating where a picker is
 * configured: a member browsing for a `.zip` finds nothing.
 *
 * ## Where the schema was read, and what was not done
 *
 * Two published implementations, both reading real backups, both read
 * 2026-09-11:
 *
 * - `github.com/iamkroot/moonreader-py` at commit `708c4c6` of 2026-02-28,
 *   `src/moon_reader/compute_read_stats.py`. It names the two library tables
 *   and the three columns below, and it is where the rule about reading both of
 *   them comes from.
 * - `github.com/ecntu/moonwise` at commit `1c0c653` of 2026-02-07, `import.py`
 *   and `README.md`, which read the `notes` table and treat its `book` column
 *   as the book's title, and which are where the archive's own layout is
 *   described. That is the second reading of what `book` means, and it is a
 *   different author on a different table.
 *
 * **Neither reaches an ISBN, a publisher, a year, a language or a series**, and
 * `WANTED` below is three columns because three is what is established. A
 * fourth would be a guess, and a guess that happened to name a real column
 * would file whatever it holds as whatever this module called it.
 *
 * **No phone was read.** The fixtures in `tests/lib/moonReader.test.ts` are
 * constructed from those two sources rather than captured from a device, and
 * they say so at their own site. What that leaves untested is whether a real
 * backup carries a value none of this expects, which is the same thing every
 * paragraph above is about.
 *
 * ## The library is two tables and reading one of them is a bug
 *
 * `books` and `tmpbooks` carry the same three columns, and the implementation
 * above reads a row from each and prefers `books` field by field. So a title
 * the member edited sits in one and the scan that found the file sits in the
 * other, and a reader asking only `books` answers with part of a library while
 * looking like it worked.
 *
 * **This reads both and merges on the path, which is a superset of that
 * implementation's own query**, and the difference is stated because it is a
 * deviation: a right join from `tmpbooks` drops a `books` row with no
 * `tmpbooks` partner, and such a row is a file the app's own library table
 * holds. Both tables list files on the member's device, so neither carries the
 * question `kobo.ts` answers with `Accessibility`: there is nothing here that
 * somebody does not have.
 *
 * ## What a Moon+ Reader backup cannot supply, stated rather than discovered
 *
 * - **Authors as separate values.** `author` is one string and there is no
 *   author table, so `authors` has at most one member. Splitting it would need
 *   a separator the app does not document, and a wrong guess turns one person
 *   into two.
 * - **An identifier that is not a path.** `filename` is the file's own location
 *   and is the only key either table has, so moving a book on the device gives
 *   it a new identity here. That is a fact about the app rather than about this
 *   reader: repairing paths after a move is what its own users write scripts
 *   for.
 * - **Highlights, notes and reading progress.** `notes` and `statistics` are
 *   real and are not read: a read status in this app belongs to a member rather
 *   than to a book, and whether an import writes one is a decision about the
 *   import flow.
 */

import {
  FORMAT_FOR_EXTENSION,
  supportedExtension,
  type SupportedExtension,
} from "./fileName";
import type { SqliteDatabase, SqliteRow } from "./sqlite";
import { columnsIn, integer, text } from "./sqliteRow";

/** One book the backup says is on the member's device. */
export interface MoonReaderBook {
  /**
   * Where the file sits on the device, and the only key either table has.
   *
   * Not stable across a move, and the docstring above says why that is the
   * app's property rather than this reader's.
   */
  readonly path: string;
  readonly title: string | null;
  /** At most one, and the docstring above says why. */
  readonly authors: readonly string[];
  /**
   * What kind of object the path says the file is, where its name settles one.
   *
   * **No list of extensions lives here.** `fileName.ts` owns what a name
   * settles and is already the one home of it, so a name that app has no member
   * for answers `null` there and `null` here. A member who renamed a file loses
   * this field and loses nothing else, which is the bound worth stating: the
   * name is theirs and the app records no format anywhere.
   */
  readonly format: MoonReaderFormat | null;
}

/**
 * What a path can be read as, which is narrower than the app's whole vocabulary.
 *
 * **Derived rather than spelled**, so an extension added to `fileName.ts` widens
 * this and fails its caller to compile rather than arriving as a value nothing
 * downstream has a word for. A written out union would have been three members
 * wider than anything this module can produce.
 */
export type MoonReaderFormat = Exclude<
  (typeof FORMAT_FOR_EXTENSION)[SupportedExtension],
  ""
>;

/**
 * A field this backup's schema could not fill.
 *
 * **There is no arm for the title, and `SIGNATURE` is why**: a table with no
 * `book` column is not one of these tables at all, so a readable backup always
 * has one and a missing title is unreachable rather than merely unobserved.
 */
export type MoonReaderField = "authors";

/** Why a database yielded no library. Closed, one sentence each on screen. */
export type MoonReaderFailure =
  /** Opens as SQLite, and is not a Moon+ Reader backup's database. */
  | "not-a-moon-reader-backup"
  /** A Moon+ Reader backup with no book rows in it at all. */
  | "empty";

export interface MoonReaderLibrary {
  /**
   * The books, which can be none of them.
   *
   * A backup whose every row was refused is a library with no books in it and
   * not an empty backup, `kobo.ts`'s distinction and its reason.
   */
  readonly books: readonly MoonReaderBook[];
  /**
   * Rows in either table that carried no path.
   *
   * **This and `books.length` do not add up to the rows read**, and that is the
   * difference from every other store here: the two tables overlap, so one book
   * is commonly two rows and is counted once. A number rather than a list: it
   * exists so a member can be told the backup held rows this could not place.
   */
  readonly skipped: number;
  /**
   * The app's own version for this database, where it set one.
   *
   * `PRAGMA user_version` is where Android's `SQLiteOpenHelper` keeps the
   * version it migrates from, so an app built on it states its schema version
   * here whether or not it meant to publish one. Informational, and read rather
   * than acted on: every decision below is taken from the columns that are
   * actually there, which is the same question asked of the file rather than of
   * a number the file states about itself.
   *
   * **Zero is the unset default and is reported as no version**, because a
   * database nobody versioned and a database at version zero are not
   * distinguishable here and only one of them is a claim.
   */
  readonly schemaVersion: number | null;
  /** Fields no column in this backup could fill. Sorted, so it compares. */
  readonly missing: readonly MoonReaderField[];
}

export type MoonReaderReading =
  | { readonly ok: true; readonly library: MoonReaderLibrary }
  | { readonly ok: false; readonly failure: MoonReaderFailure };

/** The database's name inside the backup, which is a line in `_names.list`. */
export const DATABASE_FILENAME = "mrbooks.db";

/** The archive entry listing what every other entry was really called. */
export const NAMES_FILENAME = "_names.list";

/**
 * The library tables, in the order they are read.
 *
 * **`books` is read last so that its values win**, which is the direction the
 * implementation this was taken from coalesces in. Reversing it would prefer
 * the scan over whatever the member edited.
 */
const TABLES = ["tmpbooks", "books"] as const;

/**
 * The columns this reader will use, and this module is the only place they are
 * spelled.
 *
 * **Nothing outside this list is ever put into a statement.** The names that
 * reach the `SELECT` below are the members of this array that the table also
 * has, so a member supplied file decides which of these literals are used and
 * never what they are. That is the whole of the injection argument: a column
 * called `x FROM sqlite_master; DROP` on a hostile file matches no member here
 * and is not read. The table names are literals in `TABLES` for the same
 * reason.
 */
const WANTED = ["filename", "book", "author"] as const;

/**
 * The two columns without which a table is not one of these.
 *
 * **A table called `books` is not a signature.** Calibre keeps one and so does
 * half of everything else; what is this app's own is a `books` table whose rows
 * carry a `filename` and a `book`, the second of which is the title under a
 * name almost nothing else uses.
 *
 * **Requiring `book` is what makes a missing title unreachable**, which is the
 * reason `MoonReaderField` has one arm. Dropping either name from here would
 * grow that type rather than only loosen this check.
 */
const SIGNATURE = ["filename", "book"] as const;

/** Which of `WANTED` no readable table has, as the fields they fill. */
function missingFields(present: Set<string>): MoonReaderField[] {
  const fields = new Map<MoonReaderField, string>([["authors", "author"]]);
  return [...fields]
    .filter(([, column]) => !present.has(column))
    .map(([field]) => field)
    .sort();
}

/**
 * The app's own version for this database, where it set one.
 *
 * `PRAGMA user_version` answers 0 on a database that never set it, which is
 * every database and not a version, so 0 is reported as none.
 */
function schemaVersionOf(db: SqliteDatabase): number | null {
  const version = integer(db.query("PRAGMA user_version")[0]?.["user_version"]);
  return version === null || version === 0 ? null : version;
}

/** What the file's own name settles about the object it holds. */
function readFormat(path: string): MoonReaderFormat | null {
  const extension = supportedExtension(path);
  if (extension === null) return null;
  // `""` is what an extension whose object has no member says there, and it is
  // the same answer as an extension nothing recognises.
  return FORMAT_FOR_EXTENSION[extension] || null;
}

/** The row's fields, with anything this table did not carry left null. */
function bookOf(row: SqliteRow, path: string): MoonReaderBook {
  const author = text(row["author"]);
  return {
    path,
    title: text(row["book"]),
    authors: author === null ? [] : [author],
    format: readFormat(path),
  };
}

/**
 * The same book seen in both tables, with `books`'s value preferred.
 *
 * Field by field rather than row by row, because that is what the
 * implementation this was taken from does: a `books` row carrying a title and
 * no author keeps the author the scan found.
 *
 * **Two fields decide anything, and the other two cannot differ.** The merge is
 * keyed on the path, so both rows carry the same one, and the format is a pure
 * function of that path.
 *
 * **They are named anyway rather than spread**, which is the whole reason this
 * is a literal: naming every field is what makes a fifth one on
 * `MoonReaderBook` a compile error here instead of silently taking `later`'s
 * value. A spread is shorter and says nothing about the field nobody has
 * written yet.
 */
function preferring(
  earlier: MoonReaderBook,
  later: MoonReaderBook,
): MoonReaderBook {
  return {
    path: later.path,
    format: later.format,
    title: later.title ?? earlier.title,
    authors: later.authors.length > 0 ? later.authors : earlier.authors,
  };
}

/**
 * Read a Moon+ Reader backup's library, or say why there is not one.
 *
 * Never throws for anything a file can contain. Every way this can fail is a
 * value in `MoonReaderReading`, because the caller's job is the same for all of
 * them: report one source it could not read and carry on with the others.
 * `tests/lib/moonReader.test.ts` asserts that against databases built to break
 * it.
 */
export function readMoonReaderLibrary(db: SqliteDatabase): MoonReaderReading {
  const columns = new Map(
    TABLES.map((table) => [table, columnsIn(db, table)] as const),
  );
  const readable = TABLES.filter((table) =>
    SIGNATURE.every((column) => columns.get(table)?.has(column)),
  );
  if (readable.length === 0) {
    return { ok: false, failure: "not-a-moon-reader-backup" };
  }

  let rows = 0;
  let skipped = 0;
  const books = new Map<string, MoonReaderBook>();
  for (const table of readable) {
    const present = columns.get(table) ?? new Set<string>();
    // Only the members of `WANTED` this table has, which is what makes the
    // interpolation below an interpolation of this module's own literals.
    const asked = WANTED.filter((column) => present.has(column));
    const read = db.query(`SELECT ${asked.join(", ")} FROM ${table}`);
    rows += read.length;
    for (const row of read) {
      const path = text(row["filename"]);
      if (path === null) {
        skipped += 1;
        continue;
      }
      const book = bookOf(row, path);
      const seen = books.get(path);
      books.set(path, seen === undefined ? book : preferring(seen, book));
    }
  }
  if (rows === 0) return { ok: false, failure: "empty" };

  const present = new Set(
    readable.flatMap((table) => [...(columns.get(table) ?? [])]),
  );
  return {
    ok: true,
    library: {
      books: [...books.values()],
      skipped,
      schemaVersion: schemaVersionOf(db),
      missing: missingFields(present),
    },
  };
}

/**
 * The directory an index entry sits in, or `null` for a name that is not one.
 *
 * **Both doors ask this same question, and that is the point rather than
 * tidiness.** `namesEntryIn` chooses an entry and `databaseTagName` builds an
 * answer out of one, so a rule enforced at the first door only is a rule a
 * caller reaching the second directly does not get.
 *
 * **The check is three arms over the segments, and naming fewer is how a
 * comment comes to justify a guard it does not describe.** A segment is refused
 * when it is empty, `.`, or `..`, each pinned by its own test. A name beginning
 * with `/` is refused by the first of those rather than by an arm of its own,
 * because its leading segment is the empty one; that is worth saying because
 * "rooted" is the word for it and no line here spells that word.
 *
 * **What it therefore does not refuse is a drive letter**, so `C:/` passes.
 * Stated rather than fixed: a zip entry name may not carry one at all under
 * APPNOTE 4.4.17, and nothing here resolves a name against a filesystem.
 *
 * The entries of a zip are a member supplied list, so the name is as untrusted
 * as the bytes; `zip.ts` matches an entry by exact name against that same list,
 * so nothing is reachable through this that the archive did not already
 * declare, and the reason to refuse anyway is that the answer is concatenated
 * into a path and a false claim about it would be carried forward.
 *
 * **An empty segment is refused too**, because `a//b` and `a/b` name the same
 * directory to some readers and not to others, and neither is a name a backup
 * writes.
 */
function directoryOf(namesEntry: string): string | null {
  if (namesEntry === NAMES_FILENAME) return "";
  if (!namesEntry.endsWith(`/${NAMES_FILENAME}`)) return null;
  const directory = namesEntry.slice(0, -NAMES_FILENAME.length);
  const segments = directory.slice(0, -1).split("/");
  const plain = segments.every(
    (segment) => segment !== "" && segment !== "." && segment !== "..",
  );
  return plain ? directory : null;
}

/**
 * Where the archive keeps its index, taken from the archive rather than guessed.
 *
 * **The directory the entries sit under is the build's own name and there are
 * two of them**, so this asks the entries which one this archive used instead
 * of spelling either. Only the shape of a name is read here, and `directoryOf`
 * is the whole of what that shape has to be.
 *
 * **The first entry that is an index wins, and one that is not is passed over
 * rather than ending the search**, so an archive declaring a hostile name ahead
 * of its real index still reads.
 *
 * Structurally typed on purpose. It needs a name and nothing else, so it takes
 * neither a `ZipArchive` nor a `File`, and this module stays free of both.
 */
export function namesEntryIn(
  entries: readonly { readonly name: string }[],
): string | null {
  const found = entries.find((entry) => directoryOf(entry.name) !== null);
  return found?.name ?? null;
}

/**
 * Which entry of a backup archive is the database, from the archive's own index.
 *
 * The backup renames every file to its line number in `_names.list` with a
 * `.tag` suffix, so this reads that text and answers the index's own sibling
 * with a name built from an integer.
 *
 * **Every character of an answer is either a directory this module checked or a
 * decimal number**, which is the claim the tests pin and is narrower than the
 * one an earlier draft made. Two different member supplied things reach here
 * and they are refused separately: no **line** of the index is ever returned,
 * so a line reading `../../../etc/passwd` decides only whether its number is
 * the one returned; and the **entry name** is put through `directoryOf` here as
 * well as in `namesEntryIn`, so a caller that skipped the first door is refused
 * at this one. `tests/lib/moonReader.test.ts` asserts the shape of every answer
 * rather than examples of it, and feeds both halves something hostile at once.
 *
 * **The first match wins and the name is matched whole.** A backup carries one
 * `mrbooks.db`, and requiring a path separator or the start of the line keeps
 * `oldmrbooks.db` from answering. `null` says this text names no database,
 * which is a zip that is not one of these backups.
 */
export function databaseTagName(
  namesEntry: string,
  names: string,
): string | null {
  // Not a precondition left to a comment: a name that is not an index used to
  // slice negatively here and answer a truncation of itself, `covers.dat`
  // yielding `covers.da1.tag`.
  const directory = directoryOf(namesEntry);
  if (directory === null) return null;
  const lines = names.split("\n");
  for (const [index, line] of lines.entries()) {
    const name = line.trim();
    if (name === DATABASE_FILENAME || name.endsWith(`/${DATABASE_FILENAME}`)) {
      return `${directory}${index + 1}.tag`;
    }
  }
  return null;
}
