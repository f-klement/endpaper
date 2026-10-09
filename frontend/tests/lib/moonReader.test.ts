/**
 * The Moon+ Reader backup reader, against backup shaped databases built here.
 *
 * **Every database below is constructed, and none came out of a backup.** No
 * device was reachable from where this was written, so the schema is taken from
 * the two published implementations `src/lib/moonReader.ts` names, which read
 * real backups. That is why the table names, the three column names and the
 * `books` over `tmpbooks` preference below are quotations rather than guesses.
 * That module names the repositories, the commits and the dates, and is the one
 * home of those: a sha in two files is a sha that drifts in one of them.
 *
 * **What is not a quotation is said so where it appears.** Neither source lists
 * the columns those tables carry beyond the three, so nothing here invents one
 * to look real; the only extra column below is an attack, and it is labelled as
 * one.
 *
 * A fixture presented as a real backup's database when it is not would be worse
 * than no fixture, so this paragraph is the fixture's provenance and it is
 * meant to be read before the values in it are trusted.
 *
 * Built through `databaseOf` and read back through `openSqlite`, so what is
 * asserted is what an `mrbooks.db` does rather than what a stand in was told to
 * answer.
 */

import { describe, expect, it } from "vitest";

import {
  databaseTagName,
  namesEntryIn,
  readMoonReaderLibrary,
  DATABASE_FILENAME,
  NAMES_FILENAME,
  type MoonReaderBook,
  type MoonReaderFormat,
  type MoonReaderLibrary,
} from "../../src/lib/moonReader";
import { openSqlite } from "../../src/lib/sqlite";
import { databaseOf, engine } from "./sqliteFixtures";

/**
 * The two library tables, with the columns this app reads.
 *
 * `notes` and `statistics` are here and are read by nothing, which is what
 * proves the reader names its tables rather than taking whatever a backup
 * holds. Both are real: the implementations named in the module read them.
 */
const MOON_READER_SCHEMA = [
  `CREATE TABLE books (filename TEXT PRIMARY KEY, book TEXT, author TEXT)`,
  `CREATE TABLE tmpbooks (filename TEXT PRIMARY KEY, book TEXT, author TEXT)`,
  `CREATE TABLE notes (
     _id INTEGER PRIMARY KEY, book TEXT, highlightColor INTEGER,
     time INTEGER, original TEXT
   )`,
  `CREATE TABLE statistics (
     filename TEXT, usedTime INTEGER, readWords INTEGER, dates TEXT
   )`,
  `PRAGMA user_version = 21`,
];

/** A backup holding whatever these statements put in it. */
async function backup(schema: string[], ...rows: string[]) {
  const reading = await openSqlite(
    await databaseOf(...schema, ...rows),
    engine,
  );
  if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);
  const read = readMoonReaderLibrary(reading.database);
  reading.database.close();
  return read;
}

/** The library, or a failure raised where the assertion can see it. */
async function libraryOn(...rows: string[]): Promise<MoonReaderLibrary> {
  const read = await backup(MOON_READER_SCHEMA, ...rows);
  if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
  return read.library;
}

async function booksOn(...rows: string[]): Promise<readonly MoonReaderBook[]> {
  return (await libraryOn(...rows)).books;
}

/**
 * **A compile time assertion, and the only kind that can make this claim.**
 * `MoonReaderFormat` is derived from `fileName.ts`, so it is exactly as narrow
 * as that map's own declaration: written with an annotation rather than
 * `satisfies`, the derivation widens silently to every member of `BookFormat`,
 * including the physical ones, and the registry row that passes this field
 * through stops compiling. Nothing at runtime can see that, so this line is
 * what fails instead, and `bun run typecheck` covers this file.
 *
 * The three named here are `stores.ts::StoreFormat`, which is what a store row
 * takes. Deliberately spelled rather than imported: the point is that the
 * derived type has not drifted from what the registry accepts, and importing
 * the thing under test would make the two agree by construction.
 */
const FORMAT_IS_NO_WIDER_THAN_A_STORE_ROW_TAKES:
  "ebook" | "audiobook" | "comic" = "ebook" as MoonReaderFormat;

const IN_BOOKS = `INSERT INTO books (filename, book, author)
  VALUES ('/storage/emulated/0/Books/dune.epub', 'Dune', 'Frank Herbert')`;

const IN_TMPBOOKS = `INSERT INTO tmpbooks (filename, book, author)
  VALUES ('/storage/emulated/0/Books/dune.epub', 'dune', 'F. Herbert')`;

describe("a book the backup carries", () => {
  it("reads a row the curated table holds", async () => {
    expect(await booksOn(IN_BOOKS)).toEqual([
      {
        path: "/storage/emulated/0/Books/dune.epub",
        title: "Dune",
        authors: ["Frank Herbert"],
        format: "ebook",
      },
    ]);
  });

  it("reads a row only the scanned table holds", async () => {
    const books = await booksOn(IN_TMPBOOKS);
    expect(books).toHaveLength(1);
    expect(books[0]?.title).toBe("dune");
  });

  it("counts a book in both tables once and skips neither row", async () => {
    const library = await libraryOn(IN_BOOKS, IN_TMPBOOKS);
    expect(library.books).toHaveLength(1);
    expect(library.skipped).toBe(0);
  });

  it("prefers the curated table's value for a field it fills", async () => {
    const books = await booksOn(IN_BOOKS, IN_TMPBOOKS);
    expect(books[0]?.title).toBe("Dune");
    expect(books[0]?.authors).toEqual(["Frank Herbert"]);
  });

  it("keeps the scanned table's value where the curated one is null", async () => {
    const books = await booksOn(
      IN_TMPBOOKS,
      `INSERT INTO books (filename, book, author)
         VALUES ('/storage/emulated/0/Books/dune.epub', 'Dune', NULL)`,
    );
    expect(books[0]?.title).toBe("Dune");
    expect(books[0]?.authors).toEqual(["F. Herbert"]);
  });

  it("keeps a curated row the scanned table never saw", async () => {
    const books = await booksOn(
      IN_TMPBOOKS,
      `INSERT INTO books (filename, book, author)
         VALUES ('/storage/emulated/0/Books/left-hand.epub',
                 'The Left Hand of Darkness', 'Ursula K. Le Guin')`,
    );
    expect(books.map((book) => book.path)).toEqual([
      "/storage/emulated/0/Books/dune.epub",
      "/storage/emulated/0/Books/left-hand.epub",
    ]);
  });

  it("gives a book with no author no authors at all", async () => {
    const books = await booksOn(
      `INSERT INTO books (filename, book, author)
         VALUES ('/Books/anonymous.epub', 'Beowulf', NULL)`,
    );
    expect(books[0]?.authors).toEqual([]);
  });

  it("gives a book with a blank author no authors at all", async () => {
    const books = await booksOn(
      `INSERT INTO books (filename, book, author)
         VALUES ('/Books/anonymous.epub', 'Beowulf', '   ')`,
    );
    expect(books[0]?.authors).toEqual([]);
  });
});

describe("what the file's own name settles", () => {
  const formatOf = async (path: string) =>
    (
      await booksOn(
        `INSERT INTO books (filename, book, author)
           VALUES ('${path}', 'A Book', 'A Writer')`,
      )
    )[0]?.format;

  it("reads a book from a name the app walks", async () => {
    expect(await formatOf("/Books/dune.epub")).toBe(
      FORMAT_IS_NO_WIDER_THAN_A_STORE_ROW_TAKES,
    );
  });

  it("reads a comic from a name the app walks", async () => {
    expect(await formatOf("/Books/issue.cbz")).toBe("comic");
  });

  it("reads nothing from a name this app has no member for", async () => {
    expect(await formatOf("/Books/notes.txt")).toBeNull();
  });

  it("reads nothing from a name with no extension at all", async () => {
    expect(await formatOf("/Books/dune")).toBeNull();
  });
});

describe("a row that is not a book", () => {
  it("skips a row with no path and counts it", async () => {
    const library = await libraryOn(
      IN_BOOKS,
      `INSERT INTO books (filename, book, author)
         VALUES (NULL, 'Nowhere', 'Nobody')`,
    );
    expect(library.books).toHaveLength(1);
    expect(library.skipped).toBe(1);
  });

  it("counts a pathless row in each table separately", async () => {
    const library = await libraryOn(
      `INSERT INTO books (filename, book, author) VALUES (NULL, 'A', NULL)`,
      `INSERT INTO tmpbooks (filename, book, author) VALUES (NULL, 'B', NULL)`,
    );
    expect(library.skipped).toBe(2);
    expect(library.books).toEqual([]);
  });
});

describe("what the backup says about itself", () => {
  it("reports the version the app set", async () => {
    expect((await libraryOn(IN_BOOKS)).schemaVersion).toBe(21);
  });

  it("reports no version where nothing set one", async () => {
    const read = await backup(
      [
        `CREATE TABLE books (filename TEXT, book TEXT, author TEXT)`,
        `CREATE TABLE tmpbooks (filename TEXT, book TEXT, author TEXT)`,
      ],
      IN_BOOKS,
    );
    if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
    expect(read.library.schemaVersion).toBeNull();
  });

  it("names no missing field where every column is there", async () => {
    expect((await libraryOn(IN_BOOKS)).missing).toEqual([]);
  });

  it("names the field a column that is not there would have filled", async () => {
    const read = await backup(
      [
        `CREATE TABLE books (filename TEXT, book TEXT)`,
        `CREATE TABLE tmpbooks (filename TEXT, book TEXT)`,
      ],
      `INSERT INTO books (filename, book) VALUES ('/Books/dune.epub', 'Dune')`,
    );
    if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
    expect(read.library.missing).toEqual(["authors"]);
    expect(read.library.books[0]?.title).toBe("Dune");
    expect(read.library.books[0]?.authors).toEqual([]);
  });
});

describe("an unreadable store is one skipped source, never a broken import", () => {
  it("refuses a database with neither library table", async () => {
    const read = await backup([`CREATE TABLE shelf (id INTEGER)`]);
    expect(read).toEqual({ ok: false, failure: "not-a-moon-reader-backup" });
  });

  /**
   * **Both signature columns are required, and these two are a diagonal.**
   * Each carries one of the pair and not the other, so a reader asking for
   * either alone, or for one of the two, reads a table that is not this app's
   * and answers `empty` where the answer is that this is not one of these.
   */
  it("refuses a books table carrying the path column and no title", async () => {
    const read = await backup([
      `CREATE TABLE books (filename TEXT, book_title TEXT, writer TEXT)`,
    ]);
    expect(read).toEqual({ ok: false, failure: "not-a-moon-reader-backup" });
  });

  it("refuses a books table carrying the title column and no path", async () => {
    const read = await backup([
      `CREATE TABLE books (id INTEGER PRIMARY KEY, book TEXT, path TEXT)`,
    ]);
    expect(read).toEqual({ ok: false, failure: "not-a-moon-reader-backup" });
  });

  it("reads the one table a backup has where the other is gone", async () => {
    const read = await backup(
      [`CREATE TABLE tmpbooks (filename TEXT, book TEXT, author TEXT)`],
      IN_TMPBOOKS,
    );
    if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
    expect(read.library.books).toHaveLength(1);
  });

  it("says a backup with the tables and no rows is empty", async () => {
    expect(await backup(MOON_READER_SCHEMA)).toEqual({
      ok: false,
      failure: "empty",
    });
  });

  it("says a backup whose every row was refused is not empty", async () => {
    const library = await libraryOn(
      `INSERT INTO books (filename, book, author) VALUES (NULL, 'A', NULL)`,
    );
    expect(library.books).toEqual([]);
    expect(library.skipped).toBe(1);
  });

  /**
   * **A column nothing here names cannot reach a statement.**
   *
   * The fourth column is an attack and no backup has one: it is spelled so that
   * a reader building its statement out of the table's own column names would
   * emit `SELECT filename, book, author, book, author FROM sqlite_master; --
   * FROM books`. The reader asks for the three literals it spells, so the
   * column is never named and the library reads normally.
   */
  it("never names a column of the file's own choosing", async () => {
    const read = await backup(
      [
        `CREATE TABLE books (
           filename TEXT, book TEXT, author TEXT,
           "book, author FROM sqlite_master; --" TEXT
         )`,
        `CREATE TABLE tmpbooks (filename TEXT, book TEXT, author TEXT)`,
      ],
      IN_BOOKS,
    );
    if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
    expect(read.library.books).toHaveLength(1);
    expect(read.library.books[0]?.title).toBe("Dune");
  });
});

describe("which entry of a backup archive is the database", () => {
  /** One build's backup directory. The other spells it without the `p`. */
  const DIR = "com.flyersoft.moonreaderp/";

  /**
   * An index longer than any fixture below, whose every line is hostile.
   *
   * **The shape of the answer is asserted and not two examples of it.** A
   * lookup returning the matched line itself is right for a short index and
   * wrong for a real one, which is 60 lines rather than 4, so a fixture of four
   * lines cannot tell the two apart.
   */
  const LONG = (mrbooks: number) =>
    Array.from({ length: 60 }, (_, line) =>
      line + 1 === mrbooks
        ? `${DIR}${DATABASE_FILENAME}`
        : "../../../etc/passwd",
    ).join("\n");

  it("answers the line number its name sits on", () => {
    expect(
      databaseTagName(
        `${DIR}${NAMES_FILENAME}`,
        "positions10.xml\nmrbooks.db\n",
      ),
    ).toBe(`${DIR}2.tag`);
  });

  it("answers a sibling of the index and not a name at the archive root", () => {
    expect(databaseTagName(`${DIR}${NAMES_FILENAME}`, "mrbooks.db\n")).toBe(
      `${DIR}1.tag`,
    );
  });

  it("answers a bare name for an index that is at the root", () => {
    expect(databaseTagName(NAMES_FILENAME, "a.xml\nmrbooks.db\n")).toBe(
      "2.tag",
    );
  });

  it("answers for a line carrying the directory the backup wrote", () => {
    expect(
      databaseTagName(`${DIR}${NAMES_FILENAME}`, `a.xml\n${DIR}mrbooks.db\n`),
    ).toBe(`${DIR}2.tag`);
  });

  /**
   * **The directory comes from the archive's own entry and never from the
   * matching line**, and telling those apart needs them to differ. Every other
   * fixture here gives the line the same directory as the entry, which is what
   * a real backup does and is exactly why none of them can see this.
   */
  it("answers the entry's directory where the line names another", () => {
    expect(
      databaseTagName(
        `${DIR}${NAMES_FILENAME}`,
        "a.xml\n/storage/emulated/0/Books/mrbooks.db\n",
      ),
    ).toBe(`${DIR}2.tag`);
  });

  it("answers a bare name where the line names a directory", () => {
    expect(
      databaseTagName(NAMES_FILENAME, "a.xml\nsomewhere/else/mrbooks.db\n"),
    ).toBe("2.tag");
  });

  it("answers nothing for an archive listing no database", () => {
    expect(
      databaseTagName(`${DIR}${NAMES_FILENAME}`, "positions10.xml\ncovers\n"),
    ).toBeNull();
  });

  it("does not answer for a name this one is only the end of", () => {
    expect(databaseTagName(NAMES_FILENAME, "oldmrbooks.db\n")).toBeNull();
  });

  it("answers the first of two, so an index is never ambiguous", () => {
    expect(databaseTagName(NAMES_FILENAME, "mrbooks.db\nmrbooks.db\n")).toBe(
      "1.tag",
    );
  });

  it("answers for an index whose lines carry a carriage return", () => {
    expect(databaseTagName(NAMES_FILENAME, "a.xml\r\nmrbooks.db\r\n")).toBe(
      "2.tag",
    );
  });

  /**
   * **No part of an answer is ever a line of the index.** A backup is a
   * member's file and its index is member supplied text, so what a line decides
   * is whether its number is returned and never what is returned.
   */
  it("answers the directory and a number for an index of any length", () => {
    for (const at of [1, 37, 60]) {
      const answer = databaseTagName(`${DIR}${NAMES_FILENAME}`, LONG(at));
      expect(answer).toBe(`${DIR}${at}.tag`);
      expect(answer).toMatch(/^[^/]+\/[0-9]+\.tag$/);
    }
  });

  it("answers a number for a hostile index at the archive root", () => {
    const answer = databaseTagName(NAMES_FILENAME, LONG(37).replace(DIR, ""));
    expect(answer).toMatch(/^[0-9]+\.tag$/);
  });

  /**
   * **Two member supplied things reach this function and both are hostile
   * here.** Every fixture above passes an entry name the archive could have
   * written and varies only the lines, which applies the attack to the half
   * that was already safe. An entry name climbing out of the archive is the
   * other half, and it is refused rather than concatenated.
   */
  it("answers nothing for an index name that climbs out of the archive", () => {
    expect(
      databaseTagName(`../../../etc/${NAMES_FILENAME}`, LONG(37)),
    ).toBeNull();
  });

  it("answers nothing for an index name that is rooted", () => {
    expect(databaseTagName(`/etc/${NAMES_FILENAME}`, LONG(37))).toBeNull();
  });

  /**
   * **The precondition is enforced and not stated.** This used to slice
   * negatively and answer a truncation of the name it was given, so
   * `covers.dat` came back as `covers.da1.tag`.
   */
  it("answers nothing for a name that is not the index at all", () => {
    expect(databaseTagName("covers.dat", "mrbooks.db\n")).toBeNull();
  });

  /**
   * **Two `string` parameters transpose without a type error**, so the check
   * above is what stands between that and a plausible wrong answer: this used
   * to cut into the name it was given and answer `posi2.tag`.
   */
  it("answers nothing for another of the backup's own files", () => {
    expect(databaseTagName("positions10.xml", "mrbooks.db\n")).toBeNull();
  });

  it("answers nothing for a name the index name is only the end of", () => {
    expect(databaseTagName(`old${NAMES_FILENAME}`, "mrbooks.db\n")).toBeNull();
  });
});

describe("where the archive keeps its index", () => {
  const entries = (...names: string[]) => names.map((name) => ({ name }));

  it("finds an index below the directory the backup wrote", () => {
    expect(
      namesEntryIn(
        entries(
          "com.flyersoft.moonreaderp/1.tag",
          `com.flyersoft.moonreaderp/${NAMES_FILENAME}`,
        ),
      ),
    ).toBe(`com.flyersoft.moonreaderp/${NAMES_FILENAME}`);
  });

  it("finds an index the other build wrote, whose directory differs", () => {
    expect(
      namesEntryIn(entries(`com.flyersoft.moonreader/${NAMES_FILENAME}`)),
    ).toBe(`com.flyersoft.moonreader/${NAMES_FILENAME}`);
  });

  it("finds an index sitting at the archive root", () => {
    expect(namesEntryIn(entries("1.tag", NAMES_FILENAME))).toBe(NAMES_FILENAME);
  });

  it("finds nothing in an archive that is not one of these backups", () => {
    expect(namesEntryIn(entries("Takeout/archive_browser.html"))).toBeNull();
  });

  it("does not answer for a name this one is only the end of", () => {
    expect(namesEntryIn(entries(`old${NAMES_FILENAME}`))).toBeNull();
  });

  it("takes an index nested more than one directory deep", () => {
    expect(namesEntryIn(entries(`a/b/${NAMES_FILENAME}`))).toBe(
      `a/b/${NAMES_FILENAME}`,
    );
  });

  /**
   * **A zip's entry names are a member supplied list**, so the name this
   * answers is as untrusted as the bytes and the answer is concatenated into a
   * path. `zip.ts` matches an entry by exact name against that same list, so
   * nothing here is reachable that the archive did not already declare; these
   * are refused so that what the module claims about its answer stays true.
   */
  it("refuses an index name that climbs out of the archive", () => {
    expect(namesEntryIn(entries(`../../../etc/${NAMES_FILENAME}`))).toBeNull();
  });

  it("refuses an index name that is rooted", () => {
    expect(namesEntryIn(entries(`/etc/${NAMES_FILENAME}`))).toBeNull();
  });

  it("refuses an index name with a bare current directory in it", () => {
    expect(namesEntryIn(entries(`a/./${NAMES_FILENAME}`))).toBeNull();
  });

  it("refuses an index name with an empty segment in it", () => {
    expect(namesEntryIn(entries(`a//${NAMES_FILENAME}`))).toBeNull();
  });

  it("passes a refused name over and takes the real index behind it", () => {
    expect(
      namesEntryIn(
        entries(
          `../${NAMES_FILENAME}`,
          `${"com.flyersoft.moonreader"}/${NAMES_FILENAME}`,
        ),
      ),
    ).toBe(`com.flyersoft.moonreader/${NAMES_FILENAME}`);
  });
});
