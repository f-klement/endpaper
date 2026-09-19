/**
 * Writing a shelf of books, one request at a time.
 *
 * **The loop three screens share**, and it is one loop because the rules it
 * holds are one set of rules: a Calibre library, a store's export and a rapid
 * scan are the same nine hundred requests against the same single writer. Each
 * of them said so in its own words before this module existed, in two page
 * folders that could not read each other, and the one that said it best was the
 * one with no way to stop.
 *
 * **What it deliberately does not own is the request.** `post` is the caller's,
 * so what a record becomes on the wire stays where the record is understood,
 * and this module names no endpoint at all. That is also what keeps it here:
 * `tests/houseRules.test.ts` refuses any module outside a `hooks.ts` that
 * reaches the API directly, and a loop that takes its write as a callback is
 * free to live where every page can reach it.
 *
 * **One item is one unit of work, and `post` may take more than one request to
 * do it.** The rapid scan writes a book and then says where its file is, which
 * is two requests and one item: what this loop promises is that no item starts
 * while another is running, never that an item is one request.
 */

/** How far through a walk of nine hundred things this run has got. */
export interface BulkProgress {
  readonly done: number;
  readonly total: number;
}

/**
 * One item that could not be written, and what the attempt threw.
 *
 * **The item rather than a row**, because the two callers show different
 * things: an import card lists a title and the status the server answered, and
 * the scanner writes the whole queue row back with its reason on it. A shared
 * row shape would be the narrower of those two, and the reason a failure is
 * kept at all is that a count is unrecoverable.
 */
export interface BulkFailure<T> {
  readonly item: T;
  readonly thrown: unknown;
}

export interface BulkOutcome<T> {
  readonly added: number;
  readonly failures: readonly BulkFailure<T>[];
  /**
   * The items the run reached, which after a stop is not the items it was
   * given.
   *
   * **What a caller prunes by.** A queue that clears the rows it offered clears
   * rows it never attempted the moment a stop exists, and those are exactly the
   * books a member stopped in order to keep. Equal to the input for a run that
   * was not stopped, which is why nothing noticed before there was a stop.
   */
  readonly attempted: readonly T[];
  /**
   * True when the member stopped it **and** that ended it early, so a short
   * count is not read as damage.
   *
   * Both halves, because a stop pressed while the last item is in flight is a
   * run that wrote everything it was given: see the return statement, which
   * names what each half alone would accept.
   */
  readonly stopped: boolean;
}

export interface BulkHooks<T> {
  /** One item, written. Rejects for anything the server refused. */
  post: (item: T) => Promise<unknown>;
  onProgress: (progress: BulkProgress) => void;
  /**
   * Whether the member has pressed stop, asked between items.
   *
   * A function rather than a value: the loop reads it after every item, and a
   * boolean captured when the loop started would say `false` for ever.
   *
   * **Not optional, and a caller that cannot answer it does not compile.** A
   * member who can halt a nine hundred book import and cannot halt a three
   * hundred book scan is the defect this module was cut out for.
   */
  stopped: () => boolean;
}

/**
 * Write them, one at a time, until they run out or the member stops.
 *
 * **Sequential rather than `Promise.all`.** Nine hundred concurrent requests
 * against one SQLite writer is not a faster import, and a duplicate ISBN
 * answering 409 has to be attributable to a book.
 *
 * **A failure is kept with the item it was, never counted.** "Sixty could not
 * be added" after a nine hundred book import is unrecoverable: nothing says
 * which sixty, and the queue that knew has just been cleared.
 *
 * **The stop is read between items rather than inside one.** An item already
 * in flight finishes, which is what makes `attempted` a prefix of the input and
 * lets a caller prune exactly what it reached.
 */
export async function writeOneAtATime<T>(
  items: readonly T[],
  hooks: BulkHooks<T>,
): Promise<BulkOutcome<T>> {
  const failures: BulkFailure<T>[] = [];
  const attempted: T[] = [];
  let added = 0;

  hooks.onProgress({ done: 0, total: items.length });
  for (const [position, item] of items.entries()) {
    if (hooks.stopped()) break;
    attempted.push(item);
    try {
      await hooks.post(item);
      added += 1;
    } catch (thrown) {
      failures.push({ item, thrown });
    }
    hooks.onProgress({ done: position + 1, total: items.length });
  }

  // **Both conjuncts, and each alone is a different wrong answer.**
  //
  // `hooks.stopped()` alone reports a full shelf as stopped: a member who
  // presses stop while the last item is in flight gets every item written and
  // every row pruned, under a sentence saying what it did not reach is still
  // in the queue, over an empty queue.
  //
  // `attempted.length < items.length` alone names a member as the reason for
  // any other way out of this loop. There is one way out today and it is the
  // stop, so the two are equal now and the next break condition added here
  // would inherit the wrong word for itself.
  return {
    added,
    failures,
    attempted,
    stopped: hooks.stopped() && attempted.length < items.length,
  };
}
