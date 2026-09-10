/**
 * The Apple Books reader, against Apple Books shaped stores built here.
 *
 * **Every database below is constructed, and none came off a machine.** No Mac
 * was reachable from where this was written, so the schema is taken from
 * `github.com/tnahs/readstor`, which exports an Apple Books library and ships
 * the stores it is tested against. That is why the column names, the three
 * spellings of `ZEPUBID` and the shape of `Z_METADATA` below are quotations
 * rather than guesses. `src/lib/appleBooks.ts` names the repository, the branch
 * and the date it was read, and is the one home of those: a source in two files
 * is a source that drifts in one of them.
 *
 * A fixture presented as a real library when it is not would be worse than no
 * fixture, so this paragraph is the fixture's provenance and it is meant to be
 * read before the numbers in it are trusted.
 *
 * Built through `databaseOf` and read back through `openSqlite`, so what is
 * asserted is what a `BKLibrary-*.sqlite` does rather than what a stand in was
 * told to answer.
 */

import { describe, expect, it } from "vitest";

import {
  isAppleBooksDatabaseName,
  readAppleBooksLibrary,
  type AppleBook,
  type AppleBooksLibrary,
} from "../../src/lib/appleBooks";
import { openSqlite, type SqliteDatabase } from "../../src/lib/sqlite";
import { databaseOf, engine } from "./sqliteFixtures";

/**
 * `ZBKLIBRARYASSET`, trimmed to the columns this app reads.
 *
 * The store measured has 86 of them, and the trim is the point rather than a
 * shortcut: a reader that only works against the full schema is a reader that
 * breaks on the next release of Books. `ZCONTENTTYPE` is here and is read by
 * nothing, which is what proves the statement names its columns rather than
 * asking for all of them.
 *
 * The types are Core Data's own: `VARCHAR` for every string including `ZYEAR`,
 * and `INTEGER` for every boolean.
 */
const APPLE_SCHEMA = [
  `CREATE TABLE ZBKLIBRARYASSET (
     Z_PK INTEGER PRIMARY KEY,
     Z_ENT INTEGER,
     Z_OPT INTEGER,
     ZCONTENTTYPE INTEGER,
     ZISSAMPLE INTEGER,
     ZISEPHEMERAL INTEGER,
     ZISHIDDEN INTEGER,
     ZISPROOF INTEGER,
     ZASSETID VARCHAR,
     ZTITLE VARCHAR,
     ZAUTHOR VARCHAR,
     ZEPUBID VARCHAR,
     ZYEAR VARCHAR,
     ZLANGUAGE VARCHAR,
     ZPATH VARCHAR
   )`,
  `CREATE TABLE Z_METADATA (Z_VERSION INTEGER PRIMARY KEY, Z_UUID VARCHAR, Z_PLIST BLOB)`,
  `INSERT INTO Z_METADATA (Z_VERSION, Z_UUID) VALUES (1, 'ECD289BE-A6F0-42A4-B971-1F4BB42C3771')`,
];

/**
 * A store from before the columns this reader reaches for existed.
 *
 * Core Data regenerates the table from a model that ships inside Books, so a
 * column arriving or leaving is what an update to the application does. This is
 * the arm where one has left.
 */
const OLD_APPLE_SCHEMA = [
  `CREATE TABLE ZBKLIBRARYASSET (
     Z_PK INTEGER PRIMARY KEY,
     ZASSETID VARCHAR,
     ZTITLE VARCHAR,
     ZAUTHOR VARCHAR
   )`,
];

/** A library holding whatever these statements put in it. */
async function store(schema: string[], ...rows: string[]) {
  const reading = await openSqlite(
    await databaseOf(...schema, ...rows),
    engine,
  );
  if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);
  const read = readAppleBooksLibrary(reading.database);
  reading.database.close();
  return read;
}

/** The library, or a failure raised where the assertion can see it. */
async function libraryOn(...rows: string[]): Promise<AppleBooksLibrary> {
  const read = await store(APPLE_SCHEMA, ...rows);
  if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
  return read.library;
}

async function booksOn(...rows: string[]): Promise<readonly AppleBook[]> {
  return (await libraryOn(...rows)).books;
}

/** One sideloaded book, with every column this reader knows filled in. */
const SIDELOADED = `INSERT INTO ZBKLIBRARYASSET
  (Z_PK, ZCONTENTTYPE, ZISSAMPLE, ZISEPHEMERAL, ZISHIDDEN, ZISPROOF, ZASSETID,
   ZTITLE, ZAUTHOR, ZEPUBID, ZYEAR, ZLANGUAGE, ZPATH)
  VALUES (1, 1, 0, 0, 0, 0, '8E6660FFF4EB8789B4BDF5FAD625CCFC',
          'Think on These Things', 'Krishnamurti', '978-0-06-202639-2', '1964',
          'en-US',
          '/Users/somebody/Library/Containers/com.apple.BKAgentService/Data/Documents/iBooks/Books/8E6660FFF4EB8789B4BDF5FAD625CCFC.epub')`;

/**
 * A row carrying an asset id and whatever `COLUMN=value` pairs are named.
 *
 * Split on the first `=` only, so a value may contain one. Every other column
 * is left null, which is what a library with nothing in that field looks like.
 */
function bare(assetId: string, ...columns: string[]): string {
  const pairs = columns.map((pair) => {
    const at = pair.indexOf("=");
    return { name: pair.slice(0, at), value: pair.slice(at + 1) };
  });
  const names = ["ZASSETID", ...pairs.map((pair) => pair.name)];
  const values = [`'${assetId}'`, ...pairs.map((pair) => pair.value)];
  return `INSERT INTO ZBKLIBRARYASSET (${names.join(", ")})
          VALUES (${values.join(", ")})`;
}

describe("reading a library", () => {
  it("gives back a book with every field the columns carry", async () => {
    expect(await booksOn(SIDELOADED)).toEqual([
      {
        assetId: "8E6660FFF4EB8789B4BDF5FAD625CCFC",
        title: "Think on These Things",
        authors: ["Krishnamurti"],
        isbn: "9780062026392",
        year: 1964,
        language: "en-US",
        format: "EPUB",
      },
    ]);
  });

  it("reports the store's own model version", async () => {
    expect((await libraryOn(SIDELOADED)).schemaVersion).toBe(1);
  });

  it("keeps one author string as one author", async () => {
    // Apple keeps no author list, so two names in `ZAUTHOR` are one value and
    // splitting them on a separator Apple does not document turns one person
    // into two.
    const books = await booksOn(bare("a", "ZAUTHOR='Gilbert & Sullivan'"));

    expect(books[0]?.authors).toEqual(["Gilbert & Sullivan"]);
  });

  it("gives a book with no author no authors rather than an empty one", async () => {
    expect((await booksOn(bare("a")))[0]?.authors).toEqual([]);
  });
});

describe("the identifier a file carried", () => {
  /**
   * `ZEPUBID` is the book's own `dc:identifier` copied verbatim, so the same
   * ISBN arrives under whichever spelling the file used. Three of these four
   * are in the store measured, and `urn:isbn:` is the EPUB 3 spelling that
   * `opf.ts` already strips at its own site.
   */
  const SPELLINGS = [
    { what: "bare", written: "9780465008575", isbn: "9780465008575" },
    { what: "hyphenated", written: "978-0-06-202639-2", isbn: "9780062026392" },
    { what: "prefixed", written: "isbn_9780393316049", isbn: "9780393316049" },
    {
      what: "the EPUB 3 urn",
      written: "urn:isbn:9780393316049",
      isbn: "9780393316049",
    },
  ];

  it.each(SPELLINGS)(
    "reads an ISBN written $what",
    async ({ written, isbn }) => {
      expect((await booksOn(bare("a", `ZEPUBID='${written}'`)))[0]?.isbn).toBe(
        isbn,
      );
    },
  );

  it("reads an ISBN-10, which the identifier may still be", async () => {
    expect((await booksOn(bare("a", "ZEPUBID='0393316041'")))[0]?.isbn).toBe(
      "9780393316049",
    );
  });

  it("reads no ISBN out of an identifier that is not one", async () => {
    // Most `dc:identifier` values are a UUID, and one is not an ISBN because a
    // column called `ZEPUBID` carried it.
    const uuid = "urn:uuid:f9a1c0de-0000-4000-8000-000000000000";
    const books = await booksOn(bare("a", `ZEPUBID='${uuid}'`));

    expect(books[0]?.isbn).toBeNull();
  });

  it("reads no ISBN out of digits that fail their own check", async () => {
    expect(
      (await booksOn(bare("a", "ZEPUBID='9780465008576'")))[0]?.isbn,
    ).toBeNull();
  });
});

describe("what the member has", () => {
  it("refuses a store sample, which nobody bought", async () => {
    const library = await libraryOn(bare("sample", "ZISSAMPLE=1"));

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });

  it("refuses a temporary asset", async () => {
    const library = await libraryOn(bare("temporary", "ZISEPHEMERAL=1"));

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });

  it("refuses a book the member hid, which is them saying it is not theirs", async () => {
    const library = await libraryOn(bare("hidden", "ZISHIDDEN=1"));

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });

  it("keeps a proof copy, which is a book somebody was given", async () => {
    // Named because it is the flag deliberately left out of the refusing set: a
    // proof is a real book on a real shelf, unlike an advertisement for one.
    expect(await booksOn(bare("proof", "ZISPROOF=1"))).toHaveLength(1);
  });

  it("refuses a row with no asset id, which is nothing this app can point at", async () => {
    const library = await libraryOn(
      `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZTITLE) VALUES (1, 'Nameless')`,
    );

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });

  it("reads a flag Core Data wrote as something other than one", async () => {
    // The column is an INTEGER and the value is Apple's, so the test is whether
    // the flag is set rather than whether it equals 1.
    const library = await libraryOn(bare("sample", "ZISSAMPLE=2"));

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });

  it("counts what it refused, so a member can be told there was more", async () => {
    const library = await libraryOn(
      SIDELOADED,
      bare("sample", "ZISSAMPLE=1"),
      bare("hidden", "ZISHIDDEN=1"),
    );

    expect(library.books).toHaveLength(1);
    expect(library.skipped).toBe(2);
  });
});

describe("the format a row points at", () => {
  const PATHS = [
    { what: "an EPUB", path: "/Books/a.epub", format: "EPUB" },
    { what: "a PDF", path: "/Books/a.pdf", format: "PDF" },
    { what: "a Multi-Touch book", path: "/Books/a.ibooks", format: "IBOOKS" },
    { what: "an extension in capitals", path: "/Books/A.EPUB", format: "EPUB" },
  ];

  it.each(PATHS)("reads $what off the path", async ({ path, format }) => {
    expect((await booksOn(bare("a", `ZPATH='${path}'`)))[0]?.format).toBe(
      format,
    );
  });

  it("reads no format off a path naming a file it does not know", async () => {
    expect(
      (await booksOn(bare("a", "ZPATH='/Books/a.m4b'")))[0]?.format,
    ).toBeNull();
  });

  it("reads no format on a book with no file on this machine", async () => {
    // A purchase the member has not downloaded has a row and no path, and a
    // format guessed for one would be a fact about nothing.
    expect((await booksOn(bare("a")))[0]?.format).toBeNull();
  });
});

describe("the year in a library", () => {
  const YEARS = [
    { written: "1964", year: 1964 },
    { written: "1450", year: 1450 },
    { written: "2100", year: 2100 },
    { written: "1449", year: null },
    { written: "2101", year: null },
    { written: "not a year", year: null },
    { written: "0101-01-01T00:00:00+00:00", year: null },
  ];

  it.each(YEARS)("reads $written as $year", async ({ written, year }) => {
    expect((await booksOn(bare("a", `ZYEAR='${written}'`)))[0]?.year).toBe(
      year,
    );
  });
});

describe("a schema this reader does not have all of", () => {
  it("reads what an old store does have", async () => {
    const read = await store(
      OLD_APPLE_SCHEMA,
      `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID, ZTITLE, ZAUTHOR)
         VALUES (1, 'a', 'Think on These Things', 'Krishnamurti')`,
    );

    expect(read.ok && read.library.books).toEqual([
      {
        assetId: "a",
        title: "Think on These Things",
        authors: ["Krishnamurti"],
        isbn: null,
        year: null,
        language: null,
        format: null,
      },
    ]);
  });

  it("keeps a book on a store with none of the flags it refuses by", async () => {
    // A flag that is not there is not a flag that is set, so a column an
    // update removed costs the distinction and never the book.
    const read = await store(
      OLD_APPLE_SCHEMA,
      `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID) VALUES (1, 'a')`,
    );

    expect(read.ok && read.library.skipped).toBe(0);
  });

  it("names the fields no column in this store could fill", async () => {
    const read = await store(
      OLD_APPLE_SCHEMA,
      `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID) VALUES (1, 'a')`,
    );

    expect(read.ok && read.library.missing).toEqual([
      "format",
      "isbn",
      "language",
      "year",
    ]);
  });

  it("has nothing missing on a store carrying every column", async () => {
    expect((await libraryOn(SIDELOADED)).missing).toEqual([]);
  });

  it("says a store with no metadata table has no version", async () => {
    const read = await store(
      OLD_APPLE_SCHEMA,
      `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID) VALUES (1, 'a')`,
    );

    expect(read.ok && read.library.schemaVersion).toBeNull();
  });
});

describe("an unreadable store is one skipped source, never a broken import", () => {
  /**
   * The rule the whole ticket turns on, asserted as a property rather than as a
   * list of cases.
   *
   * A member picks several sources at once and one of them is a library whose
   * schema moved, or a file that is not what they thought it was. That has to
   * cost the one source and nothing else, so every outcome of this reader is a
   * value in a closed union and none of them is a throw. The databases below
   * are built to break it.
   *
   * **Each case carries the reading it should produce**, because asserting only
   * that the answer is one of the shapes is a tautology a case flipping from a
   * library to a failure passes silently.
   */
  const HOSTILE = [
    {
      what: "a database that is somebody else's",
      rows: [`CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)`],
      expected: { failure: "not-an-apple-books-library" },
    },
    {
      what: "another application's Core Data store",
      rows: [
        `CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER PRIMARY KEY, ZBODY VARCHAR)`,
      ],
      expected: { failure: "not-an-apple-books-library" },
    },
    {
      what: "a table with the signature and nothing else",
      rows: [
        `CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER, ZASSETID VARCHAR)`,
        `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID) VALUES (1, 'a')`,
      ],
      expected: { books: 1, skipped: 0 },
    },
    {
      // **The reading here is a book, and that is SQLite rather than this
      // reader being lax.** Every string column is declared VARCHAR, so text
      // affinity turns the integers below into `'2'`, `'3'` and the rest, while
      // the flag columns keep `'nine'` as text because it converts to no
      // integer. So the row reads as a book with a nonsense title and no flag
      // set, which is what testing the value rather than the declared type
      // costs and what `sqliteRow.integer` states at its own site.
      what: "every column carrying the wrong type",
      rows: [
        ...APPLE_SCHEMA,
        `INSERT INTO ZBKLIBRARYASSET
           (Z_PK, ZASSETID, ZTITLE, ZAUTHOR, ZEPUBID, ZYEAR, ZLANGUAGE, ZPATH,
            ZISSAMPLE, ZISEPHEMERAL, ZISHIDDEN)
           VALUES (1, 2, 3, 4, 5, 6, 7, 8, 'nine', 'ten', 'eleven')`,
      ],
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "every column carrying null",
      rows: [...APPLE_SCHEMA, `INSERT INTO ZBKLIBRARYASSET (Z_PK) VALUES (1)`],
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "a view where the table should be",
      rows: [
        `CREATE TABLE elsewhere (Z_PK INTEGER, ZASSETID VARCHAR, ZTITLE VARCHAR)`,
        `CREATE VIEW ZBKLIBRARYASSET AS SELECT * FROM elsewhere`,
      ],
      expected: { failure: "empty" },
    },
    {
      what: "a column name shaped like a statement",
      rows: [
        `CREATE TABLE ZBKLIBRARYASSET ("Z_PK); DROP TABLE ZBKLIBRARYASSET; --" TEXT)`,
      ],
      expected: { failure: "not-an-apple-books-library" },
    },
    {
      what: "a metadata table that is not Core Data's",
      rows: [
        ...APPLE_SCHEMA.slice(0, 1),
        `CREATE TABLE Z_METADATA (something VARCHAR)`,
        `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID) VALUES (1, 'a')`,
      ],
      expected: { books: 1, skipped: 0 },
    },
  ];

  it.each(HOSTILE)(
    "answers rather than throwing for $what",
    async ({ rows, expected }) => {
      const reading = await openSqlite(await databaseOf(...rows), engine);
      if (!reading.ok)
        throw new Error(`expected a database: ${reading.failure}`);

      const read = readAppleBooksLibrary(reading.database);
      reading.database.close();

      expect(
        read.ok
          ? { books: read.library.books.length, skipped: read.library.skipped }
          : { failure: read.failure },
      ).toEqual(expected);
    },
  );

  it("says a file is not an Apple Books library rather than saying it is empty", async () => {
    // Two different sentences to a member holding a file that did not work, and
    // the wrong one sends them looking for books in a file that holds none.
    const read = await store([`CREATE TABLE ZBKLIBRARYASSET (Z_PK INTEGER)`]);

    expect(read).toEqual({
      ok: false,
      failure: "not-an-apple-books-library",
    });
  });

  it("says a library is empty when it is a library with nothing in it", async () => {
    // What a member who copied the store without its `-wal` sidecar gets, which
    // is what their copy says rather than a guess about what it left behind.
    const read = await store(APPLE_SCHEMA);

    expect(read).toEqual({ ok: false, failure: "empty" });
  });

  it("keeps the count when a library holds only what it refuses", async () => {
    const library = await libraryOn(bare("sample", "ZISSAMPLE=1"));

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });
});

describe("the statement is built from this module's own column list", () => {
  it("reads a store carrying a column named like a statement", async () => {
    // **The guard this asserts is the allowlist, and the case has to reach
    // it.** A file whose payload column stops it being recognised as an Apple
    // Books library at all is refused before a statement is composed, so it
    // says nothing about how one is composed: this store has both signature
    // columns and is read.
    //
    // The payload is spelled so that the injected prefix would parse: under a
    // reader selecting every column the store has, the composed SQL is a valid
    // SELECT followed by a DROP. Two things stop it, and this reaches the outer
    // one. `sqlite.ts`'s `PRAGMA query_only` is the inner one.
    //
    // **`survived` therefore fires only when both are gone**, and it is here as
    // depth rather than as this case's guard: measured, removing the allowlist
    // fails the first assertion with the table still standing, and removing the
    // pragma alone fails nothing in this file. The assertion above it is what
    // watches the allowlist, and the case below is what watches the shape of
    // the statement it composes.
    const bytes = await databaseOf(
      `CREATE TABLE ZBKLIBRARYASSET (
         Z_PK INTEGER,
         ZASSETID VARCHAR,
         "ZASSETID FROM ZBKLIBRARYASSET; DROP TABLE secrets; --" VARCHAR
       )`,
      `CREATE TABLE secrets (id INTEGER PRIMARY KEY)`,
      `INSERT INTO ZBKLIBRARYASSET (Z_PK, ZASSETID) VALUES (1, 'a-book')`,
    );
    const reading = await openSqlite(bytes, engine);
    if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);

    const read = readAppleBooksLibrary(reading.database);
    const survived = reading.database.query(
      "SELECT name FROM sqlite_master WHERE name = 'secrets'",
    );
    reading.database.close();

    expect(read.ok && read.library.books.map((book) => book.assetId)).toEqual([
      "a-book",
    ]);
    expect(survived).toHaveLength(1);
  });

  it("names no column it did not ask for, and never asks for all of them", async () => {
    // **The case the injection arm above cannot see.** A reader composing
    // `SELECT *` passes every assertion in this file otherwise: it reads the
    // same books, refuses the same rows, and leaves the same tables standing,
    // while carrying all 86 of a real store's columns per row into memory and
    // dropping the property this module's own docstring turns on. What sees it
    // is the statement, so the statement is what this reads.
    //
    // **Asserted by equality rather than against a list of columns to avoid**,
    // which is the shape this repository keeps paying for: an enumeration of
    // what is unwanted is open, and the column it missed was `Z_PK`. Measured
    // on this file's first draft: `SELECT Z_PK, ${columns.join(", ")} FROM ...`
    // widened the statement, carried no `*`, named none of the three enumerated
    // names, and passed all 57. An equality refuses that, a reorder and a `*` at
    // once, and goes stale **loudly** where an enumeration goes stale silently,
    // which is the whole of what it buys. `WANTED_HERE` below is still a second
    // list and has to move whenever `WANTED` or the fixture does: the module's
    // own docstring already names `ZBOOKDESCRIPTION` as a field waiting on a
    // helper to move, and the day it lands this line needs editing. Measured:
    // dropping `ZTITLE` from `WANTED` fails this case among 3 of 57, and it
    // reads as this test's business, because the statement did lose a member of
    // the module's list. That is the trade, and it is the right way round.
    //
    // **The equality is over every statement the module composes, in order, and
    // not over the one that names the table.** Two drafts refused a widening of
    // the asset statement and let the other one through: `SELECT * FROM
    // Z_METADATA` passed, and so did `SELECT Z_VERSION, Z_PLIST FROM
    // Z_METADATA`, which pulls the blob `appleBooks.ts` argues at length for
    // never opening and spells the harm without a wildcard for a `*` arm to
    // see. A list refuses a statement of any shape, and an added one as well.
    //
    // The module's own list in its order, which this store carries in full, so
    // the equality is sensitive to every member of it rather than to two.
    const WANTED_HERE = [
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
    ];
    const reading = await openSqlite(
      await databaseOf(
        // **The reach of the equality below is this list, and the limit has
        // two halves.** An assertion can only see a statement that names a
        // column the fixture declares, so this one declares **both** every
        // column the module reads and every column its docstring names as
        // deliberately unread. Two drafts each named one half and each left a
        // hole the comment made a reviewer agree with:
        //
        // - Without the unread columns, widening the composed list with
        //   `ZSERIESID` and `ZSEQUENCEDISPLAYNAME` left the statement byte
        //   identical and passed all 57, while asking a real store for two more
        //   columns a row.
        // - Without the read columns, a second statement gated on
        //   `present.has("ZPATH")`, which is this module's own dominant idiom
        //   rather than a contrived shape, never ran here and passed all 57.
        //   The same statement gated on a column this fixture did declare
        //   failed at 1 of 57, which is what proves the gate was never the
        //   evasion: the gate column's absence was.
        //
        // **Deliberately not `APPLE_SCHEMA`**, which is trimmed to what the
        // reader reads, because the trim is that fixture's point and carrying
        // both halves is this one's.
        //
        // **The residue is stated rather than closed**: a statement naming a
        // column nobody has named anywhere is still invisible, and no shape of
        // assertion fixes that. Only this list and the row below do.
        `CREATE TABLE ZBKLIBRARYASSET (
           Z_PK INTEGER PRIMARY KEY,
           ZASSETID VARCHAR,
           ZTITLE VARCHAR,
           ZAUTHOR VARCHAR,
           ZEPUBID VARCHAR,
           ZYEAR VARCHAR,
           ZLANGUAGE VARCHAR,
           ZPATH VARCHAR,
           ZISSAMPLE INTEGER,
           ZISEPHEMERAL INTEGER,
           ZISHIDDEN INTEGER,
           ZBOOKDESCRIPTION VARCHAR,
           ZCONTENTTYPE INTEGER,
           ZDURATION FLOAT,
           ZKIND VARCHAR,
           ZSEQUENCEDISPLAYNAME VARCHAR,
           ZSERIESCONTAINER INTEGER,
           ZSERIESID VARCHAR,
           ZSERIESSORTKEY INTEGER,
           ZISPROOF INTEGER,
           ZISSTOREAUDIOBOOK INTEGER,
           ZSTOREID VARCHAR
         )`,
        // **Every declared column is filled, and that is the second half of
        // the reach limit.** A statement gated on a row value rather than on
        // the schema runs only if the value is there: measured, with this row
        // filling 3 of the 22 columns, a statement gated on
        // `text(row["ZPATH"]) !== null` never ran and passed all 57, where the
        // same statement gated on `present.has("ZPATH")` failed at 1 of 57.
        // The three refusing flags are 0 rather than null for the same reason
        // and have to stay 0, since a 1 would take the row out of the library
        // and the assertion below with it.
        `INSERT INTO ZBKLIBRARYASSET
           (Z_PK, ZASSETID, ZTITLE, ZAUTHOR, ZEPUBID, ZYEAR, ZLANGUAGE, ZPATH,
            ZISSAMPLE, ZISEPHEMERAL, ZISHIDDEN, ZBOOKDESCRIPTION, ZCONTENTTYPE,
            ZDURATION, ZKIND, ZSEQUENCEDISPLAYNAME, ZSERIESCONTAINER,
            ZSERIESID, ZSERIESSORTKEY, ZISPROOF, ZISSTOREAUDIOBOOK, ZSTOREID)
           VALUES (1, 'a-book', 'The Art Spirit', 'Robert Henri',
                   '9780465008575', '1923', 'en-US', '/Books/a-book.epub',
                   0, 0, 0, '<p>not this app''s to read</p>', 1,
                   0.0, 'ebook', 'A Sequence', 0,
                   'series-1', 0, 0, 0, 'store-1')`,
      ),
      engine,
    );
    if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);

    const asked: string[] = [];
    const recording: SqliteDatabase = {
      query(sql, params) {
        asked.push(sql);
        return reading.database.query(sql, params);
      },
      close() {
        reading.database.close();
      },
    };

    const read = readAppleBooksLibrary(recording);
    recording.close();

    // The case has to reach the composition, or it asserts nothing about it.
    expect(read.ok && read.library.books).toHaveLength(1);

    expect(asked).toEqual([
      "PRAGMA table_info(ZBKLIBRARYASSET)",
      `SELECT ${WANTED_HERE.join(", ")} FROM ZBKLIBRARYASSET`,
      "SELECT Z_VERSION FROM Z_METADATA",
    ]);
  });
});

describe("which file is one of these stores", () => {
  const NAMES = [
    { name: "BKLibrary-1-091020131601.sqlite", is: true },
    { name: "BKLibrary-1-000000000000.sqlite", is: true },
    { name: "bklibrary-1-091020131601.SQLITE", is: true },
    { name: "BKLibrary-1-091020131601.sqlite-wal", is: false },
    { name: "BKLibrary-1-091020131601.sqlite-shm", is: false },
    { name: "AEAnnotation_v10312011_1727_local.sqlite", is: false },
    { name: "KoboReader.sqlite", is: false },
    { name: "BKLibrary-1-091020131601.sqlite.zip", is: false },
  ];

  it.each(NAMES)("says $name is $is", ({ name, is }) => {
    // The suffix is a timestamp from when the store was created, so the name is
    // a family rather than a name. The two sidecars are here because they sit
    // beside the store in the same directory and are not databases.
    expect(isAppleBooksDatabaseName(name)).toBe(is);
  });
});
