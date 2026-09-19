/**
 * What an import on this page makes of the shared write.
 *
 * The loop itself is `lib/bulkWrite.ts`, which the rapid scanner walks too.
 * What is left here is this page's own vocabulary: a failure is a title and the
 * status the server answered, because that is what an import card lists, and
 * `DUPLICATE_STATUS` is the one status worth its own sentence.
 *
 * **What it deliberately does not own** is what to write. Each hook maps its
 * own records to `BookCreate` through `./types`, so the reader's shape stays
 * the reader's and this walks bodies.
 */

import {
  writeOneAtATime,
  type BulkHooks,
  type BulkProgress,
} from "../../../lib/bulkWrite";
import type { BookCreate } from "../../../api/generated/model";

/** How far through a step that walks nine hundred things this one is. */
export type ImportProgress = BulkProgress;

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

/** The shared loop's hooks, over the bodies this page sends. */
export type WriteHooks = BulkHooks<BookCreate>;

/**
 * Add them, one request each.
 *
 * **A failure is kept with its reason rather than counted.** "Sixty could not
 * be added" after a nine hundred book import is unrecoverable: nothing says
 * which sixty.
 *
 * **The items it reached are dropped here rather than carried on.** A stopped
 * import sends every book again on the next press and the ones already there
 * answer 409, which `hooks.ts` records as the decision it is; the queue that
 * has to prune by what was walked is the scanner's.
 */
export async function writeBooks(
  bodies: readonly BookCreate[],
  hooks: WriteHooks,
): Promise<ImportOutcome> {
  const outcome = await writeOneAtATime(bodies, hooks);
  return {
    added: outcome.added,
    failures: outcome.failures.map(({ item, thrown }) => ({
      title: item.title,
      status: statusOf(thrown),
    })),
    stopped: outcome.stopped,
  };
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
