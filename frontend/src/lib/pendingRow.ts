/**
 * Which rows a list is waiting on.
 *
 * A mutation's own `isPending` says that a write is out, not which row it is
 * for, and a row's spinner needs the second: marking every row while one is
 * out would stop a reader pressing the next one. So the answer is the id each
 * write was called with.
 */

/**
 * The `key` each call still out carries, so every row with a write out is
 * marked.
 *
 * `calls` is the variables of every call in flight, one entry per call, which
 * is what the mutation cache holds. A mutation hook's own `variables` is only
 * its latest call, so reading that would unmark a row the moment the same
 * action is pressed on another, and a second press on the first is refused by
 * the server as an error. A call whose variables carry no number under `key`
 * marks nothing.
 */
export function pendingRows(
  key: string,
  calls: readonly unknown[],
): ReadonlySet<number> {
  const rows = new Set<number>();
  for (const call of calls) {
    if (typeof call !== "object" || call === null) continue;
    const row: unknown = (call as Record<string, unknown>)[key];
    if (typeof row === "number") rows.add(row);
  }
  return rows;
}
