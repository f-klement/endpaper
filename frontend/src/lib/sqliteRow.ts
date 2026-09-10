/**
 * What a reader needs before it can believe a row a member's database handed it.
 *
 * **Neither the connection nor a library.** `sqlite.ts` owns opening a file and
 * saying why it could not; `calibre.ts` and `kobo.ts` own what a library means.
 * These four are what sits between: a value coerced out of an untrusted row,
 * and the columns a table actually has. They were declared in both readers, to
 * the character, and a third reader is coming.
 *
 * **The rule for what may join, because a helper module with no rule grows into
 * a second `sqlite.ts`.** A function belongs here when it answers a question
 * about a cell or a column without knowing what the value means: `text` does
 * not know it is a title. Anything that knows a table, a schema or a vendor
 * belongs to the reader that knows it. `kobo.ts::isTrue` is the boundary from
 * the other side: two spellings of a boolean is a fact about Kobo's firmware
 * rather than about SQLite, so it stays there and calls `text` from here.
 *
 * **Nothing here decides a failure.** A value these refuse is `null`, which is
 * a missing field, and a reader turns a missing field into a skipped book or a
 * thinner record on its own terms. A refusal reaching a member is
 * `SqliteFailure` and is `sqlite.ts`'s.
 *
 * **The bounds a cell has already passed are `sqlite.ts`'s**, and these run
 * after them: `MAX_CELL_BYTES` has already refused an absurd cell, so what
 * arrives here is a value worth looking at rather than one worth measuring.
 */

import type { SqliteDatabase } from "./sqlite";

/** A cell as a usable string, or `null` for one that is not. */
export function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * A cell as a whole number, or `null`.
 *
 * **A number and not a numeric string**, which is the exclusion worth stating
 * because SQLite does not promise a storage class: a column declared with text
 * affinity hands back `"188"` where another device hands back `188`, and this
 * reads the second only. Where a reader knows its vendor writes both, it says
 * so at its own site and reads across them there, which is what
 * `kobo.ts::isTrue` is.
 */
export function integer(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.trunc(value);
}

/** A cell as a number that may have a fraction, or `null`. */
export function decimal(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The columns one table has, so a schema that renamed one costs a field rather
 * than the file.
 *
 * Asked of the file rather than assumed, because a missing column and an empty
 * one are different answers and only one of them means "this is not the library
 * it claimed to be".
 *
 * **A table name cannot be a bound parameter in `PRAGMA`, so it is checked
 * rather than trusted.** Every name passed here today is a literal in a reader,
 * and a comment saying so is what stops holding the moment somebody passes a
 * name read out of `sqlite_master`, which came from a member supplied file.
 * The refusal answers an empty set, which a caller already handles: a table
 * whose columns are unknown is one it reads no field from.
 *
 * **The check is on the name and not on the answer**, which is the distinction
 * a test for it has to make: a rejected statement comes back from
 * `sqlite.ts::query` as an empty result too, so an empty set proves nothing.
 * What only this line produces is the statement never being asked, and
 * `tests/lib/sqliteRow.test.ts` asserts that against a database that records
 * what it was asked, with a quoted identifier as the second instrument: SQLite
 * answers `PRAGMA table_info("content")` happily, so a reader without this
 * hands back columns where this one hands back nothing.
 */
export function columnsIn(db: SqliteDatabase, table: string): Set<string> {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(table)) return new Set();
  const rows = db.query(`PRAGMA table_info(${table})`);
  return new Set(
    rows.map((row) => text(row["name"])).filter((name) => name !== null),
  );
}
