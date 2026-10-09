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

import initSqlJs from "sql.js/dist/sql-wasm-browser.js";

import type { SqliteEngineLoader } from "../../src/lib/sqlite";

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
