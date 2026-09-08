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
  columnsIn,
  crossCheck,
  indexOpfFiles,
  libraryPathOf,
  plainText,
  readCalibreLibrary,
  type CalibreBook,
} from "../../src/lib/calibre";
import type { OpfRecord } from "../../src/lib/opf";
import { openSqlite, type SqliteDatabase } from "../../src/lib/sqlite";
import { CALIBRE_SCHEMA, databaseOf, engine } from "./sqliteFixtures";

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
    // range, so nothing downstream would have caught it.
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

describe("a table name that is not a table name", () => {
  /**
   * Asked of `columnsIn` directly, and that is why it is exported.
   *
   * Every caller inside the module passes a literal, so a test going through
   * `readCalibreLibrary` cannot construct a name the check refuses and is green
   * whether the check is there or not. The refusal is what stops the comment
   * being the whole argument the first time somebody passes a name out of
   * `tablesIn`, which is read from a member supplied file.
   */
  it("never reaches the database with a name that is not one", async () => {
    // **Asserted on the statement, not on the answer**, and the first version
    // of this was wrong for exactly that reason: it checked that a hostile name
    // yielded no columns, which a database with the check deleted also does,
    // because a syntax error comes back as an empty result. Deleting the guard
    // scored 0 of 1. What only the guard produces is the query never being
    // asked, so the database here records what it was asked.
    const asked: string[] = [];
    const recorder: SqliteDatabase = {
      query: (sql) => {
        asked.push(sql);
        return [];
      },
      close: () => {},
    };

    for (const hostile of [
      'books"; DROP TABLE books; --',
      "books) UNION SELECT 1 --",
      "sqlite_master; ATTACH DATABASE 'x' AS y",
      "books-2",
      "",
    ]) {
      expect(columnsIn(recorder, hostile).size).toBe(0);
    }
    expect(asked).toEqual([]);

    // And an ordinary name still is asked, so the refusal is not simply always.
    expect(columnsIn(recorder, "books").size).toBe(0);
    expect(asked).toEqual(["PRAGMA table_info(books)"]);
  });

  it("reads the real columns of a real table", async () => {
    const reading = await openSqlite(
      await databaseOf(
        `CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)`,
      ),
      engine,
    );
    if (!reading.ok) throw new Error(reading.failure);

    expect([...columnsIn(reading.database, "books")]).toEqual(["id", "title"]);
    reading.database.close();
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

const A_FILE: OpfRecord = {
  version: "2.0",
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
    // `readCalibreLibrary` refuses all three by name and `opf.ts` refuses none,
    // so a Calibre library's own `metadata.opf` hands them straight back.
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
    readonly file: Partial<OpfRecord>;
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
