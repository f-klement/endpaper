/**
 * The Kobo reader, against Kobo shaped databases built here.
 *
 * **Every database below is constructed, and none came off a device.** No Kobo
 * was reachable from where this was written, so the schema is taken from
 * calibre's KoboTouch driver, which is a working implementation of this same
 * read against real hardware. That is why the column names, the `Accessibility`
 * values and the two spellings of `IsDownloaded` below are quotations rather
 * than guesses. `src/lib/kobo.ts` names the file, the commit and the date it
 * was read, and is the one home of those: a sha in two files is a sha that
 * drifts in one of them.
 *
 * A fixture presented as a real device's database when it is not would be worse
 * than no fixture, so this paragraph is the fixture's provenance and it is
 * meant to be read before the numbers in it are trusted.
 *
 * Built through `databaseOf` and read back through `openSqlite`, so what is
 * asserted is what a `KoboReader.sqlite` does rather than what a stand in was
 * told to answer.
 */

import { describe, expect, it } from "vitest";

import {
  readKoboLibrary,
  type KoboBook,
  type KoboLibrary,
} from "../../src/lib/kobo";
import { openSqlite } from "../../src/lib/sqlite";
import { databaseOf, engine } from "./sqliteFixtures";

/**
 * The `content` table, trimmed to the columns this app reads.
 *
 * A real device carries about a hundred more, and the trim is the point rather
 * than a shortcut: a reader that only works against the full schema is a reader
 * that breaks on the next firmware. `ContentType` is here and is read by
 * nothing, which is what proves the statement names its columns rather than
 * asking for all of them.
 *
 * `IsDownloaded` is declared with numeric affinity so that both spellings
 * survive being written: SQLite keeps `1` as a number and `'true'` as text in
 * such a column, and the reader is asserted against both. Which affinity a
 * given firmware uses is not documented anywhere and is not what these tests
 * are about.
 *
 * **The stated version is a parameter and the columns do not move with it.**
 * That is what a device does: `dbversion` is a number the file writes about
 * itself, and no firmware removes a column to match a lower one. `null` builds
 * the table away entirely, which is the only thing this reader treats as the
 * absence of a version.
 */
function schemaAt(version: number | null): string[] {
  const stated =
    version === null
      ? []
      : [
          `CREATE TABLE dbversion (version INTEGER NOT NULL)`,
          `INSERT INTO dbversion (version) VALUES (${version})`,
        ];
  return [
    `CREATE TABLE content (
       ContentID TEXT NOT NULL PRIMARY KEY,
       ContentType TEXT,
       MimeType TEXT,
       BookID TEXT,
       Title TEXT,
       Attribution TEXT,
       Publisher TEXT,
       Language TEXT,
       ISBN TEXT,
       Series TEXT,
       SeriesNumber TEXT,
       SeriesNumberFloat REAL,
       DateCreated TEXT,
       Accessibility INTEGER,
       IsDownloaded BOOL,
       ___ExpirationStatus INTEGER
     )`,
    ...stated,
  ];
}

/** A current device, which is the one every test below asks for by default. */
const KOBO_SCHEMA = schemaAt(170);

/**
 * A row at one accessibility, downloaded or not.
 *
 * At module scope because two describes need it: what a value is named, and
 * that neither the name nor the refusal moves with the version the device
 * states about itself.
 */
function row(id: string, accessibility: number, downloaded: string): string {
  return `INSERT INTO content
      (ContentID, Title, Accessibility, IsDownloaded)
      VALUES ('${id}', 'A Book', ${accessibility}, ${downloaded})`;
}

/**
 * A device from before `Accessibility`, `ISBN` and the series columns existed.
 *
 * calibre gates those behind schema versions 16, 46 and 65, so a device this
 * old is not a hypothetical: it is the arm of calibre's own query that
 * substitutes defaults for the columns that are not there.
 */
const OLD_KOBO_SCHEMA = [
  `CREATE TABLE content (
     ContentID TEXT NOT NULL PRIMARY KEY,
     MimeType TEXT,
     BookID TEXT,
     Title TEXT,
     Attribution TEXT,
     DateCreated TEXT
   )`,
];

/** A device holding whatever these statements put on it. */
async function device(schema: string[], ...rows: string[]) {
  const reading = await openSqlite(
    await databaseOf(...schema, ...rows),
    engine,
  );
  if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);
  const read = readKoboLibrary(reading.database);
  reading.database.close();
  return read;
}

/** The library, or a failure raised where the assertion can see it. */
async function libraryOn(...rows: string[]): Promise<KoboLibrary> {
  const read = await device(KOBO_SCHEMA, ...rows);
  if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
  return read.library;
}

async function booksOn(...rows: string[]): Promise<readonly KoboBook[]> {
  return (await libraryOn(...rows)).books;
}

/** One purchased book, with every column this reader knows filled in. */
const PURCHASED = `INSERT INTO content
  (ContentID, ContentType, MimeType, BookID, Title, Attribution, Publisher,
   Language, ISBN, Series, SeriesNumber, SeriesNumberFloat, DateCreated,
   Accessibility, IsDownloaded, ___ExpirationStatus)
  VALUES ('a1b2c3d4-0000-4000-8000-000000000001', '6',
          'application/x-kobo-epub+zip', NULL, 'Dune', 'Frank Herbert',
          'Chilton Books', 'en', '9780441013593', 'Dune Chronicles', '1', 1.0,
          '1965-08-01T00:00:00.000', 1, 'true', 0)`;

/**
 * What `PURCHASED` reads back as.
 *
 * At module scope because the version arms assert it too: a gate on any column
 * calibre gates is a change to one of these fields, and a list of names alone
 * would not see it.
 */
const DUNE = {
  contentId: "a1b2c3d4-0000-4000-8000-000000000001",
  title: "Dune",
  authors: ["Frank Herbert"],
  isbn: "9780441013593",
  publisher: "Chilton Books",
  year: 1965,
  language: "en",
  seriesName: "Dune Chronicles",
  seriesIndex: 1,
  format: "KEPUB",
  acquisition: "purchase",
} satisfies KoboBook;

describe("reading a device", () => {
  it("gives back a book with every field the columns carry", async () => {
    const [book] = await booksOn(PURCHASED);

    expect(book).toEqual(DUNE);
  });

  it("reports the device's own schema version", async () => {
    expect((await libraryOn(PURCHASED)).schemaVersion).toBe(170);
  });

  it("reads a chapter row as part of its book rather than as a book", async () => {
    // A book is a row with no BookID and its chapters point back at it. A
    // reader that misses this files a novel as three hundred books.
    //
    // **The chapter carries the same `Accessibility` as its book, and that is
    // what makes this a test of the clause.** Without it the row is refused for
    // being unowned instead, and deleting `WHERE BookID IS NULL` from the
    // reader left all 38 tests in this file green. Measured. `skipped` is
    // asserted beside the length for the same reason: a chapter excluded by
    // the clause is not a row the member was refused.
    const library = await libraryOn(
      PURCHASED,
      `INSERT INTO content (ContentID, BookID, Title, Accessibility)
         VALUES ('a1b2c3d4-0000-4000-8000-000000000001!!chapter-1',
                 'a1b2c3d4-0000-4000-8000-000000000001', 'Chapter One', 1)`,
    );

    expect(library).toMatchObject({ books: [{ title: "Dune" }], skipped: 0 });
  });

  it("tells a sideloaded book from a purchased one", async () => {
    const [book] = await booksOn(
      `INSERT INTO content
         (ContentID, MimeType, Title, Attribution, Accessibility, IsDownloaded)
         VALUES ('file:///mnt/onboard/Herbert, Frank/Dune.epub',
                 'application/epub+zip', 'Dune', 'Frank Herbert', -1, 'true')`,
    );

    expect(book).toMatchObject({ acquisition: "sideloaded", format: "EPUB" });
  });

  it("reads an ISBN only where the value is one", async () => {
    const [book] = await booksOn(
      `INSERT INTO content (ContentID, Title, ISBN, Accessibility)
         VALUES ('1', 'Dune', 'not-an-isbn', 1)`,
    );

    expect(book?.isbn).toBeNull();
  });
});

describe("what the member owns", () => {
  /**
   * The ContentIDs that came back, sorted.
   *
   * Sorted because the reader sends no `ORDER BY`: the order rows come back in
   * is the engine's business and asserting it would be asserting something this
   * module does not promise.
   */
  async function keptOn(...rows: string[]): Promise<string[]> {
    const read = await device(KOBO_SCHEMA, ...rows);
    // **Raised rather than answered as `[]`.** Every refusal case below asserts
    // an empty list, and a reader that failed outright would satisfy all of
    // them while filtering nothing: the first draft of this helper did exactly
    // that, and four tests passed on the failure branch.
    if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
    return read.library.books.map((book) => book.contentId).sort();
  }

  it("keeps a book from every store arm calibre names", async () => {
    // What this test is for is that all four are kept. Which arm each number is
    // is asserted below, separately, because keeping a row and naming it are
    // two things and a reader can get the second wrong while passing this.
    expect(
      await keptOn(
        row("arm-1", 1, "'true'"),
        row("arm-2", 2, "'true'"),
        row("arm-8", 8, "'true'"),
        row("arm-9", 9, "'true'"),
      ),
    ).toEqual(["arm-1", "arm-2", "arm-8", "arm-9"]);
  });

  /**
   * Which arm each number is, one row per value.
   *
   * **This restates `kobo.ts`'s table and that is now the point rather than a
   * second home.** Until a row could say how the member came by it, the arms
   * were interchangeable and naming them in a test bought a drift; now `8` and
   * `9` decide whether a Kobo Plus title and a public library loan import as
   * something the member owns, so which number is which is behaviour and a test
   * that does not pin it leaves the whole distinction unenforced.
   *
   * **One case each rather than one database of five**, so a reader that
   * answered the same name for every row fails four of these instead of
   * passing a single `toEqual` that happened to be sorted the same way.
   */
  it.each([
    [-1, "sideloaded"],
    [1, "purchase"],
    [2, "purchase"],
    [8, "subscription"],
    [9, "loan"],
  ])("reads accessibility %i as %s", async (accessibility, acquisition) => {
    const [book] = await booksOn(row("1", accessibility, "'true'"));

    expect(book?.acquisition).toBe(acquisition);
  });

  it("keeps a purchase the member has archived rather than downloaded", async () => {
    // Endpaper carries what somebody owns rather than what is on the device
    // tonight, and an archived purchase is still owned. calibre excludes these
    // by default because it is managing the device's files instead.
    expect(await keptOn(row("archived", 1, "'false'"))).toEqual(["archived"]);
  });

  it("refuses a recommendation and a preview, which nobody bought", async () => {
    // Accessibility 4 and 6 are the store advertising at the member. Importing
    // one tells them they own a book they have never had.
    const kept = await keptOn(
      row("recommendation", 4, "'true'"),
      row("preview", 6, "'true'"),
    );

    expect(kept).toEqual([]);
  });

  it("refuses an accessibility it does not recognise", async () => {
    // The direction is the decision: a firmware inventing a value loses a real
    // book visibly, in `skipped`, rather than gaining an advert invisibly.
    expect(await keptOn(row("from-the-future", 77, "'true'"))).toEqual([]);
  });

  it("refuses a sideloaded book the member has deleted", async () => {
    // Kobo keeps the row and clears the flag rather than removing it.
    expect(await keptOn(row("deleted", -1, "'false'"))).toEqual([]);
  });

  it("refuses the expired row a deleted book leaves behind", async () => {
    expect(
      await keptOn(
        `INSERT INTO content
           (ContentID, Title, Accessibility, IsDownloaded, ___ExpirationStatus)
           VALUES ('expired', 'A Book', 1, 'true', 3)`,
      ),
    ).toEqual([]);
  });

  it("reads both spellings of the downloaded flag", async () => {
    // Both spellings, and which firmware writes which is `kobo.ts`'s to say.
    // A reader testing one of the two imports nothing from the other kind of
    // device. These are sideloaded rows, where the flag is what decides.
    const kept = await keptOn(
      row("older", -1, "'true'"),
      row("newer", -1, "1"),
      row("older-deleted", -1, "'false'"),
      row("newer-deleted", -1, "0"),
    );

    // **Both directions of both spellings.** A draft that built the numeric
    // spelling only as `1` was green against a reader answering `true` for
    // every number, which imports a book the member deleted.
    expect(kept).toEqual(["newer", "older"]);
  });

  it("counts what it refused, so a member can be told there was more", async () => {
    const library = await libraryOn(
      PURCHASED,
      row("preview", 6, "'true'"),
      row("deleted", -1, "'false'"),
    );

    expect(library.skipped).toBe(2);
  });
});

describe("the version the device states about itself", () => {
  /**
   * A row whose two series columns disagree, so that the later of them is
   * visible.
   *
   * `SeriesNumberFloat` arrived at schema version 136 and `SeriesNumber` at 65.
   * With both columns saying `1`, a gate on either reads the same number and
   * nothing goes red, which is how the first draft of this describe left one of
   * calibre's five gates unguarded while asserting it covered them.
   */
  const DISAGREEING_SERIES = `INSERT INTO content
    (ContentID, Title, Accessibility, IsDownloaded, Series, SeriesNumber,
     SeriesNumberFloat)
    VALUES ('series-float', 'A Book', 1, 'true', 'A Sequence', '7', 7.5)`;

  /**
   * One whole library, read off devices differing only in what they state.
   *
   * **This is the enforcement for `schemaVersionOf`'s claim that the number is
   * read and never acted on**, which was a sentence in a docstring and nothing
   * else until this test.
   *
   * **Every `dbversion` threshold in calibre's driver has an arm below it and
   * an arm at or above it**, which is the bound rather than a round set.
   * Counted at commit `71a1997`: sixteen thresholds, the lowest 8 and the
   * highest `dbversion >= 191`, and the top arm is calibre's own
   * `supported_dbversion` of 220, the newest schema it claims to read.
   * **Recount from the driver rather than from this paragraph**, and note what
   * it does not cover: a gate above 220, and a path this library does not
   * walk.
   *
   * Three arms are there because a mutation ran green without them. `188` is
   * the version `isTrue` names, and a boolean gated there was invisible while
   * the list stopped at 170. `55` against `56` are the two calibre's own
   * firmware comment separates. And no version table at all is what this reader
   * answers `null` for where calibre substitutes `0`, so a gate spelled against
   * a missing version lands on that arm and nowhere else.
   *
   * **A whole library and not a list of names**, because a gate can move a
   * column rather than a value: the header's list of five is the one to recount
   * from, and the warning on it is there too. So every field of a filled book
   * is asserted, with `missing` and the refused count beside it. A draft
   * asserting the names alone was green against a reader that dropped the
   * series on a device stating less than 65.
   *
   * **And every refusal this reader makes, because whole in its fields is not
   * whole in its paths.** A library asserting each field of each book it kept
   * was green against a gate on `___ExpirationStatus`, which is a column this
   * reader gates by presence and which no other row here carried. The three
   * refused rows added for that are each refused by one path and no other, so
   * a count of five says which five.
   *
   * **The empty `ContentID` was guarded by nothing in this repository**, which
   * is what pulling that thread found rather than what it was pulled for:
   * dropping that arm of the refusal passed the whole frontend suite. Neither
   * hostile case that looks like it covers it can reach it, one writing an
   * integer into a column with text affinity and the other being refused by
   * the accessibility path first.
   *
   * **The chapter row is excluded rather than refused**, so it moves neither
   * list nor count and is here for the one thing a refusal row cannot cover:
   * `WHERE BookID IS NULL` is gateable too, and a version gate on it was green
   * across all eight arms without it.
   *
   * The version is asserted back as well: read and reported is the whole of
   * what this module does with it, and a reader that stopped reading it would
   * satisfy the first half of that alone.
   */
  it.each([
    { states: "no version at all", version: null },
    { states: "0", version: 0 },
    { states: "53", version: 53 },
    { states: "55", version: 55 },
    { states: "56", version: 56 },
    { states: "170", version: 170 },
    { states: "188", version: 188 },
    { states: "220", version: 220 },
  ])(
    "reads the same library on a device stating $states",
    async ({ version }) => {
      const read = await device(
        schemaAt(version),
        PURCHASED,
        DISAGREEING_SERIES,
        row("bought-and-removed", 1, "'false'"),
        row("sideloaded", -1, "'true'"),
        row("sideloaded-and-deleted", -1, "'false'"),
        row("kobo-plus", 8, "'true'"),
        row("overdrive", 9, "'true'"),
        row("preview", 6, "'true'"),
        // Each of the three below is downloaded and otherwise unremarkable, so
        // that exactly one refusal can account for it: the expired row, then a
        // `ContentID` this reader cannot use, then an `Accessibility` that is
        // there as a column and empty on the row.
        `INSERT INTO content
           (ContentID, Title, Accessibility, IsDownloaded, ___ExpirationStatus)
           VALUES ('expired', 'A Book', 1, 'true', 3)`,
        `INSERT INTO content (ContentID, Title, Accessibility, IsDownloaded)
           VALUES ('', 'A Book', 1, 'true')`,
        `INSERT INTO content (ContentID, Title, IsDownloaded)
           VALUES ('no-accessibility', 'A Book', 'true')`,
        // Excluded by the statement's own clause rather than refused, so it
        // moves neither `kept` nor `skipped`. It is here because that clause is
        // gateable too, and a version gate on it was green without this row.
        `INSERT INTO content (ContentID, BookID, Title, Accessibility)
           VALUES ('chapter-1', 'a1b2c3d4-0000-4000-8000-000000000001',
                   'Chapter One', 1)`,
      );
      if (!read.ok) throw new Error(`expected a library: ${read.failure}`);
      const books = read.library.books;

      expect({
        schemaVersion: read.library.schemaVersion,
        missing: read.library.missing,
        skipped: read.library.skipped,
        // Name and id together: a version gate that renamed a row without
        // dropping it is the outcome this ticket was about, and a list of ids
        // alone is green for it.
        kept: books
          .map((book) => `${book.contentId} ${book.acquisition}`)
          .sort(),
        filled: books.find((book) => book.contentId === DUNE.contentId) ?? null,
        fromTheFloatColumn:
          books.find((book) => book.contentId === "series-float")
            ?.seriesIndex ?? null,
      }).toEqual({
        schemaVersion: version,
        missing: [],
        skipped: 5,
        kept: [
          "a1b2c3d4-0000-4000-8000-000000000001 purchase",
          "bought-and-removed purchase",
          "kobo-plus subscription",
          "overdrive loan",
          "series-float purchase",
          "sideloaded sideloaded",
        ],
        filled: DUNE,
        fromTheFloatColumn: 7.5,
      });
    },
  );
});

describe("a series position", () => {
  it("comes from the float column where the firmware has one", async () => {
    const [book] = await booksOn(
      `INSERT INTO content
         (ContentID, Title, Accessibility, Series, SeriesNumber,
          SeriesNumberFloat)
         VALUES ('1', 'Dune Messiah', 1, 'Dune Chronicles', '2', 2.0)`,
    );

    expect(book?.seriesIndex).toBe(2);
  });

  it("falls back to the text column, which every firmware has", async () => {
    const [book] = await booksOn(
      `INSERT INTO content
         (ContentID, Title, Accessibility, Series, SeriesNumber)
         VALUES ('1', 'Children of Dune', 1, 'Dune Chronicles', '3')`,
    );

    expect(book?.seriesIndex).toBe(3);
  });

  it("is not read on a book in no series", async () => {
    // A position on a standalone book is not a first volume, which is the rule
    // `calibre.ts` reached for Calibre's own default of 1.0.
    const [book] = await booksOn(
      `INSERT INTO content (ContentID, Title, Accessibility, SeriesNumber)
         VALUES ('1', 'Dune', 1, '1')`,
    );

    expect(book).toMatchObject({ seriesName: null, seriesIndex: null });
  });
});

describe("the year on a device", () => {
  /** The year read off a DateCreated of this value. */
  async function yearOf(created: string): Promise<number | null> {
    const [book] = await booksOn(
      `INSERT INTO content (ContentID, Title, Accessibility, DateCreated)
         VALUES ('1', 'A Book', 1, '${created}')`,
    );
    return book?.year ?? null;
  }

  it("reads the year out of an ISO timestamp", async () => {
    expect(await yearOf("1965-08-01T00:00:00.000")).toBe(1965);
  });

  it("keeps the years at each end of the plausible window", async () => {
    // The boundary arm `bookBounds.test.ts` asks every reader for: any
    // contiguous widening of an end has to contain the point outside it.
    expect(await yearOf("1450-01-01T00:00:00.000")).toBe(1450);
    expect(await yearOf("2100-01-01T00:00:00.000")).toBe(2100);
  });

  it("refuses the year immediately outside each end", async () => {
    expect(await yearOf("1449-01-01T00:00:00.000")).toBeNull();
    expect(await yearOf("2101-01-01T00:00:00.000")).toBeNull();
  });

  it("refuses a date field carrying something that is not a date", async () => {
    expect(await yearOf("sometime")).toBeNull();
  });
});

describe("a schema this reader does not have all of", () => {
  it("reads what an old device does have", async () => {
    const read = await device(
      OLD_KOBO_SCHEMA,
      `INSERT INTO content (ContentID, MimeType, Title, Attribution, DateCreated)
         VALUES ('file:///mnt/onboard/Dune.epub', 'application/epub+zip',
                 'Dune', 'Frank Herbert', '1965-08-01T00:00:00.000')`,
    );

    expect(read.ok).toBe(true);
    expect(read.ok && read.library.books[0]).toMatchObject({
      title: "Dune",
      authors: ["Frank Herbert"],
      year: 1965,
      format: "EPUB",
    });
  });

  it("cannot say how an old device's book got there", async () => {
    // There was nowhere on that firmware to record it, so the honest answer is
    // that there is no answer rather than a default that reads as one. The
    // book is still kept: a missing column costs the distinction and not the
    // row, which is what separates this from a refusal.
    const read = await device(
      OLD_KOBO_SCHEMA,
      `INSERT INTO content (ContentID, Title) VALUES ('1', 'Dune')`,
    );

    expect(read.ok && read.library.books[0]?.acquisition).toBe("unrecorded");
  });

  it("names the fields no column on this device could fill", async () => {
    const read = await device(
      OLD_KOBO_SCHEMA,
      `INSERT INTO content (ContentID, Title) VALUES ('1', 'Dune')`,
    );

    expect(read.ok && read.library.missing).toEqual([
      "isbn",
      "language",
      "publisher",
      "series",
    ]);
  });

  it("has nothing missing on a device carrying every column", async () => {
    expect((await libraryOn(PURCHASED)).missing).toEqual([]);
  });

  it("says a device with no version table has no version", async () => {
    const read = await device(
      OLD_KOBO_SCHEMA,
      `INSERT INTO content (ContentID, Title) VALUES ('1', 'Dune')`,
    );

    expect(read.ok && read.library.schemaVersion).toBeNull();
  });
});

describe("an unreadable store is one skipped source, never a broken import", () => {
  /**
   * The rule the whole ticket turns on, asserted as a property rather than as a
   * list of cases.
   *
   * A member picks several sources at once and one of them is a device whose
   * firmware moved, or a file that is not what they thought it was. That has to
   * cost the one source and nothing else, so every outcome of this reader is a
   * value in a closed union and none of them is a throw. The databases below
   * are built to break it.
   *
   * **Each case carries the reading it should produce.** An earlier draft
   * asserted only that the answer was one of the shapes, which is a tautology:
   * a case flipping from a library to a failure passed it silently.
   */
  const HOSTILE = [
    {
      what: "a database that is somebody else's",
      rows: [`CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)`],
      expected: { failure: "not-a-kobo-device" },
    },
    {
      what: "a content table that is not Kobo's",
      rows: [`CREATE TABLE content (id INTEGER PRIMARY KEY, body TEXT)`],
      expected: { failure: "not-a-kobo-device" },
    },
    {
      what: "a Kobo table with the signature and nothing else",
      rows: [
        `CREATE TABLE content (ContentID TEXT, BookID TEXT)`,
        `INSERT INTO content (ContentID, BookID) VALUES ('1', NULL)`,
      ],
      expected: { books: 1, skipped: 0 },
    },
    {
      what: "every column carrying the wrong type",
      rows: [
        ...KOBO_SCHEMA,
        `INSERT INTO content
           (ContentID, MimeType, Title, Attribution, Publisher, Language, ISBN,
            Series, SeriesNumber, SeriesNumberFloat, DateCreated, Accessibility,
            IsDownloaded, ___ExpirationStatus)
           VALUES (1, 2, 3, 4, 5, 6, 7, 8, 9, 'ten', 11, 'twelve', 13,
                   'fourteen')`,
      ],
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "every column carrying null",
      rows: [
        ...KOBO_SCHEMA,
        `INSERT INTO content (ContentID, BookID) VALUES ('1', NULL)`,
      ],
      expected: { books: 0, skipped: 1 },
    },
    {
      what: "a view where the table should be",
      rows: [
        `CREATE TABLE elsewhere (ContentID TEXT, BookID TEXT, Title TEXT)`,
        `CREATE VIEW content AS SELECT * FROM elsewhere`,
      ],
      expected: { failure: "empty" },
    },
    {
      what: "a column name shaped like a statement",
      rows: [
        `CREATE TABLE content ("ContentID); DROP TABLE content; --" TEXT)`,
      ],
      expected: { failure: "not-a-kobo-device" },
    },
  ];

  it.each(HOSTILE)(
    "answers rather than throwing for $what",
    async ({ rows, expected }) => {
      const reading = await openSqlite(await databaseOf(...rows), engine);
      if (!reading.ok)
        throw new Error(`expected a database: ${reading.failure}`);

      const read = readKoboLibrary(reading.database);
      reading.database.close();

      expect(
        read.ok
          ? { books: read.library.books.length, skipped: read.library.skipped }
          : { failure: read.failure },
      ).toEqual(expected);
    },
  );

  it("says a file is not a Kobo device rather than saying it is empty", async () => {
    // Two different sentences to a member holding a file that did not work, and
    // the wrong one sends them looking for books on a device that is not one.
    const read = await device([`CREATE TABLE content (id INTEGER)`]);

    expect(read).toEqual({ ok: false, failure: "not-a-kobo-device" });
  });

  it("says a device is empty when it is a device with nothing on it", async () => {
    const read = await device(KOBO_SCHEMA);

    expect(read).toEqual({ ok: false, failure: "empty" });
  });

  it("keeps the count when a device holds only what it refuses", async () => {
    // Not the same thing as an empty device, and the member is owed the
    // difference: a Kobo carrying two hundred store recommendations has plenty
    // on it, none of which they own. Reporting that as empty throws the count
    // away, which is what an earlier draft did.
    const library = await libraryOn(
      `INSERT INTO content (ContentID, Title, Accessibility)
         VALUES ('recommendation', 'Buy This', 6)`,
    );

    expect(library).toMatchObject({ books: [], skipped: 1 });
  });
});

describe("the statement is built from this module's own column list", () => {
  it("reads a device carrying a column named like a statement", async () => {
    // **The guard this asserts is the allowlist, and the case has to reach
    // it.** A file whose payload column stops it being recognised as a Kobo at
    // all is refused before a statement is composed, so it says nothing about
    // how one is composed: this device has both signature columns and is read.
    //
    // The payload is spelled so that the injected prefix would parse: under a
    // reader selecting every column the device has, the composed SQL is a valid
    // SELECT followed by a DROP. Two things stop it, and this reaches the outer
    // one. `sqlite.ts`'s `PRAGMA query_only` is the other, which is why the
    // table is asserted to survive as well as the book to arrive.
    const bytes = await databaseOf(
      `CREATE TABLE content (
         ContentID TEXT,
         BookID TEXT,
         "ContentID FROM content; DROP TABLE secrets; --" TEXT
       )`,
      `CREATE TABLE secrets (id INTEGER PRIMARY KEY)`,
      `INSERT INTO content (ContentID, BookID) VALUES ('a-book', NULL)`,
    );
    const reading = await openSqlite(bytes, engine);
    if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);

    const read = readKoboLibrary(reading.database);
    const survived = reading.database.query(
      "SELECT name FROM sqlite_master WHERE name = 'secrets'",
    );
    reading.database.close();

    expect(read.ok && read.library.books.map((book) => book.contentId)).toEqual(
      ["a-book"],
    );
    expect(survived).toHaveLength(1);
  });
});
