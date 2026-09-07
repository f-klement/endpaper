/**
 * The little of sql.js that `sqlite.ts` uses, declared rather than depended on.
 *
 * **`@types/sql.js` is deliberately not installed.** It opens with
 * `/// <reference types="node" />` and `/// <reference types="emscripten" />`,
 * and a triple slash reference is not filtered by `tsconfig.json`'s `types`
 * allowlist: installing it hands `process`, `Buffer` and the whole Node global
 * surface to every component and every test in this package. That allowlist is
 * what keeps a browser bundle from reaching for them, and `types/build-env.d.ts`
 * says so at its own site. Declaring the four members used here costs less than
 * the leak.
 *
 * The import specifier is the **explicit browser build**, not the package name.
 * `sql.js` declares an `exports` map whose `browser` condition resolves to
 * `dist/sql-wasm-browser.js` and whose default resolves to `dist/sql-wasm.js`,
 * so the application and the suite would otherwise load two different files and
 * the suite would be testing the one that does not ship. The two `.wasm` files
 * are byte identical (verified with `cmp` on 1.14.2), and the browser JS is the
 * one carrying no `require()`, which is what a browser bundle wants.
 */

declare module "sql.js/dist/sql-wasm-browser.js" {
  /** What one `SELECT` answered: the column names, then a row per array. */
  export interface QueryExecResult {
    readonly columns: string[];
    readonly values: SqlValue[][];
  }

  export type SqlValue = number | string | Uint8Array | null;

  export interface SqlJsDatabase {
    /** Run one or more statements and return a result set per statement. */
    exec(sql: string, params?: SqlValue[]): QueryExecResult[];
    /**
     * The database as bytes.
     *
     * Never called by `src/`, which only ever reads: it is here because
     * `tests/lib/sqliteFixtures.ts` builds a real library and hands the bytes
     * to `openSqlite`, which is what lets the reader be tested against a
     * database rather than against a stand in that answers rows.
     */
    export(): Uint8Array<ArrayBuffer>;
    close(): void;
  }

  export interface SqlJsStatic {
    Database: new (bytes?: Uint8Array) => SqlJsDatabase;
  }

  export interface SqlJsConfig {
    /**
     * The compiled module, handed over rather than fetched.
     *
     * Supplying it is what keeps the engine from resolving a URL of its own:
     * see `sqlite.ts` for why this module never lets it do that.
     */
    wasmBinary?: ArrayBuffer;
  }

  export default function initSqlJs(config?: SqlJsConfig): Promise<SqlJsStatic>;
}
