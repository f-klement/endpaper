/**
 * Whether a book is still out, and the date it came back.
 *
 * **The server owns this rule and `LoanOut` carries no derived flag for it.**
 * `backend/lending.py` decides that a loan is open when it holds no return
 * stamp, and `backend/tests/test_house_rules.py` narrows which backend modules
 * may name that column at all. The payload ships the column, so a browser
 * reading one loan has to apply the rule itself, and this module is where that
 * happens.
 *
 * **It is one loan, not one book, and the difference is where the server does
 * answer.** A book payload's `active_loan` is filled from the open loan door,
 * so its presence is the server saying the book is out, and this module is not
 * a second opinion on that. It answers whether the loan in hand is closed.
 *
 * **Every branch on a card reads the one answer.** Whether the book is back
 * decides the dimming, the deadline line, the return date, the days out line
 * and the return button, and a screen deriving it per site is a screen that
 * can call the same row open in one place and closed in another with nothing
 * to say which is right.
 *
 * **The verdict and the date come together** rather than as a predicate,
 * because the site that prints the date needs the value, and a predicate would
 * have sent it back to the column for it. Two facts off one read cannot
 * disagree.
 *
 * `tests/lib/loanState.test.ts` holds the rule that nothing else under `src`
 * names the column, which is the browser's half of the backend's own.
 *
 * `overdueText` words the overdue badge, the other answer a loan card reads off
 * one loan, so the card holds markup and this module holds what it says.
 */

import type { LoanOut, Locale } from "../api/generated/model";
import type { Translate } from "../i18n";
import { numericDate } from "./date";

/** A loan as a screen reads it. */
export interface LoanState {
  /** The book has not come back. */
  readonly isOpen: boolean;
  /**
   * When the book came back, or null while it is still out.
   *
   * **Null or a non empty string, never anything else falsy**, so a caller may
   * render it behind `&&` without checking first. Falsy is not invisible
   * there: React prints `0`, `-0` and `0n` as "0" and `NaN` as "NaN", while
   * null renders nothing.
   */
  readonly returnedOn: string | null;
}

/**
 * Read a loan's return state off the payload, once.
 *
 * **`||` and not `??`, and the difference is every falsy value that is not
 * null.** The column is a nullable datetime, so nothing the server serialises
 * is `""` and the two spellings agree over the declared type. Where they
 * differ, truthiness leaves the loan out rather than drawing the card as
 * returned and then handing an unusable value to a date formatter, and it is
 * what lets `returnedOn` promise something a caller can print.
 */
export function loanState(loan: LoanOut): LoanState {
  const returnedOn = loan.returned_at || null;
  return { isOpen: returnedOn === null, returnedOn };
}

/**
 * What an overdue loan's badge says.
 *
 * **The day count leads, because it tells a week from a year at a glance, and
 * the date stays beside it**: it is what a person writing to a borrower needs,
 * and the deadline line a card draws for an open loan is gated on the loan not
 * being overdue, so the badge is the only place an overdue row can show it.
 *
 * The count is 0 within the first day past the deadline, which says nothing,
 * so the date carries that case on its own, and the bare word carries a loan
 * flagged with no date at all. `days_overdue` is defaulted because the
 * generated type makes it optional; the server fills it on every loan a list
 * returns.
 */
export function overdueText(
  loan: LoanOut,
  locale: Locale,
  t: Translate,
): string {
  if (!loan.due_at) return t("loans.overdue");
  const date = numericDate(loan.due_at, locale);
  const days = loan.days_overdue ?? 0;
  if (days > 0)
    return t(
      days === 1 ? "loans.overdueByOneDaySince" : "loans.overdueByDaysSince",
      { days, date },
    );
  return t("loans.overdueSince", { date });
}
