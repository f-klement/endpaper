/**
 * Tests for src/lib/sqliteRow.ts.
 *
 * **These four were declared in `calibre.ts` and again in `kobo.ts`**, and this
 * file is one of the two things that stop a third reader making it three: the
 * arms below are the vocabulary's only home, and the last one refuses a copy in
 * any module that opens a member's database.
 *
 * The coercions are asked directly. Through a reader they are asked only of the
 * values that reader's own fixtures carry, so what a coercion refuses is
 * asserted by whichever library happened to have a row shaped like that, which
 * is a different question from what the rule is.
 *
 * Databases are real, built through `sqliteFixtures.databaseOf` and read back
 * through `openSqlite`: `columnsIn` composes a statement, and what a statement
 * does is a fact about the engine rather than about a stand in.
 */

import { describe, expect, it } from "vitest";

import { openSqlite, type SqliteDatabase } from "../../src/lib/sqlite";
import { columnsIn, decimal, integer, text } from "../../src/lib/sqliteRow";
import { databaseOf, engine } from "./sqliteFixtures";

/** A database over these statements, or a failure that names itself. */
async function opened(...statements: string[]) {
  const reading = await openSqlite(await databaseOf(...statements), engine);
  if (!reading.ok) throw new Error(`expected a database: ${reading.failure}`);
  return reading;
}

/**
 * Every module, read as text, for the import rule at the end of this file.
 *
 * `import.meta.glob` rather than `node:fs`, for the reason
 * `tests/houseRules.test.ts` gives at its own copy: a guard test is a poor
 * reason to add `@types/node` and widen the global types. Here rather than
 * beside that copy because the rule is about one module's vocabulary and this
 * is that module's test file.
 */
const SOURCES = import.meta.glob("../../src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("a cell read as a string", () => {
  it("is the value with its edges trimmed", () => {
    expect(text("  Dune  ")).toBe("Dune");
  });

  it("is nothing for a cell holding only spaces", () => {
    // A blank and an absent field are the same thing to every caller, and the
    // readers each treat `null` as "the file did not say".
    expect(text("   ")).toBeNull();
    expect(text("")).toBeNull();
  });

  it("is nothing for a cell that is not text at all", () => {
    // `SqliteRow` carries five things and only one of them is a string. A
    // number reaching a title field would be rendered to a member as one.
    expect(text(42)).toBeNull();
    expect(text(null)).toBeNull();
    expect(text(undefined)).toBeNull();
    expect(text(new Uint8Array([1, 2]))).toBeNull();
  });
});

describe("a cell read as a whole number", () => {
  it("is the number with any fraction cut off", () => {
    expect(integer(3.7)).toBe(3);
    expect(integer(-3.7)).toBe(-3);
  });

  it("is nothing for a number that is not one", () => {
    expect(integer(Number.NaN)).toBeNull();
    expect(integer(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("is nothing for a number written as text", () => {
    // **The exclusion the module states, pinned here so it is a decision.**
    // SQLite promises no storage class, so a column with text affinity hands
    // back `"188"` where another device hands back `188`. Reading both here
    // would put the guess in every caller's answer; the one reader that knows
    // its vendor writes both says so at its own site, which is
    // `kobo.ts::isTrue`.
    expect(integer("188")).toBeNull();
  });
});

describe("a cell read as a number that may have a fraction", () => {
  it("keeps the fraction, which is what it is for", () => {
    // A Kobo writes 2.5 for a novella between two novels, and Calibre's
    // `series_index` is a REAL. Truncating here loses the half.
    expect(decimal(2.5)).toBe(2.5);
  });

  it("is nothing for anything that is not a finite number", () => {
    expect(decimal(Number.NaN)).toBeNull();
    expect(decimal("2.5")).toBeNull();
    expect(decimal(null)).toBeNull();
  });
});

describe("a table name a PRAGMA is given", () => {
  it("never reaches the database when it is not a name", async () => {
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
      // **The one that turns on the anchors alone**, and it is why it is here:
      // every other string above fails on a character the class refuses, so a
      // guard that had lost `^` and `$` to the `m` flag would still refuse them
      // all. Measured by the security seat: that one character mutation passed
      // 102 of 102 across this file and both readers, and under it
      // `PRAGMA table_info(books\n); DROP TABLE books; --` is composed and run.
      "books\n); DROP TABLE books; --",
      "",
    ]) {
      expect(columnsIn(recorder, hostile).size).toBe(0);
    }
    expect(asked).toEqual([]);

    // And an ordinary name still is asked, so the refusal is not simply always.
    expect(columnsIn(recorder, "books").size).toBe(0);
    expect(asked).toEqual(["PRAGMA table_info(books)"]);
  });

  it("gives back nothing for a name the engine would have accepted", async () => {
    // **The second instrument, and the case has to be one the engine would
    // answer**, or the assertion is satisfied by the absence of the guard.
    // Measured: with the refusal deleted and a name of `content); DROP TABLE
    // content; --`, the statement throws, `sqlite.ts` answers `[]` for a
    // statement it could not run, and the empty set comes back either way.
    //
    // A quoted identifier separates them. SQLite accepts `PRAGMA
    // table_info("books")` and hands back the columns, so a reader without the
    // refusal answers with them and this one answers nothing.
    //
    // **All three quotings the engine accepts, and the third is what makes this
    // a test of the rule rather than of one character.** Measured by the
    // security seat against the real engine: rewritten as a blacklist,
    // `table === "" || /["';()\-\s]/.test(table)`, the guard passed 102 of 102
    // across this file and both readers, because `[books]` carries none of
    // those characters and `PRAGMA table_info([books])` answers the full column
    // list. A rule that says which names are allowed cannot be replaced by one
    // that lists a few that are not, and this is the arm that says so.
    const reading = await opened(
      `CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)`,
    );
    const answered = ['"books"', "[books]", "`books`"].map((quoted) =>
      columnsIn(reading.database, quoted),
    );
    // The engine really would have answered: the same table, unquoted, is read.
    const plain = columnsIn(reading.database, "books");
    reading.database.close();

    expect(answered).toEqual([new Set(), new Set(), new Set()]);
    expect([...plain]).toEqual(["id", "title"]);
  });

  it("reads the real columns of a real table", async () => {
    const reading = await opened(
      `CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)`,
    );
    const columns = [...columnsIn(reading.database, "books")];
    reading.database.close();

    expect(columns).toEqual(["id", "title"]);
  });

  it("gives back nothing for a table the file does not have", async () => {
    // A missing table is an answer rather than a throw: a reader asks what the
    // file carries and reports the field as absent.
    const reading = await opened(`CREATE TABLE books (id INTEGER PRIMARY KEY)`);
    const columns = columnsIn(reading.database, "content");
    reading.database.close();

    expect(columns).toEqual(new Set());
  });
});

describe("the one home of the untrusted row vocabulary", () => {
  /**
   * The population is derived, not listed.
   *
   * **A module that reads a member supplied database imports `./sqlite`**, and
   * that is the whole of what makes it one: a third reader for Apple Books or
   * Kindle for PC joins this rule by opening a database, with no edit here, and
   * a module that stops opening one leaves it the same way. A list of readers
   * is the shape that goes stale exactly when a reader is added, which is the
   * moment this rule is for.
   *
   * **What it does not see, because the ways to spell a declaration are an open
   * set.** A copy hidden as an object property, `const helpers = { text(value)
   * {…} }`, is not a `function`, `const`, `let` or `var` binding of that name
   * and passes: measured by the design seat, **102 of 102** across this file,
   * `calibre.test.ts` and `kobo.test.ts`. The same mutation with
   * `const text = helpers.text;` beside it is caught, which is why the
   * exclusion is the pure object property form and not "a copy on an object".
   * What the pattern is
   * written against is the copy somebody makes, which is the one they pasted
   * out of the other reader, and that is a plain declaration. A further arm per
   * spelling is the enumerating shape this tree keeps refusing, so the answer if
   * one ever arrives is to name it here rather than to widen the pattern.
   *
   * **The direction it is wrong in, stated so nobody loosens it away.** A
   * module opening a database and legitimately needing a local `text` of its
   * own is refused here, loudly, and the answer is to name the local one for
   * what it does rather than to narrow this. The reverse, a fifth copy of the
   * four sitting in a third reader, is silent and is what shipped twice.
   */
  it("is not copied by any other module that opens a database", () => {
    const modules = Object.entries(SOURCES).map(
      ([path, source]) => [path.replace("../../src/", ""), source] as const,
    );

    const home = modules.find(([path]) => path === "lib/sqliteRow.ts")![1];
    // Derived from the module's own exports, so a fifth helper added there is
    // covered without an edit here.
    const vocabulary = [...home.matchAll(/export function (\w+)/g)].map(
      ([, name]) => name!,
    );
    // An anchor and not a census: a pattern that stopped matching would leave
    // nothing to look for and this arm would pass over any number of copies.
    // **Named rather than equated**, because an equality here refuses a fifth
    // helper legitimately added to that module and reports it as a copy, which
    // is the opposite of what this comment used to claim.
    expect(vocabulary).toContain("text");
    expect(vocabulary).toContain("columnsIn");

    // The specifier is matched the way `tests/lib/fileReaders.test.ts` matches
    // the seam's: a path ending in the module's name, with or without an
    // extension, since `allowImportingTsExtensions` makes both spellings
    // typecheck. `./sqliteRow` does not match, because what follows `sqlite`
    // there is not a dotted extension.
    const isSqlite = (from: string) => /\/sqlite(\.\w+)?$/.test(from);
    const opensADatabase = modules
      .filter(([path]) => path !== "lib/sqliteRow.ts")
      .filter(([, source]) =>
        [...source.matchAll(/from "([^"]+)"/g)].some(([, from]) =>
          isSqlite(from!),
        ),
      );
    // And a second anchor, named rather than equated: a third reader joins this
    // population by opening a database and needs no edit here, where an
    // equality would fail on the reader it is meant to cover.
    const openers = opensADatabase.map(([path]) => path);
    expect(openers).toContain("lib/calibre.ts");
    expect(openers).toContain("lib/kobo.ts");

    const copies = opensADatabase.flatMap(([path, source]) =>
      vocabulary
        .filter((name) =>
          new RegExp(`\\b(?:function|const|let|var)\\s+${name}\\b`).test(
            source,
          ),
        )
        .map((name) => `${path} declares ${name}`),
    );

    expect(copies).toEqual([]);
  });
});
