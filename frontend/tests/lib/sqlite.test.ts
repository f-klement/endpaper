/**
 * The SQLite seam, against real databases.
 *
 * Every case here builds a database with the shipped engine and hands the bytes
 * back through the public door, so what is asserted is what a member's file
 * would do rather than what a stand in was told to answer.
 */

import { describe, expect, it } from "vitest";

import {
  MAX_CELL_BYTES,
  MAX_DATABASE_BYTES,
  MAX_ROWS_PER_QUERY,
  openSqlite,
  openSqliteFile,
} from "../../src/lib/sqlite";
import { databaseOf, engine } from "./sqliteFixtures";

/** One file of this repository, as text. */
function raw(path: "../../package.json" | "../../src/lib/sqlite.ts"): string {
  const files = {
    "../../package.json": import.meta.glob("../../package.json", {
      query: "?raw",
      import: "default",
      eager: true,
    }),
    "../../src/lib/sqlite.ts": import.meta.glob("../../src/lib/sqlite.ts", {
      query: "?raw",
      import: "default",
      eager: true,
    }),
  };
  return Object.values(files[path])[0] as string;
}

async function open(bytes: Uint8Array) {
  const reading = await openSqlite(bytes, engine);
  if (!reading.ok)
    throw new Error(`expected a database, got ${reading.failure}`);
  return reading.database;
}

describe("opening a database", () => {
  it("reads a table back by column name", async () => {
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (id INTEGER, title TEXT)",
        "INSERT INTO shelf VALUES (1, 'Dune'), (2, 'Solaris')",
      ),
    );

    expect(database.query("SELECT id, title FROM shelf ORDER BY id")).toEqual([
      { id: 1, title: "Dune" },
      { id: 2, title: "Solaris" },
    ]);
    database.close();
  });

  it("binds a parameter rather than pasting it in", async () => {
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (title TEXT)",
        "INSERT INTO shelf VALUES ('Dune'), (''' OR 1=1 --')",
      ),
    );

    expect(
      database.query("SELECT title FROM shelf WHERE title = ?", [
        "' OR 1=1 --",
      ]),
    ).toEqual([{ title: "' OR 1=1 --" }]);
    database.close();
  });

  it("refuses a file that is not a database", async () => {
    const reading = await openSqlite(
      new TextEncoder().encode("this is a text file"),
      engine,
    );

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
  });

  it("refuses an empty file rather than reading it as an empty library", async () => {
    // SQLite opens a zero byte file as a valid database with nothing in it, so
    // the layer above would report "that is not a Calibre library" about a file
    // that is not a database at all.
    const reading = await openSqlite(new Uint8Array(0), engine);

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
  });

  it("refuses a database whose pages no longer agree with each other", async () => {
    // What a copy taken while calibre-web was writing looks like: a header that
    // still parses over a page that has been overwritten with something else.
    // The whole reason the reference library's own journal mode was called out
    // on the ticket is that SQLite will answer from a file like this rather
    // than refuse it, so the refusal has to be asked for.
    const bytes = await databaseOf(
      "CREATE TABLE shelf (id INTEGER, title TEXT)",
      "INSERT INTO shelf VALUES (1, 'Dune')",
    );
    const pageSize = (bytes[16]! << 8) | bytes[17]!;
    bytes.fill(0x5a, pageSize, pageSize + 64);

    const reading = await openSqlite(bytes, engine);

    expect(reading).toEqual({ ok: false, failure: "damaged" });
  });

  it("refuses a file past the byte ceiling without reading it", async () => {
    // A `File` rather than the bytes: the point of the second door is that the
    // size is refused before an `ArrayBuffer` of it exists, so a file that
    // would not fit in memory never gets there. `arrayBuffer` throws if it is
    // ever called, which is what makes this an assertion rather than a hope.
    const file = {
      size: MAX_DATABASE_BYTES + 1,
      arrayBuffer: () => {
        throw new Error("the bytes were read after all");
      },
    } as unknown as File;

    expect(await openSqliteFile(file, engine)).toEqual({
      ok: false,
      failure: "too-large",
    });
  });

  it("closes a database it is about to refuse", async () => {
    // A file that opens and then fails a pragma is still holding all of itself
    // in WebAssembly memory, and the engine module is imported once and cached,
    // so a leak here accumulates across every refused pick for the life of the
    // tab. The loader is the seam: the engine is real everywhere else, and here
    // it is one that records what was closed.
    const closed: string[] = [];
    const failing = () =>
      Promise.resolve({
        Database: class {
          exec(): never {
            throw new Error("file is not a database");
          }
          export() {
            return new Uint8Array() as Uint8Array<ArrayBuffer>;
          }
          close() {
            closed.push("closed");
          }
        },
      });

    const reading = await openSqlite(new Uint8Array([1, 2, 3]), {
      engine: failing,
    });

    expect(reading).toEqual({ ok: false, failure: "not-a-database" });
    expect(closed).toEqual(["closed"]);
  });

  it("still names the refusal when closing the handle throws too", async () => {
    // The close runs on a handle that has already misbehaved. A throw there
    // would replace the closed failure union with an exception, and the member
    // holding a damaged copy would be told something generic went wrong.
    const engineThatCannotClose = () =>
      Promise.resolve({
        Database: class {
          exec(): never {
            throw new Error("database disk image is malformed");
          }
          export() {
            return new Uint8Array() as Uint8Array<ArrayBuffer>;
          }
          close(): never {
            throw new Error("close failed too");
          }
        },
      });

    const reading = await openSqlite(new Uint8Array([1, 2, 3]), {
      engine: engineThatCannotClose,
    });

    expect(reading).toEqual({ ok: false, failure: "damaged" });
  });

  it("says the engine is missing rather than throwing", async () => {
    // What a browser that refuses to compile WebAssembly looks like from here,
    // which is the shape a content security policy without 'wasm-unsafe-eval'
    // produces. It cannot be provoked in a test environment, so the loader is
    // the seam and this is the arm it exists for.
    const reading = await openSqlite(await databaseOf("CREATE TABLE a (b)"), {
      engine: () => Promise.reject(new Error("compilation refused")),
    });

    expect(reading).toEqual({ ok: false, failure: "no-engine" });
  });
});

describe("a database opened here is never written", () => {
  it("refuses an insert on its own connection", async () => {
    // `PRAGMA query_only` rather than a promise not to write one. The member's
    // own file is already out of reach, since a picked `File` is a snapshot;
    // this is the half that stops a bug here mutating the copy in memory and
    // reporting rows nobody's library contains.
    const bytes = await databaseOf(
      "CREATE TABLE shelf (title TEXT)",
      "INSERT INTO shelf VALUES ('Dune')",
    );
    const database = await open(bytes);

    database.query("INSERT INTO shelf VALUES ('Solaris')");

    expect(database.query("SELECT count(*) AS n FROM shelf")).toEqual([
      { n: 1 },
    ]);
    database.close();
  });
});

describe("what one statement may hand back", () => {
  it("drops a cell wider than the ceiling and keeps the row", async () => {
    // The row is the point. A hostile file putting a hundred megabytes in one
    // description must not cost the library it sits in, which is the same rule
    // `bookBounds.ts` applies one layer up.
    const wide = "a".repeat(MAX_CELL_BYTES + 1);
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (title TEXT, description TEXT)",
        `INSERT INTO shelf VALUES ('Dune', '${wide}')`,
      ),
    );

    expect(database.query("SELECT title, description FROM shelf")).toEqual([
      { title: "Dune", description: null },
    ]);
    database.close();
  });

  it("measures a cell in bytes, not in code units", async () => {
    // One over the ceiling, in bytes. Each is two UTF-16 units and four bytes,
    // so a ceiling read off `length` would admit twice what it meant to and
    // this row would come back whole.
    const emoji = "\u{1F4DA}".repeat(MAX_CELL_BYTES / 4 + 1);
    const database = await open(
      await databaseOf(
        "CREATE TABLE shelf (title TEXT)",
        `INSERT INTO shelf VALUES ('${emoji}')`,
      ),
    );

    expect(database.query("SELECT title FROM shelf")).toEqual([
      { title: null },
    ]);
    database.close();
  });
});

describe("the engine the policy was measured against", () => {
  it("is the version the module names", () => {
    // The content security policy grants `'wasm-unsafe-eval'` on the strength
    // of one measurement: that this engine contains no `eval(` and no `new
    // Function`. That is a fact about a version, the dependency is pinned
    // exactly, and a bot bumps minor and patch releases on its own, so without
    // this the sentence justifying the relaxation goes stale with nothing red.
    // Read through `import.meta.glob`, which needs no `node:fs` and no file
    // URL: this file runs under happy-dom, where `import.meta.url` is not one.
    const manifest = JSON.parse(raw("../../package.json")) as {
      dependencies: Record<string, string>;
    };
    const source = raw("../../src/lib/sqlite.ts");

    const pinned = manifest.dependencies["sql.js"];
    expect(pinned).toMatch(/^\d+\.\d+\.\d+$/);
    expect(source).toContain(`sql.js ${pinned} contains no \`eval(\``);
  });
});

describe("how many rows one statement may hand back", () => {
  it("stops at the ceiling rather than building every row", async () => {
    const over = MAX_ROWS_PER_QUERY + 1;
    const database = await open(
      await databaseOf(
        "CREATE TABLE wide (n INTEGER)",
        `INSERT INTO wide
           WITH RECURSIVE counter(n) AS (
             SELECT 1 UNION ALL SELECT n + 1 FROM counter WHERE n < ${over}
           )
           SELECT n FROM counter`,
      ),
    );

    expect(database.query("SELECT count(*) AS n FROM wide")).toEqual([
      { n: over },
    ]);
    expect(database.query("SELECT n FROM wide")).toHaveLength(
      MAX_ROWS_PER_QUERY,
    );
    database.close();
  });
});

describe("a question the file cannot answer", () => {
  it("is an empty result and never a throw", async () => {
    const database = await open(await databaseOf("CREATE TABLE shelf (title)"));

    expect(database.query("SELECT * FROM nothing_like_this")).toEqual([]);
    expect(database.query("SELECT title FROM shelf")).toEqual([]);
    database.close();
  });

  it("throws only for a query after close, which is a caller's bug", async () => {
    const database = await open(await databaseOf("CREATE TABLE shelf (title)"));
    database.close();

    expect(() => database.query("SELECT 1")).toThrow();
  });
});
