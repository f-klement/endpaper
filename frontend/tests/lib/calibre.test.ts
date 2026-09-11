/**
 * The Calibre reader, against real Calibre shaped databases.
 *
 * Every library here is built by `sqliteFixtures.CALIBRE_SCHEMA` and read back
 * through `openSqlite`, so what is asserted is what a `metadata.db` does rather
 * than what a stand in was told to answer. The placeholder cases are the point:
 * Calibre fills a blank rather than leaving one, so the values that need
 * refusing are values a real library carries.
 */

import { describe, expect, it } from "vitest";

import {
  CALIBRE_PLACEHOLDER,
  crossCheck,
  indexOpfFiles,
  identifiersWithScheme,
  libraryPathOf,
  plainText,
  readCalibreLibrary,
  type CalibreBook,
} from "../../src/lib/calibre";
import type { FileMetadata } from "../../src/lib/fileReaders";
import { openSqlite } from "../../src/lib/sqlite";
import { CALIBRE_SCHEMA, databaseOf, engine } from "./sqliteFixtures";

// The Takeout reader's own volume id rule, for the sweep that holds the two
// to one shape. A `?raw` specifier is a different module id, so this is a
// string rather than a second evaluation of that reader, which needs jsdom.
import takeoutSource from "../../src/lib/takeout.ts?raw";

/** A library holding whatever these rows put in it. */
async function library(...rows: string[]) {
  const reading = await openSqlite(
    await databaseOf(...CALIBRE_SCHEMA, ...rows),
    engine,
  );
  if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);
  const read = readCalibreLibrary(reading.database);
  reading.database.close();
  return read;
}

/** The books, or a failure raised where the assertion can see it. */
async function booksIn(...rows: string[]) {
  const read = await library(...rows);
  if (!read.ok) throw new Error(`expected books: ${read.failure}`);
  return read.books;
}

const ONE_BOOK = [
  `INSERT INTO books (id, title, pubdate, series_index, path)
     VALUES (1, 'Dune', '1965-08-01 00:00:00+00:00', 1.0, 'Herbert, Frank/Dune (1)')`,
  `INSERT INTO authors (id, name) VALUES (1, 'Frank Herbert')`,
  `INSERT INTO books_authors_link (book, author) VALUES (1, 1)`,
];

describe("reading a library", () => {
  it("gives back a book with every field the tables carry", async () => {
    const [book] = await booksIn(
      ...ONE_BOOK,
      `INSERT INTO publishers (id, name) VALUES (1, 'Chilton Books')`,
      `INSERT INTO books_publishers_link (book, publisher) VALUES (1, 1)`,
      `INSERT INTO series (id, name) VALUES (1, 'Dune Chronicles')`,
      `INSERT INTO books_series_link (book, series) VALUES (1, 1)`,
      `INSERT INTO languages (id, lang_code) VALUES (1, 'eng')`,
      `INSERT INTO books_languages_link (book, lang_code) VALUES (1, 1)`,
      `INSERT INTO comments (book, text) VALUES (1, '<p>A desert planet.</p>')`,
      `INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn', '9780441013593')`,
      `INSERT INTO data (book, format, name) VALUES (1, 'EPUB', 'Dune')`,
    );

    expect(book).toEqual({
      id: 1,
      path: "Herbert, Frank/Dune (1)",
      title: "Dune",
      authors: ["Frank Herbert"],
      identifiers: [{ type: "isbn", value: "9780441013593" }],
      isbn: "9780441013593",
      publisher: "Chilton Books",
      year: 1965,
      language: "eng",
      description: "A desert planet.",
      seriesName: "Dune Chronicles",
      seriesIndex: 1,
      formats: ["EPUB"],
    });
  });

  it("keeps several authors separate and in link order", async () => {
    const [book] = await booksIn(
      `INSERT INTO books (id, title, path) VALUES (1, 'Good Omens', 'x')`,
      `INSERT INTO authors (id, name) VALUES (1, 'Terry Pratchett'), (2, 'Neil Gaiman')`,
      `INSERT INTO books_authors_link (id, book, author) VALUES (1, 1, 1), (2, 1, 2)`,
    );

    expect(book!.authors).toEqual(["Terry Pratchett", "Neil Gaiman"]);
  });

  it("carries every identifier, not only the ISBN", async () => {
    const [book] = await booksIn(
      ...ONE_BOOK,
      `INSERT INTO identifiers (book, type, val)
         VALUES (1, 'amazon', 'B000R34YKC'), (1, 'goodreads', '234225')`,
    );

    expect(book!.identifiers).toEqual([
      { type: "amazon", value: "B000R34YKC" },
      { type: "goodreads", value: "234225" },
    ]);
    expect(book!.isbn).toBeNull();
  });

  it("finds an ISBN a household filed under another type", async () => {
    // The `isbn` row is what Calibre writes, and it is not what every library
    // has: a household that typed it into a plugin's own field still typed an
    // ISBN, and `parseIsbn` is what decides whether the value is one.
    const [book] = await booksIn(
      ...ONE_BOOK,
      `INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn10', '0441013597')`,
    );

    expect(book!.isbn).toBe("9780441013593");
  });

  it("refuses an identifier labelled ISBN that fails its own check digit", async () => {
    const [book] = await booksIn(
      ...ONE_BOOK,
      `INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn', '9780441013599')`,
    );

    expect(book!.isbn).toBeNull();
  });

  it("prefers the row typed isbn over one that merely parses", async () => {
    const [book] = await booksIn(
      ...ONE_BOOK,
      `INSERT INTO identifiers (id, book, type, val)
         VALUES (1, 1, 'other', '9780140328721'), (2, 1, 'isbn', '9780441013593')`,
    );

    expect(book!.isbn).toBe("9780441013593");
  });
});

describe("what Calibre writes where nobody said", () => {
  it("does not file a library under the year 101", async () => {
    // `UNDEFINED_DATE` is `0101-01-01`, and 101 is inside the year column's
    // range, so nothing downstream would have caught it. Refused here by the
    // window rather than by the name it used to be refused by; the arm stays
    // because it is the value that bought the window and the one this library
    // actually carries, 29 rows of 897 measured 2026-09-10.
    const [book] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '0101-01-01 00:00:00+00:00', 'x')`,
    );

    expect(book!.year).toBeNull();
  });

  it("reads a real pubdate as its year", async () => {
    const [book] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '1965-08-01 00:00:00+00:00', 'x')`,
    );

    expect(book!.year).toBe(1965);
  });

  it("does not read a pubdate no book could have been published in", async () => {
    // The window is `year.plausibleYear`'s, and this is the arm that says
    // which values it refuses here. The caller scan in
    // `tests/lib/bookBounds.test.ts` asserts that this module names the
    // function and that it calls it, and it does both by matching text: it
    // reads neither end of the window, so it cannot tell this door applying it
    // from this door widening it. Its call arm matches `plausibleYear(`, which
    // is a spelling a docstring can carry; no module under `src/lib/` carries
    // it in prose today, so a dropped call is red there as things stand.
    //
    // `1200-01-01` is the ticket's value and the refusal this door did not
    // make: the name it refused by covered 101 and nothing else, so a row a
    // second early enough arrived as a fact.
    const [medieval] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '1200-01-01 00:00:00+00:00', 'x')`,
    );

    expect(medieval!.year).toBeNull();

    // **The point immediately outside each end, and that choice is the arm.**
    // A number far outside catches a reader that drops the window and nothing
    // else; a reader keeping a second, wider window of its own answers from
    // that one for a contiguous band, and any contiguous widening of an end has
    // to contain the point just outside it. Same reasoning as `cbz.test.ts`,
    // and the values are that file's, not this seat's.
    const [tooEarly] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '1449-12-31 00:00:00+00:00', 'x')`,
    );
    const [tooLate] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '2101-01-01 00:00:00+00:00', 'x')`,
    );

    expect(tooEarly!.year).toBeNull();
    expect(tooLate!.year).toBeNull();
  });

  it("reads a pubdate on either edge of the window as its year", async () => {
    // The inside of each end, because every arm above expects `null`: a reader
    // that answers `null` for every year passes all of them. This is the side
    // of the boundary they do not reach, and it is what refuses a window
    // narrowed by one at either end.
    const [earliest] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '1450-01-01 00:00:00+00:00', 'x')`,
    );
    const [latest] = await booksIn(
      `INSERT INTO books (id, title, pubdate, path)
         VALUES (1, 'Dune', '2100-12-31 00:00:00+00:00', 'x')`,
    );

    expect(earliest!.year).toBe(1450);
    expect(latest!.year).toBe(2100);
  });

  it("treats the placeholder title as no title", async () => {
    const [book] = await booksIn(
      `INSERT INTO books (id, title, path) VALUES (1, 'Unknown', 'x')`,
    );

    expect(book!.title).toBeNull();
  });

  it("treats the placeholder author as no author", async () => {
    const [book] = await booksIn(
      `INSERT INTO books (id, title, path) VALUES (1, 'Dune', 'x')`,
      `INSERT INTO authors (id, name) VALUES (1, 'Unknown')`,
      `INSERT INTO books_authors_link (book, author) VALUES (1, 1)`,
    );

    expect(book!.authors).toEqual([]);
  });

  it("does not file a standalone book as the first of a series", async () => {
    // `series_index` is `1.0` on every row Calibre writes, series or not.
    const [book] = await booksIn(
      `INSERT INTO books (id, title, series_index, path) VALUES (1, 'Dune', 1.0, 'x')`,
    );

    expect(book!.seriesName).toBeNull();
    expect(book!.seriesIndex).toBeNull();
  });

  it("keeps the index where there really is a series", async () => {
    const [book] = await booksIn(
      `INSERT INTO books (id, title, series_index, path) VALUES (1, 'Messiah', 2.0, 'x')`,
      `INSERT INTO series (id, name) VALUES (1, 'Dune Chronicles')`,
      `INSERT INTO books_series_link (book, series) VALUES (1, 1)`,
    );

    expect(book!.seriesIndex).toBe(2);
  });
});

describe("a database that is not a Calibre library", () => {
  it("is refused rather than read as one with nothing in it", async () => {
    // This app's own database has a `books` table. Recognising on that name
    // alone would answer "a Calibre library with nine hundred empty records".
    const reading = await openSqlite(
      await databaseOf(
        "CREATE TABLE books (id INTEGER, title TEXT)",
        "INSERT INTO books VALUES (1, 'Dune')",
      ),
      engine,
    );
    if (!reading.ok) throw new Error(reading.failure);

    expect(readCalibreLibrary(reading.database)).toEqual({
      ok: false,
      failure: "not-a-calibre-library",
    });
    reading.database.close();
  });

  it("says a Calibre library with no books is empty", async () => {
    expect(await library()).toEqual({ ok: false, failure: "empty" });
  });
});

describe("a Calibre that moved its own schema", () => {
  it("loses the fields the missing tables carried and keeps the books", async () => {
    // The ticket says in as many words that the layout is stable and the
    // schema is not guaranteed. A reader that needs every table is a reader
    // that returns nothing after the next Calibre release.
    const reading = await openSqlite(
      await databaseOf(
        `CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, path TEXT)`,
        `CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER)`,
        `INSERT INTO books VALUES (1, 'Dune', 'x')`,
      ),
      engine,
    );
    if (!reading.ok) throw new Error(reading.failure);
    const read = readCalibreLibrary(reading.database);
    reading.database.close();

    expect(read).toEqual({
      ok: true,
      books: [
        {
          id: 1,
          path: "x",
          title: "Dune",
          authors: [],
          identifiers: [],
          isbn: null,
          publisher: null,
          year: null,
          language: null,
          description: null,
          seriesName: null,
          seriesIndex: null,
          formats: [],
        },
      ],
    });
  });
});

describe("a comment is HTML and a description is not", () => {
  it("gives back the text, with the paragraphs still apart", () => {
    expect(plainText("<p>One.</p><p>Two.</p>")).toBe("One.\n\nTwo.");
  });

  it("does not run two lines together", () => {
    expect(plainText("First<br/>Second")).toBe("First\nSecond");
  });

  it("keeps nothing executable and nothing an element carried", () => {
    // The parse is inert: `DOMParser` with `text/html` runs no script and
    // fetches nothing, so this is a value question rather than a hope.
    expect(plainText('<img src="x" onerror="alert(1)">Fine')).toBe("Fine");
    expect(plainText("<script>alert(1)</script>Fine")).toBe("Fine");
  });

  it("is null for a comment that was only markup", () => {
    expect(plainText("<p>  </p>")).toBeNull();
  });
});

describe("finding the file beside a book", () => {
  function picked(path: string): File {
    const file = new File(["<package/>"], path.split("/").pop() ?? "");
    Object.defineProperty(file, "webkitRelativePath", { value: path });
    return file;
  }

  it("drops the folder the member pointed at", () => {
    expect(libraryPathOf(picked("Calibre/Herbert/Dune (1)/metadata.opf"))).toBe(
      "Herbert/Dune (1)/metadata.opf",
    );
  });

  it("is null for a file that came from an ordinary picker", () => {
    expect(libraryPathOf(new File([""], "metadata.opf"))).toBeNull();
  });

  it("keys each package document by the directory books.path names", () => {
    const index = indexOpfFiles([
      picked("Calibre/Herbert/Dune (1)/metadata.opf"),
      picked("Calibre/Herbert/Dune (1)/cover.jpg"),
      picked("Calibre/metadata.db"),
    ]);

    expect([...index.keys()]).toEqual(["Herbert/Dune (1)"]);
  });

  it("compares one accented directory name one way", () => {
    // The database composes and a filesystem may decompose, so the same
    // author's directory is two strings that name one place. Without the
    // normalisation the cross check is silently lost for every one of them.
    const decomposed = "José/Book (1)/metadata.opf";
    const index = indexOpfFiles([picked(`Calibre/${decomposed}`)]);

    expect(index.has("José/Book (1)")).toBe(true);
  });
});

/**
 * One book as the index gives it, and the file Calibre wrote beside that book.
 *
 * At module scope because two describes drive them: the cross check's own
 * cases, and the placeholder set below, which has to reach both of a library's
 * doors from one list.
 */
const A_BOOK: CalibreBook = {
  id: 1,
  path: "x",
  title: "Dune",
  authors: ["Frank Herbert"],
  identifiers: [],
  isbn: null,
  publisher: null,
  year: null,
  language: null,
  description: null,
  seriesName: null,
  seriesIndex: null,
  formats: ["EPUB"],
};

const A_FILE: FileMetadata = {
  title: "Dune",
  subtitle: null,
  authors: ["Frank Herbert"],
  identifiers: [],
  isbn: null,
  publisher: null,
  year: null,
  language: null,
  description: null,
  seriesName: null,
  seriesIndex: null,
};

describe("checking a book against the file beside it", () => {
  it("fills a field the database left empty", () => {
    const checked = crossCheck(A_BOOK, {
      ...A_FILE,
      publisher: "Chilton Books",
    });

    expect(checked.book.publisher).toBe("Chilton Books");
    expect(checked.filled).toBe(1);
    expect(checked.disagreed).toBe(0);
  });

  it("keeps the database's value where the two disagree, and counts it", () => {
    const checked = crossCheck(
      { ...A_BOOK, publisher: "Chilton Books" },
      { ...A_FILE, publisher: "Ace" },
    );

    expect(checked.book.publisher).toBe("Chilton Books");
    expect(checked.filled).toBe(0);
    expect(checked.disagreed).toBe(1);
  });

  it("takes the file's ISBN when the database has none", () => {
    const checked = crossCheck(A_BOOK, { ...A_FILE, isbn: "9780441013593" });

    expect(checked.book.isbn).toBe("9780441013593");
    expect(checked.filled).toBe(1);
  });

  it("keeps the database's ISBN when both carry a real one", () => {
    const checked = crossCheck(
      { ...A_BOOK, isbn: "9780441013593" },
      { ...A_FILE, isbn: "9780140328721" },
    );

    expect(checked.book.isbn).toBe("9780441013593");
    expect(checked.disagreed).toBe(1);
  });

  it("never pairs one source's index with the other's series", () => {
    // A position counts in a series. Taking the number from a file that names a
    // different series invents a volume neither source claims.
    //
    // **The database's own index is null here, and that is the whole test.**
    // With a number on both sides `??` answers before the guard runs, so the
    // fixture that gave the database a `seriesIndex` of 1 passed whether the
    // series were compared or not: dropping the comparison entirely was green.
    const checked = crossCheck(
      { ...A_BOOK, seriesName: "Dune Chronicles", seriesIndex: null },
      { ...A_FILE, seriesName: "Something Else", seriesIndex: 7 },
    );

    expect(checked.book.seriesName).toBe("Dune Chronicles");
    expect(checked.book.seriesIndex).toBeNull();
    expect(checked.disagreed).toBe(1);
  });

  it("takes the index from the file when the two name one series", () => {
    const checked = crossCheck(
      { ...A_BOOK, seriesName: "Dune Chronicles", seriesIndex: null },
      { ...A_FILE, seriesName: "Dune Chronicles", seriesIndex: 2 },
    );

    expect(checked.book.seriesIndex).toBe(2);
    expect(checked.filled).toBe(1);
  });

  it("takes both when the database names no series at all", () => {
    const checked = crossCheck(A_BOOK, {
      ...A_FILE,
      seriesName: "Dune Chronicles",
      seriesIndex: 2,
    });

    expect(checked.book.seriesName).toBe("Dune Chronicles");
    expect(checked.book.seriesIndex).toBe(2);
    // Two fields, not one. The count is what the screen shows before the
    // write, so a branch that counts a name and an index as one understates
    // exactly the number the cross check exists to report.
    expect(checked.filled).toBe(2);
  });

  it("counts one when the file names a series and no position in it", () => {
    const checked = crossCheck(A_BOOK, {
      ...A_FILE,
      seriesName: "Dune Chronicles",
      seriesIndex: null,
    });

    expect(checked.filled).toBe(1);
  });

  it("fills the authors and does not compare them", () => {
    // Two spellings of one person are the common case, and counting them would
    // bury the disagreement count under a difference nobody would act on.
    const filled = crossCheck({ ...A_BOOK, authors: [] }, A_FILE);
    expect(filled.book.authors).toEqual(["Frank Herbert"]);
    expect(filled.filled).toBe(1);

    const spelled = crossCheck(A_BOOK, {
      ...A_FILE,
      authors: ["Herbert, Frank"],
    });
    expect(spelled.book.authors).toEqual(["Frank Herbert"]);
    expect(spelled.disagreed).toBe(0);
  });

  it("reads the file's description as text, not as the markup it is", () => {
    // A Calibre `metadata.opf` writes `dc:description` as escaped HTML, so the
    // gap fill reaches the same markup the database path drops. Filling it raw
    // put `<script>` source into a stored book description by the other door.
    const checked = crossCheck(A_BOOK, {
      ...A_FILE,
      description: "<p>One.</p><script>alert(1)</script>",
    });

    expect(checked.book.description).toBe("One.");
  });

  it("rescues a book whose title Calibre never had", () => {
    const checked = crossCheck({ ...A_BOOK, title: null }, A_FILE);

    expect(checked.book.title).toBe("Dune");
    expect(checked.filled).toBe(1);
  });

  describe("the placeholders, arriving by the file's door instead", () => {
    // `readCalibreLibrary` refuses the two string placeholders by name and the
    // year one inside the same window. `opf.ts` refuses the year one by that
    // window and hands the other two straight back, so
    // a Calibre library's own `metadata.opf` still reaches this door with them.
    // These arms drive `crossCheck` directly, which is what keeps the year arm
    // covered now that `opf.readYear` cannot produce 101 in production.
    // Measured over the household's 897 book library on 2026-09-08: 57 books
    // took the year 101 and 31 took `Unknown` as their author.

    it("refuses the file's undefined year rather than filling a gap with it", () => {
      const checked = crossCheck(A_BOOK, { ...A_FILE, year: 101 });

      expect(checked.book.year).toBeNull();
      expect(checked.filled).toBe(0);
    });

    it("does not count the file's undefined year as a disagreement", () => {
      const checked = crossCheck(
        { ...A_BOOK, year: 1965 },
        { ...A_FILE, year: 101 },
      );

      expect(checked.book.year).toBe(1965);
      expect(checked.disagreed).toBe(0);
    });

    it("keeps an ordinary year the file supplies", () => {
      // The arm had no case at all in which the file's year survived, so a
      // mutant narrowing the refusal to `>= 101` discarded every real year the
      // file carries and passed. This is the side of the boundary the case
      // below does not reach.
      const checked = crossCheck(A_BOOK, { ...A_FILE, year: 1965 });

      expect(checked.book.year).toBe(1965);
      expect(checked.filled).toBe(1);
    });

    it("keeps a real year the file supplies one below the placeholder", () => {
      // The exact value, never a floor: widening `=== 101` to `<= 101` passed
      // 43 of 43, because both string arms of this sieve had a boundary case
      // and the numeric arm had none. A member's genuine pre-102 year is what
      // that mutant discarded.
      const checked = crossCheck(A_BOOK, { ...A_FILE, year: 100 });

      expect(checked.book.year).toBe(100);
      expect(checked.filled).toBe(1);
    });

    it("refuses the file's Unknown author rather than filling a gap with it", () => {
      const checked = crossCheck(
        { ...A_BOOK, authors: [] },
        { ...A_FILE, authors: ["Unknown"] },
      );

      expect(checked.book.authors).toEqual([]);
      expect(checked.filled).toBe(0);
    });

    it("keeps a real author the file names beside the placeholder", () => {
      // The refusal is per name. Dropping the whole list would lose a person a
      // library filed second behind a blank.
      const checked = crossCheck(
        { ...A_BOOK, authors: [] },
        { ...A_FILE, authors: ["Unknown", "Frank Herbert"] },
      );

      expect(checked.book.authors).toEqual(["Frank Herbert"]);
      expect(checked.filled).toBe(1);
    });

    it("refuses the placeholder wherever the file lists it", () => {
      // Position independent, like the index door, which reaches every name
      // through one predicate. This arm is where the two doors had already
      // drifted: every other fixture puts `Unknown` first or nowhere, so a
      // refusal that skipped every name after the first was green.
      const checked = crossCheck(
        { ...A_BOOK, authors: [] },
        { ...A_FILE, authors: ["Frank Herbert", "Unknown"] },
      );

      expect(checked.book.authors).toEqual(["Frank Herbert"]);
      expect(checked.filled).toBe(1);
    });

    it("keeps a real author whose name merely contains the placeholder", () => {
      // The whole name, never a substring. Written because the mutation that
      // loosened this to `includes` was the one evasion of six that the round
      // before this did not catch: the case it had was `Unknown` beside a
      // second name, which a substring match survives.
      const checked = crossCheck(
        { ...A_BOOK, authors: [] },
        { ...A_FILE, authors: ["The Unknown Soldier"] },
      );

      expect(checked.book.authors).toEqual(["The Unknown Soldier"]);
      expect(checked.filled).toBe(1);
    });

    it("refuses the file's Unknown title rather than filling a gap with it", () => {
      const checked = crossCheck(
        { ...A_BOOK, title: null },
        { ...A_FILE, title: "Unknown" },
      );

      expect(checked.book.title).toBeNull();
      expect(checked.filled).toBe(0);
    });

    it("keeps a real title that merely begins with the placeholder", () => {
      // The whole value, never a substring: `Unknown` is what Calibre writes
      // instead of a title, and a book called `Unknown Pleasures` is a title.
      const checked = crossCheck(
        { ...A_BOOK, title: null },
        { ...A_FILE, title: "Unknown Pleasures" },
      );

      expect(checked.book.title).toBe("Unknown Pleasures");
      expect(checked.filled).toBe(1);
    });
  });
});

describe("the placeholder set, refused at both of a library's doors", () => {
  /**
   * The set, named once, and the only place these tests say what one is.
   *
   * A library is read through two doors: `readCalibreLibrary` meets a
   * placeholder in a row of `metadata.db`, and `crossCheck` meets it again in
   * the `metadata.opf` Calibre wrote from that row. Each entry below carries
   * the set's own key and says how a row carries the value and how a file
   * carries it, so **a fourth predicate is one entry here and a failing test
   * at whichever door forgets it**, rather than two edits with nothing red
   * after the first.
   *
   * **The keys are checked against the set twice, and that is what makes this
   * a derivation rather than a list beside one.** `PlaceholderCase.key` is
   * typed as one of the set's, so removing a member fails the typecheck here,
   * and the assertion after the loop fails when a member is added with none.
   * Written first as a hand maintained parallel literal, which moved the very
   * defect the set was introduced to remove up into this file: a fourth
   * predicate wired at one door left all 52 tests green, because nothing red
   * follows from a list that is merely short.
   *
   * That is not hypothetical either: the two doors had already drifted on the
   * author arm, where the file door's refusal could be made to skip every name
   * after the first and stay green.
   *
   * `series_index` is deliberately absent. Both doors refuse it structurally,
   * by reading a position only where a series is named, so there is no value
   * to hand a predicate and nothing here could drive it.
   *
   * **The year case is a door short**: its index door arm passes on the window
   * `readYear` applies rather than on the set's member, so the coupling this
   * block claims holds for `title` and `author` only. `CALIBRE_PLACEHOLDER`'s
   * docstring is the home of that exception. The arm stays because it asserts
   * what the door does, and the file door arm below is the member's coverage.
   */
  /** One placeholder, and the two doors it has to be refused at. */
  interface PlaceholderCase {
    /**
     * The set's own key.
     *
     * Typed as one of them rather than as a string, so removing a member from
     * `CALIBRE_PLACEHOLDER` fails the typecheck here rather than quietly
     * shrinking what the assertion below compares.
     */
    readonly key: keyof typeof CALIBRE_PLACEHOLDER;
    /** How the two test names below read. */
    readonly what: string;
    /** Rows that put the placeholder in an index. */
    readonly rows: readonly string[];
    /** The one field this case empties on the index's side. */
    readonly book: Partial<CalibreBook>;
    /** The placeholder, as the file beside the book carries it. */
    readonly file: Partial<FileMetadata>;
    /** The field under test, read off whichever door answered. */
    readonly read: (book: CalibreBook) => unknown;
    /** What that field reads as once the placeholder is refused. */
    readonly empty: unknown;
  }

  const placeholders: readonly PlaceholderCase[] = [
    {
      key: "year",
      what: "the undefined year",
      rows: [
        `INSERT INTO books (id, title, pubdate, path)
           VALUES (1, 'Dune', '0101-01-01 00:00:00+00:00', 'x')`,
      ],
      book: { year: null },
      file: { year: 101 },
      read: (book: CalibreBook) => book.year,
      empty: null,
    },
    {
      key: "title",
      what: "the placeholder title",
      rows: [`INSERT INTO books (id, title, path) VALUES (1, 'Unknown', 'x')`],
      book: { title: null },
      file: { title: "Unknown" },
      read: (book: CalibreBook) => book.title,
      empty: null,
    },
    {
      key: "author",
      what: "the placeholder author",
      rows: [
        `INSERT INTO books (id, title, path) VALUES (1, 'Dune', 'x')`,
        `INSERT INTO authors (id, name) VALUES (1, 'Unknown')`,
        `INSERT INTO books_authors_link (book, author) VALUES (1, 1)`,
      ],
      book: { authors: [] },
      file: { authors: ["Unknown"] },
      read: (book: CalibreBook) => book.authors,
      empty: [],
    },
  ];

  for (const placeholder of placeholders) {
    it(`refuses ${placeholder.what} in a row of the index`, async () => {
      const [book] = await booksIn(...placeholder.rows);

      expect(placeholder.read(book!)).toEqual(placeholder.empty);
    });

    it(`refuses ${placeholder.what} in the file beside the book`, () => {
      // One field emptied, so the rest of the two fixtures still agree and
      // the counts below are about this field and nothing else.
      const checked = crossCheck(
        { ...A_BOOK, ...placeholder.book },
        { ...A_FILE, ...placeholder.file },
      );

      expect(placeholder.read(checked.book)).toEqual(placeholder.empty);
      expect(checked.filled).toBe(0);
      expect(checked.disagreed).toBe(0);
    });
  }

  it("covers every predicate the set holds, and no other", () => {
    // Sorted, because the order of the set's own keys is incidental and a
    // reordering is not a hole. What this fails on is a member with no entry,
    // which is a predicate no door above is driven to apply.
    expect(placeholders.map((placeholder) => placeholder.key).sort()).toEqual(
      Object.keys(CALIBRE_PLACEHOLDER).sort(),
    );
  });
});

/**
 * The mapping from a Calibre type string to a scheme this app stores.
 *
 * Read out of a real `metadata.db` like everything else here, because the type
 * column is somebody else's data and a fixture that handed the function an
 * array would not be reading a library at all.
 */
describe("which of a library's identifiers reach the endpoint", () => {
  /** What one book's `identifiers` rows become, as a request would take them. */
  async function schemed(...rows: string[]) {
    const [book] = await booksIn(...ONE_BOOK, ...rows);
    return identifiersWithScheme(book!.identifiers);
  }

  /** One `identifiers` row. */
  function row(type: string, value: string) {
    return `INSERT INTO identifiers (book, type, val) VALUES (1, '${type}', '${value}')`;
  }

  it("keeps the two schemes this app has and passes the rest over", async () => {
    expect(
      await schemed(
        row("isbn", "9780441013593"),
        row("amazon", "B000R34YKC"),
        row("google", "s7NIrgEACAAJ"),
        row("goodreads", "234225"),
      ),
    ).toEqual([
      { scheme: "asin", value: "B000R34YKC" },
      { scheme: "google_books", value: "s7NIrgEACAAJ" },
    ]);
  });

  // Calibre's `AMAZON_DOMAINS`, read off calibre master on 2026-09-11, with the
  // `com` entry spelled both ways that plugin can produce: `amazon` is what it
  // writes for that store and `amazon_com` is what `get_domain_and_asin` reads.
  // Enumerated **here** and nowhere in the source: the rule under test is a
  // shape, and this is the corpus that says the shape covers what exists.
  const MARKETPLACES = [
    "amazon",
    "amazon_com",
    "amazon_fr",
    "amazon_de",
    "amazon_uk",
    "amazon_au",
    "amazon_it",
    "amazon_jp",
    "amazon_es",
    "amazon_br",
    "amazon_in",
    "amazon_nl",
    "amazon_cn",
    "amazon_ca",
    "amazon_se",
  ];

  for (const type of MARKETPLACES) {
    it(`reads ${type} as an ASIN`, async () => {
      expect(await schemed(row(type, "B000R34YKC"))).toEqual([
        { scheme: "asin", value: "B000R34YKC" },
      ]);
    });
  }

  it("reads the bare `asin` spelling Calibre's own reader accepts", async () => {
    // The second name in the Amazon family, and the arm that makes it load
    // bearing: `get_domain_and_asin` reads `key in ('amazon', 'asin')` as the
    // US marketplace, so a library that filed one under it filed an ASIN.
    expect(await schemed(row("asin", "B000R34YKC"))).toEqual([
      { scheme: "asin", value: "B000R34YKC" },
    ]);
  });

  it("reads a marketplace Calibre's own list has never carried", async () => {
    // The point of the suffix being a shape. Amazon opened .pl after the list
    // above was written, and a reader built from that list files it as nothing.
    expect(await schemed(row("amazon_pl", "B000R34YKC"))).toEqual([
      { scheme: "asin", value: "B000R34YKC" },
    ]);
  });

  it("declines an amazon type whose suffix is not a marketplace", async () => {
    // **One underscore and a word after it**, which is the arm that separates a
    // suffix shaped like a marketplace from any suffix at all: widening the
    // rule to `_[a-z]+$` files both of these under `asin`, and the second alone
    // would not notice, its root being `amazon_kindle` either way.
    expect(await schemed(row("amazon_author", "B000R34YKC"))).toEqual([]);
    expect(await schemed(row("amazon_kindle_notes", "B000R34YKC"))).toEqual([]);
    // Four letters, which pins the other end of the bound: every arm above
    // refuses five letters and more, so `{2,4}` passes without this one.
    expect(await schemed(row("amazon_kids", "B000R34YKC"))).toEqual([]);
  });

  it("declines `asin` in a name that is not the Amazon family", async () => {
    // `mobi-asin` is the tempting one and it is the type that names a place
    // rather than a scheme: calibre's MOBI reader sets it from EXTH 113, whose
    // own comment there reads `ASIN or other id`, and calibre refuses it by
    // default. The value here is the uuid calibre mints into that record when a
    // file has no ASIN; the second arm is a value the shape rule would accept,
    // so what refuses this row is the type and the arm says so.
    expect(
      await schemed(row("mobi-asin", "0e8c1b52-8a4f-4f65-8a6b-7c4b1e0d2f11")),
    ).toEqual([]);
    expect(await schemed(row("mobi-asin", "B000R34YKC"))).toEqual([]);
  });

  for (const type of ["goodreads", "doi", "issn", "oclc", "arxiv", "uri"]) {
    it(`declines ${type}, which no reader here produces`, async () => {
      // A value shaped like the scheme it would have been filed under, so what
      // refuses the row is the type rather than the value.
      expect(await schemed(row(type, "B000R34YKC"))).toEqual([]);
    });
  }

  it("declines a value the scheme's own readers would not produce", async () => {
    // The direction the suffix being open could be wrong in: a plugin free to
    // invent `amazon_zz` is not free to make a store page reference an ASIN.
    expect(
      await schemed(
        row("amazon_de", "https://www.amazon.de/dp/B000R34YKC"),
        row("amazon_zz", "9780441013593"),
        row("google", "s7NIrgEACAAJXX"),
      ),
    ).toEqual([]);
  });

  it("keeps a printed edition's ASIN, which is its ISBN-10", async () => {
    // Amazon issues one, so an ASIN alphabet narrowed to a `B` prefix would
    // drop a real row. Calibre's own regression fixture carries this value
    // under `amazon_ca`.
    expect(await schemed(row("amazon_ca", "162380874X"))).toEqual([
      { scheme: "asin", value: "162380874X" },
    ]);
  });

  it("takes a type as Calibre's own readers take one", async () => {
    // Both `get_domain_and_asin` and `urls_from_identifiers` start by lower
    // casing the keys, because the column holds whatever was typed into it.
    expect(await schemed(row("  AMAZON_DE  ", "B000R34YKC"))).toEqual([
      { scheme: "asin", value: "B000R34YKC" },
    ]);
  });

  it("keeps a row a library padded, which arrives trimmed", async () => {
    // **Named for the composition and not for this function**, which does no
    // trimming: `sqliteRow.text` does it before the row is built. The arm is
    // still worth its line, because the shape rule is length exact, so a reader
    // that stopped trimming would drop the row rather than widen anything.
    expect(await schemed(row("amazon", "  B000R34YKC  "))).toEqual([
      { scheme: "asin", value: "B000R34YKC" },
    ]);
  });

  it("carries a repeat and either case through, folding neither", async () => {
    // **The seam, asserted rather than assumed.** A scheme's canonical form and
    // the fold of a repeat are `LibrarySettingsPage/types`', because both are
    // properties of the scheme and both readers go through that door; this one
    // answers one entry a matching row. The arms that pin the fold itself are
    // in that module's mirrored test.
    expect(
      await schemed(
        row("amazon", "b000r34ykc"),
        row("amazon_de", "B000R34YKC"),
      ),
    ).toEqual([
      { scheme: "asin", value: "b000r34ykc" },
      { scheme: "asin", value: "B000R34YKC" },
    ]);
  });

  it("holds the volume id to the shape the Takeout reader holds it to", async () => {
    // **Swept against that module's own rule, not against examples.** The two
    // readers produce one scheme's values and a difference between them is a
    // row one would send and the other would not. Read out of the source
    // because the constant is private to it, which is `kindle.test.ts`'s
    // arrangement for the same problem.
    const declared = /const VOLUME_ID = (\/\S+\/);/.exec(takeoutSource);
    expect(declared).not.toBeNull();
    const volumeId = new RegExp(declared![1]!.slice(1, -1));

    const candidates = [
      "aB3-dE6_gH9j",
      "s7NIrgEACAAJ",
      "aB3-dE6_gH9",
      "aB3-dE6_gH9jk",
      "aB3-dE6_gH9.",
      "aB3-dE6_gH9+",
      "____________",
      "------------",
      "000000000000",
    ];
    const agreed = await Promise.all(
      candidates.map(async (candidate) => ({
        candidate,
        kept: (await schemed(row("google", candidate))).length === 1,
        produced: volumeId.test(candidate),
      })),
    );

    expect(agreed.filter((one) => one.kept !== one.produced)).toEqual([]);
    // Both answers appear, so an equality that held because nothing passed is
    // not what was measured.
    expect(new Set(agreed.map((one) => one.kept))).toEqual(
      new Set([true, false]),
    );
  });
});
