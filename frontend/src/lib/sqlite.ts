/**
 * A SQLite file, read in the member's own browser and never written.
 *
 * **This exists because a Calibre library has exactly one writer.** calibre-web
 * owns the household's library and the Calibre desktop is scaled to zero so
 * that two processes never hold it at once; reading is not writing, but a third
 * process reading the live file is still a third process. A `File` handed over
 * by an `<input type="file">` is a snapshot the page cannot write back to, and
 * the bytes below are copied into WebAssembly memory before a statement runs.
 * So the route this module opens **cannot be a second writer**, by construction
 * rather than by promise. That is the whole argument for doing it here rather
 * than server side, and `docs/decisions.md` carries it.
 *
 * `PRAGMA query_only = 1` is the belt to that braces: the engine itself refuses
 * an `INSERT` on this connection, so a bug here fails loudly rather than
 * mutating a copy somebody later trusts.
 *
 * **A member supplied database is untrusted input**, in exactly the way a
 * catalogue record is. Three bounds, and **only the first of them bounds
 * memory**, which is worth saying because the obvious reading is that all three
 * do. `MAX_DATABASE_BYTES` is checked against `File.size` before a byte is
 * read, so a file lying about its own shape is stopped by the bound rather than
 * by the claim, and every allocation below is then transitively bounded by it:
 * a 64 MiB SQLite file cannot hold an unbounded number of rows.
 *
 * `MAX_ROWS_PER_QUERY` and `MAX_CELL_BYTES` bound **what a caller is handed**,
 * and they run after `exec` has materialised the result set, so the engine has
 * already spent that memory when they apply. What they are worth is the
 * allocation they do not then make in JavaScript, and the field they refuse to
 * carry into a book. What the values mean is `calibre.ts`, and what the API
 * will hold is `bookBounds.ts`.
 *
 * **Lazy loaded, and it is the largest thing this app can pull in.** Nothing
 * imports this at the top of a module the shell reaches: the Calibre import
 * card resolves it with `await import` when a member picks a file.
 * `tests/pages/SettingsPage/LibrarySettingsPage/hooks.test.tsx` asserts that,
 * because a static import would compile, pass every other test, and move a
 * third of a megabyte into the shell.
 *
 * Measured on the build at this tip. A size does not vary by node, so no node
 * is named: the figures are the build's, not a machine's.
 *
 * The engine is
 * `assets/sql-wasm-browser-*.wasm` at 658.41 kB raw and **326.00 kB gzipped**,
 * this module's own chunk is 41.10 kB raw and 14.67 gzipped, and `calibre.ts`
 * is 5.68 kB raw and 2.20 gzipped: 342.87 kB gzipped for the route, against a
 * main chunk of 340.08 kB gzipped that carries none of it.
 *
 * **Every figure here is from one build and the two small ones move with any
 * code edit**, by hundredths of a kilobyte. Requote them from a build rather
 * than carrying them forward: a comment does not move them, since comments are
 * stripped, and anything else does.
 *
 * **The split is not clean, and the part that is not is the small part.** The
 * service worker precaches by `globPatterns: ["**​/*.{js,css,...}"]`, which
 * has no `wasm` in it, so the 326.00 kB is downloaded only by a session that
 * opens this card. The 14.66 kB wrapper chunk is a `.js` and is precached like
 * every other lazy chunk in this app, so every session pays that much.
 *
 * **`script-src` had to be relaxed for this and the relaxation is one token.**
 * `backend/middleware.py` grants `'wasm-unsafe-eval'`, which permits compiling
 * WebAssembly and nothing else; `'unsafe-eval'` is still refused, and so is
 * `'unsafe-inline'`. **sql.js 1.14.2 contains no `eval(` and no `new Function`,
 * measured over `dist/sql-wasm-browser.js`**, so the wider grant would have
 * bought nothing.
 *
 * **That measurement is about a version, and this is the only place the version
 * is written down.** The dependency is pinned exactly and a bot bumps minor and
 * patch releases automatically, so the sentence above would otherwise go stale
 * with nothing red: `tests/lib/sqlite.test.ts` compares it against
 * `package.json` and fails the build when the two part company, which is what
 * turns a bump into a prompt to re-run the scan.
 * `backend/tests/test_middleware.py` pins the resulting policy by exact
 * equality.
 */

import initSqlJs, {
  type SqlJsDatabase,
  type SqlJsStatic,
  type SqlValue,
} from "sql.js/dist/sql-wasm-browser.js";
import wasmUrl from "sql.js/dist/sql-wasm-browser.wasm?url";

/**
 * How many bytes of database may be copied into WebAssembly memory.
 *
 * The engine holds the whole file, so a tab pays for the picked file, the copy
 * and the rows read out of it. **Not measured against the household library**,
 * which was not reachable from where this was written: a Calibre `metadata.db`
 * runs to roughly a kilobyte a book plus whatever the descriptions weigh, so
 * 897 books with 15 KB of description each is about 13 MB. 64 MiB is a library
 * four times that size at the same description density, and a file past it is
 * refused rather than allowed to decide how much memory the tab takes.
 */
export const MAX_DATABASE_BYTES = 64 * 1024 * 1024;

/**
 * How many rows one statement may hand back.
 *
 * A bound on the answer rather than on the question: it stops the row objects
 * being built rather than stopping the engine reading them, so it is a bound on
 * this module's own allocation and not on the engine's. Calibre's widest table
 * for a 897 book library is `identifiers` at roughly one row a book; 200,000 is
 * a library two orders of magnitude larger.
 */
export const MAX_ROWS_PER_QUERY = 200_000;

/**
 * How wide one text or blob cell may be.
 *
 * Every value this app keeps is bounded again by `bookBounds.ts`, which cuts to
 * a column width. This is the earlier bound: it drops a cell nothing here could
 * want before it is carried any further.
 *
 * **1 MiB is 26 times the widest field this app stores**, which is
 * `TEXT_CEILINGS.description` at 10,000 code points, or 40,000 bytes at the
 * four bytes a code point can cost. It is deliberately loose: this bound is
 * about a cell that is absurd rather than a cell that is too long, and the
 * cutting to a column width happens later and knows which field it is looking
 * at.
 */
export const MAX_CELL_BYTES = 1024 * 1024;

/**
 * Why a file yielded no database. Closed, because each is a different sentence
 * to a member holding a file that did not work.
 */
export type SqliteFailure =
  /** Not a SQLite database, or one this engine will not open. */
  | "not-a-database"
  /** Opens, then disagrees with itself: a torn copy reads like this. */
  | "damaged"
  /** Past `MAX_DATABASE_BYTES`. */
  | "too-large"
  /** The engine could not be loaded or compiled in this browser. */
  | "no-engine";

/** One row, by column name. `undefined` for a column the statement omitted. */
export type SqliteRow = Readonly<Record<string, SqlValue | undefined>>;

/**
 * A database opened for reading.
 *
 * `query` never throws for a statement the file cannot answer: a table that is
 * not there, a column that is not there and a value the bounds refuse are all
 * outcomes a caller has to report either way. It throws only for a caller bug,
 * which is what `close` having been called already is.
 */
export interface SqliteDatabase {
  query(sql: string, params?: readonly SqlValue[]): SqliteRow[];
  close(): void;
}

export type SqliteReading =
  | { readonly ok: true; readonly database: SqliteDatabase }
  | { readonly ok: false; readonly failure: SqliteFailure };

/** How the compiled engine is obtained. One seam, and the only one. */
export type SqliteEngineLoader = () => Promise<SqlJsStatic>;

/**
 * The compiled engine, handed to sql.js rather than fetched by it.
 *
 * sql.js resolves a URL of its own when it is not given a binary, and it
 * resolves it against `document.currentScript` or `import.meta.url`, neither of
 * which survives being bundled the way this app bundles. Fetching the asset URL
 * here means the request is an ordinary same origin one that `connect-src
 * 'self'` already permits, and the URL is the one Vite emitted rather than one
 * assembled at runtime.
 *
 * **Replaceable, and the replacement is not a mock.** The suite passes a loader
 * that reads the same shipped `.wasm` off disk, because a `fetch` of a build
 * asset has no server behind it there, and a second loader that rejects, which
 * is the only way to reach the `no-engine` arm: a browser refusing to compile
 * WebAssembly is not something a test environment can be talked into. What that
 * leaves untested is this function's own two lines.
 */
const defaultEngine: SqliteEngineLoader = async () =>
  initSqlJs({ wasmBinary: await (await fetch(wasmUrl)).arrayBuffer() });

/** A cell the bounds will carry, or `null` for one they will not. */
function boundCell(value: SqlValue): SqlValue {
  if (typeof value === "string") {
    // Bytes rather than code units: the ceiling is about memory, and a string
    // of astral characters costs four bytes each where `length` counts two.
    return new Blob([value]).size > MAX_CELL_BYTES ? null : value;
  }
  if (value instanceof Uint8Array) {
    return value.byteLength > MAX_CELL_BYTES ? null : value;
  }
  return value;
}

/**
 * Open a database held in memory, or say why not.
 *
 * `null` shaped as a closed failure rather than a throw, for `readOpf`'s
 * reason: "this file is not a database" is an outcome the caller reports either
 * way, and there is nothing a caller could do differently for each of the ways
 * a file can fail to be one.
 */
export async function openSqlite(
  bytes: Uint8Array,
  options: { readonly engine?: SqliteEngineLoader } = {},
): Promise<SqliteReading> {
  if (bytes.byteLength > MAX_DATABASE_BYTES) {
    return { ok: false, failure: "too-large" };
  }
  // **SQLite reads an empty file as an empty database**, header and all, so
  // without this a member who picked a zero byte file is told their Calibre
  // library has no Calibre tables in it. Refused by name, because "that file is
  // not a database" is the sentence that is true.
  if (bytes.byteLength === 0) {
    return { ok: false, failure: "not-a-database" };
  }

  let engine;
  try {
    engine = await (options.engine ?? defaultEngine)();
  } catch {
    return { ok: false, failure: "no-engine" };
  }

  // Declared outside the `try` so the catch can close it. A database that
  // opened and then failed a pragma is still holding the whole file in
  // WebAssembly memory, and the engine module is imported once and cached, so
  // every refused pick would keep up to `MAX_DATABASE_BYTES` of heap until the
  // tab was closed.
  let handle: SqlJsDatabase | undefined;
  try {
    handle = new engine.Database(bytes);
    // **Not a formality.** `sqlite3_open` on a memory image succeeds without
    // reading a page, so a file that is not a database fails on the first
    // statement rather than on the open, and a torn copy fails later still.
    // This is the statement that makes both of them fail here.
    handle.exec("PRAGMA query_only = 1");
    // **The copy is checked, because the hazard is a copy that reads fine.**
    // The reference library is kept in a rollback journal mode, so a copy taken
    // while something was writing is a file with partly written pages and no
    // journal to undo them, and SQLite will answer from it rather than refuse
    // it. `integrity_check` is what turns that into a refusal here.
    //
    // The exclusion, stated: it walks the b-trees and the indexes, so it
    // catches a page that no longer fits the structure around it and not a page
    // whose values are simply from a moment ago. `(1)` stops at the first
    // problem, because the count of problems is not a different answer.
    const checked = handle.exec("PRAGMA integrity_check(1)");
    if (checked[0]?.values[0]?.[0] !== "ok") throw new Error("integrity");
  } catch (error) {
    // **Its own `try`, because this one runs on a handle that has already
    // misbehaved.** A throw here would replace the closed failure union with an
    // exception, so a member holding a damaged copy would be told something
    // generic went wrong rather than that the copy is damaged.
    try {
      handle?.close();
    } catch {
      // Nothing to do with it. The tab holds the heap until it is closed, which
      // is the outcome this whole branch exists to avoid and cannot then have.
    }
    // The engine says which of the two it was, and the two need different
    // sentences: "that is not a Calibre library" against "that copy was taken
    // while something was writing". `SQLITE_NOTADB` reports the first with this
    // exact phrase, and everything else at this point is a file that opened and
    // then disagreed with itself.
    const message = error instanceof Error ? error.message : "";
    return {
      ok: false,
      failure: message.includes("not a database")
        ? "not-a-database"
        : "damaged",
    };
  }

  return { ok: true, database: wrap(handle) };
}

/**
 * The same, from a file a member picked.
 *
 * **The size is refused before the bytes are read, not after.** `openSqlite`
 * bounds what reaches WebAssembly memory, which is one copy too late: reading a
 * two gigabyte file into an `ArrayBuffer` to then decline it has already spent
 * the memory the bound exists to protect.
 */
export async function openSqliteFile(
  file: File,
  options: { readonly engine?: SqliteEngineLoader } = {},
): Promise<SqliteReading> {
  if (file.size > MAX_DATABASE_BYTES) {
    return { ok: false, failure: "too-large" };
  }
  return openSqlite(new Uint8Array(await file.arrayBuffer()), options);
}

function wrap(handle: SqlJsDatabase): SqliteDatabase {
  let open = true;
  return {
    query(sql, params = []) {
      if (!open) throw new Error("query on a closed database");
      let results;
      try {
        results = handle.exec(sql, [...params]);
      } catch {
        // A missing table or column, or a page the file got wrong. The caller
        // asked whether the file carries something; the answer is that it does
        // not.
        return [];
      }
      // `exec` answers one result set per statement and none at all for a
      // statement that matched nothing. Only the first is read: every caller
      // here sends one statement, and reading further would silently accept a
      // second one somebody appended.
      const first = results[0];
      if (first === undefined) return [];
      const { columns, values } = first;
      return values.slice(0, MAX_ROWS_PER_QUERY).map((row) => {
        const record: Record<string, SqlValue | undefined> = {};
        columns.forEach((column, index) => {
          const cell = row[index];
          record[column] = cell === undefined ? undefined : boundCell(cell);
        });
        return record;
      });
    },
    close() {
      if (!open) return;
      open = false;
      handle.close();
    },
  };
}
