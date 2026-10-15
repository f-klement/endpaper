import { BookFormat } from "../../api/generated/model";

/**
 * Whether a copy is asked for rather than lent: an ebook always, an audiobook
 * only when it carries a digital reference, since the CSV import files an
 * audio CD under that format.
 *
 * The backend's `lending.is_requested_not_lent` is the rule and refuses a loan
 * on such a copy; this mirrors it so the page offers the request instead of a
 * lend button the server would refuse. Both sides have a test walking every
 * format through it, which is what holds the two together.
 */
export function isRequestedNotLent(
  format: BookFormat | null | undefined,
  hasFile: boolean,
): boolean {
  if (format === BookFormat.ebook) return true;
  return format === BookFormat.audiobook && hasFile;
}
