/**
 * Real SQLite databases, built in the test and handed over as bytes.
 *
 * **The engine here is the one that ships**, resolved by the same explicit path
 * `src/lib/sqlite.ts` imports rather than by the package name: `sql.js` declares
 * an `exports` map with a `browser` condition, so a bare specifier gives the
 * suite `dist/sql-wasm.js` and the browser `dist/sql-wasm-browser.js`, and the
 * suite would then be testing the file that does not ship.
 *
 * **The compiled module is read off disk rather than fetched.** `sqlite.ts`
 * fetches the asset URL Vite emitted, and in a suite there is no server behind
 * that URL. `openSqlite` takes the bytes instead, which is an argument and not a
 * mock: every line below the load runs identically either way, and what it
 * leaves untested is that one fetch.
 *
 * Not a double, deliberately. `tests/doubles/README.md`: a double is suite wide,
 * so a module with its own test file cannot be one, and `sqlite.ts` has one.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import fc from "fast-check";
import initSqlJs, { type SqlValue } from "sql.js/dist/sql-wasm-browser.js";

import {
  MAX_CELL_BYTES,
  MAX_ROWS_PER_QUERY,
  type SqliteEngineLoader,
} from "../../src/lib/sqlite";
import { type Total } from "../property";

const require = createRequire(import.meta.url);

/** The shipped `.wasm`, read off disk rather than fetched from nothing. */
function wasmBinary(): ArrayBuffer {
  const path = require.resolve("sql.js/dist/sql-wasm-browser.wasm");
  const bytes = readFileSync(path);
  return bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  ) as ArrayBuffer;
}

/**
 * The loader `openSqlite` takes, over the engine that ships.
 *
 * Built once: compiling the module is most of what these files spend.
 */
export const engine: { engine: SqliteEngineLoader } = {
  engine: (() => {
    let compiled: ReturnType<typeof initSqlJs> | null = null;
    return () => (compiled ??= initSqlJs({ wasmBinary: wasmBinary() }));
  })(),
};

/**
 * A database holding whatever these statements build.
 *
 * Written rather than checked in, because a fixture file is a claim about bytes
 * nobody can read: the schema under test is legible here and a change to it is
 * a diff rather than a new binary.
 */
export async function databaseOf(
  ...statements: string[]
): Promise<Uint8Array<ArrayBuffer>> {
  const handle = new (await engine.engine()).Database();
  for (const statement of statements) handle.exec(statement);
  const bytes = handle.export();
  handle.close();
  return bytes;
}

/**
 * The tables a Calibre library has, as Calibre 8 creates them.
 *
 * Trimmed to the columns this app reads, and that is the point rather than a
 * shortcut: a reader that only works against the full schema is a reader that
 * breaks on the next Calibre release, and the ticket says in as many words that
 * the schema is not guaranteed.
 */
export const CALIBRE_SCHEMA = [
  `CREATE TABLE books (
     id INTEGER PRIMARY KEY,
     title TEXT NOT NULL DEFAULT 'Unknown',
     sort TEXT,
     pubdate TIMESTAMP DEFAULT '0101-01-01 00:00:00+00:00',
     series_index REAL NOT NULL DEFAULT 1.0,
     path TEXT NOT NULL DEFAULT '',
     has_cover BOOL DEFAULT 0
   )`,
  `CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sort TEXT)`,
  `CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER)`,
  `CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)`,
  `CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER)`,
  `CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT NOT NULL)`,
  `CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INTEGER, series INTEGER)`,
  `CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT NOT NULL)`,
  `CREATE TABLE books_languages_link (id INTEGER PRIMARY KEY, book INTEGER, lang_code INTEGER, item_order INTEGER)`,
  `CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER, text TEXT NOT NULL)`,
  `CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT)`,
  `CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER, format TEXT, uncompressed_size INTEGER, name TEXT)`,
];

// --- arbitraries over a database, for the properties ------------------------
//
// **A spec and not bytes**, the rule `zipFixtures.ts` states for an archive: a
// byte arbitrary never passes SQLite's sixteen byte header, so it tests one
// refusal and calls it fuzzing. What a property draws is tables, columns and
// rows over a reader's own vocabulary; the engine that ships builds the file,
// and byte patches over the header and the first page are what damage it.

/**
 * A text cell `bytes` long, or a blob of that many, named rather than spelled
 * so a counterexample carrying one at the cell ceiling prints as a number.
 * **`astral` spends four bytes a character**, two code units each, which is
 * the cell a ceiling read off `length` admits twice over.
 */
export interface WideCell {
  readonly wide: number;
  readonly as: "text" | "astral" | "blob";
}

export type CellSpec = SqlValue | WideCell;

export interface TableSpec {
  readonly name: string;
  readonly columns: readonly string[];
  readonly rows: readonly (readonly CellSpec[])[];
  /**
   * Further rows numbered from one, past the drawn ones, in the first column.
   * **Named rather than drawn one by one**, because the row ceiling is
   * two hundred thousand and a property cannot draw that many cells.
   */
  readonly counted: number | undefined;
}

export interface DatabaseSpec {
  readonly tables: readonly TableSpec[];
  /**
   * The file's length to pad to with zeroes, or `undefined`. What would reach
   * the byte ceiling: a database past `MAX_DATABASE_BYTES` is refused by its
   * size, so the bytes past the engine's own pages need be nothing in
   * particular. **No generator here draws one**, for the reason at
   * `boundedDatabaseSpec`.
   */
  readonly padTo: number | undefined;
}

/** A reader's names, which is where a drawn database is aimed. */
export interface DatabaseVocabulary {
  readonly tables: readonly string[];
  readonly columns: readonly string[];
  /** Cell values the reader reads meaning into. */
  readonly values: readonly SqlValue[];
}

function quoted(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}

function cellValue(cell: CellSpec): SqlValue {
  if (cell === null || typeof cell !== "object" || cell instanceof Uint8Array) {
    return cell;
  }
  if (cell.as === "blob") return new Uint8Array(cell.wide);
  if (cell.as === "astral") return "\u{1F4DA}".repeat(Math.ceil(cell.wide / 4));
  return "a".repeat(cell.wide);
}

/** The dear databases by spec, built once a worker. */
const BUILT = new Map<string, Uint8Array<ArrayBuffer>>();

function keyOf(spec: DatabaseSpec): string | null {
  // A spec holding a blob value has no stable key and is not kept. A number
  // JSON cannot spell is tagged, or `NaN` and `null` would share a database.
  try {
    return JSON.stringify(spec, (_, value: unknown) => {
      if (value instanceof Uint8Array) throw new Error("unkeyed");
      if (
        typeof value === "number" &&
        (!Number.isFinite(value) || Object.is(value, -0))
      ) {
        return { number: String(Object.is(value, -0) ? "-0" : value) };
      }
      return value;
    });
  } catch {
    return null;
  }
}

/**
 * The database a spec describes, written by the engine that ships.
 *
 * **A statement the engine refuses is skipped, not thrown**: a drawn table
 * with two columns of one name is not a database anybody can write, and the
 * property is about what a reader does with a file that exists.
 */
export async function buildDatabase(
  spec: DatabaseSpec,
): Promise<Uint8Array<ArrayBuffer>> {
  const key = keyOf(spec);
  const known = key === null ? undefined : BUILT.get(key);
  if (known !== undefined) return known;
  const handle = new (await engine.engine()).Database();
  for (const table of spec.tables) {
    if (table.columns.length === 0) continue;
    const name = quoted(table.name);
    try {
      handle.exec(
        `CREATE TABLE ${name} (${table.columns.map(quoted).join(", ")})`,
      );
    } catch {
      continue;
    }
    const slots = table.columns.map(() => "?").join(", ");
    for (const row of table.rows) {
      const values = table.columns.map((_, at) => cellValue(row[at] ?? null));
      try {
        handle.exec(`INSERT INTO ${name} VALUES (${slots})`, values);
      } catch {
        // A constraint the drawn table declared; the row is not written.
      }
    }
    if (table.counted !== undefined && table.counted > 0) {
      const first = quoted(table.columns[0]!);
      handle.exec(
        `INSERT INTO ${name} (${first})
           WITH RECURSIVE counter(n) AS (
             SELECT 1 UNION ALL SELECT n + 1 FROM counter WHERE n < ${table.counted}
           )
           SELECT n FROM counter`,
      );
    }
  }
  let bytes = handle.export();
  handle.close();
  if (spec.padTo !== undefined && spec.padTo > bytes.length) {
    const padded = new Uint8Array(spec.padTo);
    padded.set(bytes);
    bytes = padded;
  }
  // **Kept only where it is dear**: a database past the byte ceiling is
  // sixty four mebibytes and one past the row ceiling two hundred thousand
  // rows, and building either per draw is what a property pays in memory,
  // which the suite pod has a limit on. An ordinary one costs a millisecond,
  // and keeping every one drawn grew this map by every draw of every run.
  const dear =
    spec.padTo !== undefined ||
    spec.tables.some((table) => table.counted !== undefined);
  if (key !== null && dear) BUILT.set(key, bytes);
  return bytes;
}

/** A value for a cell: the reader's own, the column types' edges, and noise. */
function cellSpec(vocabulary: DatabaseVocabulary): fc.Arbitrary<CellSpec> {
  return fc.oneof(
    { arbitrary: fc.constantFrom(...vocabulary.values), weight: 6 },
    { arbitrary: fc.constant(null), weight: 2 },
    {
      arbitrary: fc.constantFrom(
        0,
        -1,
        1.5,
        Number.MAX_SAFE_INTEGER,
        Number.NaN,
        "",
        " ",
        "true",
      ),
      weight: 2,
    },
    { arbitrary: fc.string({ maxLength: 16, unit: "binary" }), weight: 2 },
    { arbitrary: fc.uint8Array({ maxLength: 8 }), weight: 1 },
  );
}

/** A table: the reader's name and columns mostly, its rows few. */
function tableSpec(
  vocabulary: DatabaseVocabulary,
  cell: fc.Arbitrary<CellSpec>,
): fc.Arbitrary<TableSpec> {
  return fc.record({
    name: fc.oneof(
      { arbitrary: fc.constantFrom(...vocabulary.tables), weight: 6 },
      { arbitrary: fc.constantFrom("other", "x y", 'q"t'), weight: 1 },
    ),
    columns: fc.uniqueArray(
      fc.oneof(
        { arbitrary: fc.constantFrom(...vocabulary.columns), weight: 6 },
        { arbitrary: fc.constantFrom("other", "x y", 'q"t'), weight: 1 },
      ),
      { minLength: 1, maxLength: 8 },
    ),
    rows: fc.array(fc.array(cell, { maxLength: 8 }), { maxLength: 4 }),
    counted: fc.constant(undefined),
  } satisfies Total<TableSpec>);
}

/**
 * A database over a reader's vocabulary: tables of its own names, columns of
 * its own names, cells of its own values, mostly few of each.
 */
export function databaseSpec(
  vocabulary: DatabaseVocabulary,
): fc.Arbitrary<DatabaseSpec> {
  return fc.record({
    tables: fc.array(tableSpec(vocabulary, cellSpec(vocabulary)), {
      maxLength: 3,
    }),
    padTo: fc.constant(undefined),
  } satisfies Total<DatabaseSpec>);
}

/**
 * A database aimed at the bounds `sqlite.ts` holds while it reads: a cell at
 * and past the cell ceiling in each of its three units, and a table past the
 * row ceiling.
 *
 * **No file past the byte ceiling**, for `stores.test.ts`'s reason for the
 * Moon+ database bomb. That arm was one fixed spec, the same 64 MiB file about
 * twenty nine times a run, copied again by every patch and by the metered
 * file over it, and it took the suite pod past its memory limit, measured:
 * the worker running this property peaked at 1250.6 MiB with it and 659.6
 * without, and a run was killed at 137 inside it. It could show only that the
 * size is refused before a read, which no patch changes because nothing is
 * read, and `sqlite.test.ts`'s named case `refuses a file past the byte
 * ceiling without reading it` holds that with a file that allocates nothing.
 *
 * **Composed, for the reason every bomb here is**: a wide cell has to sit in a
 * table the engine wrote and the property reads, and independent draws of the
 * three rarely line up.
 */
export function boundedDatabaseSpec(
  vocabulary: DatabaseVocabulary,
): fc.Arbitrary<DatabaseSpec> {
  // **Both edges of the cell ceiling in one table**, so the unit is the one
  // choice left to draw, and each unit's wide cell is a tenth of what a run
  // draws from any seed. Drawn one cell at a time it was a few hundredths,
  // and a run missed a unit on a few in a hundred, measured.
  const cells = fc
    .constantFrom<WideCell["as"]>("text", "astral", "blob")
    .map((as): TableSpec => ({
      name: "wide",
      columns: ["cell"],
      rows: [
        [{ wide: MAX_CELL_BYTES, as }],
        [{ wide: MAX_CELL_BYTES + 1, as }],
      ],
      counted: undefined,
    }));
  // One past the row ceiling and not at it: the property asserts at most the
  // ceiling, which a table at it cannot fail, and each costs a table of two
  // hundred thousand rows.
  const rows = fc.constant<TableSpec>({
    name: "long",
    columns: ["n"],
    rows: [],
    counted: MAX_ROWS_PER_QUERY + 1,
  });
  const one = (table: fc.Arbitrary<TableSpec>) =>
    fc.record({
      tables: table.map((drawn) => [drawn]),
      padTo: fc.constant(undefined),
    } satisfies Total<DatabaseSpec>);
  return fc.oneof(
    { arbitrary: databaseSpec(vocabulary), weight: 2 },
    { arbitrary: one(cells), weight: 3 },
    // One, because each costs a table of two hundred thousand rows read back
    // whole, and one of six is still a tenth of a run's draws.
    { arbitrary: one(rows), weight: 1 },
  );
}

/**
 * A database shaped like a reader's own: each of its tables present or not,
 * each with its real columns less sometimes one, every row a value per column.
 *
 * **What reaches a reader's walk rather than its signature check.** Tables
 * and columns drawn independently rarely name the pair a reader requires
 * before it reads a row, so the shape is taken from the reader's schema and
 * only the dropping is drawn. **And a column's values are its own**, keyed
 * `table.column` before `column`: a join needs the same small id on both
 * sides, and a value drawn from every column's pool at once lands one on
 * few draws. Measured on the Calibre intake: drawn from one pool, no library
 * in twenty thousand draws carried a book with an author and a description.
 * A drawn noise table rides beside it.
 */
export function schemaSpec(
  shapes: Readonly<Record<string, readonly string[]>>,
  vocabulary: DatabaseVocabulary,
  columnValues: Readonly<Record<string, readonly SqlValue[]>> = {},
): fc.Arbitrary<DatabaseSpec> {
  const cell = cellSpec(vocabulary);
  const valueFor = (table: string, column: string): fc.Arbitrary<CellSpec> => {
    const own = columnValues[`${table}.${column}`] ?? columnValues[column];
    return own === undefined
      ? cell
      : fc.oneof(
          { arbitrary: fc.constantFrom(...own), weight: 6 },
          { arbitrary: cell, weight: 1 },
        );
  };
  const shaped = Object.entries(shapes).map(([name, columns]) =>
    fc
      .oneof(
        { arbitrary: fc.constant(columns), weight: 4 },
        {
          arbitrary: fc
            .nat({ max: Math.max(0, columns.length - 1) })
            .map((dropped) => columns.filter((_, at) => at !== dropped)),
          weight: 1,
        },
      )
      .chain((kept) =>
        fc.record({
          name: fc.constant(name),
          columns: fc.constant(kept),
          rows: fc.array(
            fc.tuple(...kept.map((column) => valueFor(name, column))),
            { maxLength: 4 },
          ),
          counted: fc.constant(undefined),
        } satisfies Total<TableSpec>),
      ),
  );
  return fc.record({
    tables: fc
      .tuple(
        ...shaped.map((table) =>
          fc.oneof(
            { arbitrary: table, weight: 4 },
            { arbitrary: fc.constant(null), weight: 1 },
          ),
        ),
        fc.array(tableSpec(vocabulary, cell), { maxLength: 1 }),
      )
      .map((drawn) =>
        drawn.flat().filter((table): table is TableSpec => table !== null),
      ),
    padTo: fc.constant(undefined),
  } satisfies Total<DatabaseSpec>);
}

/**
 * A drawn database with a reader's own accepted rows put back into it: each
 * base table's rows ahead of the drawn ones where the drawn table kept every
 * column, and the base table whole where it did not or was not drawn.
 *
 * **What a witness asking for a library the reader reads needs**: a book in
 * a schema of joins is several rows agreeing on an id, and drawn rows agree
 * on few draws. Measured on the Calibre intake: one draw in a hundred carried
 * a book with an author and a description, so a run from a fresh seed missed
 * it on about one run in eight.
 */
export function graftDatabase(
  drawn: DatabaseSpec,
  base: readonly TableSpec[],
): DatabaseSpec {
  const tables = drawn.tables.map((table) => {
    const own = base.find((one) => one.name === table.name);
    if (own === undefined) return table;
    const kept = own.columns.every(
      (column, at) => table.columns[at] === column,
    );
    return kept ? { ...table, rows: [...own.rows, ...table.rows] } : own;
  });
  const missing = base.filter(
    (one) => !drawn.tables.some((table) => table.name === one.name),
  );
  return { ...drawn, tables: [...tables, ...missing] };
}

/**
 * The tables and columns a schema declares, read back off a database built
 * from it rather than parsed out of its text.
 *
 * **Derived, so a column added to a schema here is drawn with no second
 * edit**, and the engine is the parser: a `CREATE TABLE` this would misread is
 * one the engine itself declared differently.
 */
export async function shapesOf(
  schema: readonly string[],
): Promise<Record<string, string[]>> {
  const handle = new (await engine.engine()).Database();
  for (const statement of schema) handle.exec(statement);
  const shapes: Record<string, string[]> = {};
  const tables = handle.exec(
    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
  );
  for (const [name] of tables[0]?.values ?? []) {
    const columns = handle.exec(`PRAGMA table_info(${quoted(String(name))})`);
    shapes[String(name)] = (columns[0]?.values ?? []).map((row) =>
      String(row[1]),
    );
  }
  handle.close();
  return shapes;
}
