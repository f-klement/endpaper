/**
 * Writing a shelf somebody already had, one book at a time.
 *
 * The step every import on this page shares once its file has been read and
 * reported on: a Calibre library and a store's are the same nine hundred
 * requests, and the reasoning below was written for the first of them and holds
 * for every other. A second copy of it would be a second place for the
 * concurrency rule and the 409 rule to drift.
 *
 * **What it deliberately does not own** is what to write. Each hook maps its
 * own records to `BookCreate` through `./types`, so the reader's shape stays
 * the reader's and this walks bodies.
 */

import type { BookCreate } from "../../../api/generated/model";

/** How far through a step that walks nine hundred things this one is. */
export interface ImportProgress {
  readonly done: number;
  readonly total: number;
}

/** What one book that could not be added was, and what the server answered. */
export interface ImportFailureRow {
  readonly title: string;
  /** The HTTP status, or `null` when the request never got one. */
  readonly status: number | null;
}

export interface ImportOutcome {
  readonly added: number;
  readonly failures: readonly ImportFailureRow[];
  /** True when the member stopped it, so a short count is not read as damage. */
  readonly stopped: boolean;
}

export interface WriteHooks {
  /** One request. Rejects for anything the server refused. */
  post: (body: BookCreate) => Promise<unknown>;
  onProgress: (progress: ImportProgress) => void;
  /**
   * Whether the member has pressed stop, asked between requests.
   *
   * A function rather than a value: the loop reads it after every request, and
   * a boolean captured when the loop started would say `false` for ever.
   */
  stopped: () => boolean;
}

/**
 * Add them, one request each.
 *
 * **Sequential rather than `Promise.all`**, for the reason the rapid queue
 * states: nine hundred concurrent requests against one SQLite writer is not a
 * faster import, and a duplicate ISBN answering 409 has to be attributable to a
 * book.
 *
 * **A failure is kept with its reason rather than counted.** "Sixty could not
 * be added" after a nine hundred book import is unrecoverable: nothing says
 * which sixty.
 */
export async function writeBooks(
  bodies: readonly BookCreate[],
  hooks: WriteHooks,
): Promise<ImportOutcome> {
  const failures: ImportFailureRow[] = [];
  let added = 0;

  hooks.onProgress({ done: 0, total: bodies.length });
  for (const [position, body] of bodies.entries()) {
    if (hooks.stopped()) break;
    try {
      await hooks.post(body);
      added += 1;
    } catch (thrown) {
      failures.push({ title: body.title, status: statusOf(thrown) });
    }
    hooks.onProgress({ done: position + 1, total: bodies.length });
  }

  return { added, failures, stopped: hooks.stopped() };
}

/**
 * What the server answered for one book, or `null` when it never answered.
 *
 * The status rather than the sentence, and the sentence is built where the
 * catalogue is: a duplicate ISBN is the ordinary outcome of importing the same
 * library twice and is worth its own words, where everything else is one line
 * saying which book did not arrive.
 */
export function statusOf(thrown: unknown): number | null {
  const status = (thrown as { status?: unknown } | null)?.status;
  return typeof status === "number" ? status : null;
}

/**
 * What the server answers for a book whose ISBN is already on the shelf.
 *
 * Named because it is the ordinary outcome rather than an error: importing the
 * same library twice is what a second run is, and a member who reads "could not
 * be added" for six hundred books believes something broke.
 */
export const DUPLICATE_STATUS = 409;

/**
 * How many failures a card lists.
 *
 * Every failure is kept in the outcome, and a list of nine hundred is not a
 * list anybody reads. The count above it is the whole number.
 */
export const FAILURES_SHOWN = 20;
