import { Link } from "react-router-dom";

import type { LoanOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import { Button } from "../../components";
import CoverImage from "./CoverImage";

interface LoanRowProps {
  loan: LoanOut;
  isReturning: boolean;
  onMarkReturned: (loanId: number) => void;
}

/**
 * One lending record. Presentational, drawn by the loans page and the overdue
 * page (#102), which is why it lives here rather than in either of them.
 *
 * **An overdue row is marked twice, and neither mark is colour alone.** The
 * whole card is outlined in `danger-500` with the left side four times as
 * thick, and the badge below the borrower names the date the book was due. A
 * reader who cannot tell the two frames apart still reads the badge.
 *
 * `border-l-4 border-danger-500` reads as a left bar and is not one: the width
 * applies to the left, the colour applies to all four sides. Calling it an edge
 * bar is what the comment said before, and it would have sent somebody looking
 * for the three sides they thought were missing.
 *
 * **The overdue badge can wrap to two lines and cannot overflow sideways.**
 * It carries a day count and a date now, so it is the widest thing on the
 * card: "14 days overdue, since 21/08/2026" in English. The bound is readable
 * off the classes rather than needing a pixel measurement: the badge is
 * `inline-block` with no `whitespace-nowrap`, inside a `flex-1 min-w-0`
 * column, so the worst case is a pill on two lines and never a card that
 * scrolls.
 *
 * **The two day counts come from the server, not from the dates beside them.**
 * `days_out` and `days_overdue` are computed in `backend/lending.py`, which is
 * also what the overdue digest reads, so a row here and a reminder sent to a
 * chat cannot disagree about the same loan. Recomputing them from `loaned_at`
 * in the browser would put a second definition of a whole day in a second
 * timezone.
 *
 * `danger-500` rather than the `danger-300` / `danger-700` pair this card
 * carried before, and the reason is measured: on the default palette that pair
 * is **1.89:1** on the light card and **2.18:1** on the dark one, against the
 * 3.0 WCAG 1.4.11 asks of a non-text indicator. It was an edge nobody could
 * see doing the whole job of saying which loans to chase, which is the same
 * defect `OverdueBanner` records in its own dark border. `danger-500` measures
 * 4.70:1 and 4.51:1 on the same two surfaces, and it is a pairing
 * `frontend/tests/theme/palettes.test.ts` already asserts at 4.5 for **every**
 * palette in **both** modes (`danger-500 text on the card`), so a palette added
 * later cannot quietly drop it below the floor.
 */
export default function LoanRow({
  loan,
  isReturning,
  onMarkReturned,
}: LoanRowProps) {
  const { t, locale } = useTranslation();
  const isReturned = Boolean(loan.returned_at);
  // Defaulted because both fields are optional in the generated type: they
  // carry a server side default, so orval emits them as `number | undefined`
  // and TypeScript will not let either be compared without this.
  //
  // **Not because of `serialisation.loan_summary`**, which was the reason
  // written here first and is a real omission on a payload this component
  // never sees: `active_loan` is rendered by the book detail page, and every
  // loan reaching `LoanRow` comes from the loans list or the overdue page,
  // where both fields are filled. Zero renders nothing either way.
  const daysOut = loan.days_out ?? 0;
  const daysOverdue = loan.days_overdue ?? 0;

  return (
    <div
      className={`card p-4 ${
        isReturned
          ? "opacity-60"
          : loan.is_overdue
            ? "border-l-4 border-danger-500 dark:border-danger-500"
            : "border-amber-200 dark:border-amber-900/70"
      }`}
    >
      <div className="flex gap-3">
        <Link to={`/book/${loan.book_id}`} className="shrink-0">
          <CoverImage
            src={loan.book?.cover_url}
            alt={loan.book?.title ?? ""}
            className="w-12 h-16 object-cover rounded shadow-sm bg-accent-100"
          />
        </Link>

        <div className="flex-1 min-w-0">
          <Link to={`/book/${loan.book_id}`}>
            <h3 className="font-semibold text-sm leading-tight line-clamp-1 hover:text-accent-700 dark:hover:text-accent-300">
              {loan.book?.title}
            </h3>
          </Link>
          {loan.book?.author && (
            <p className="text-xs text-paper-600 truncate dark:text-paper-400">
              {loan.book.author}
            </p>
          )}
          <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
            {/* Two whole phrases, not one with the borrower swapped in: German
                does not keep the English word order, and a borrower with no
                account here is worth saying rather than leaving to look like a
                member nobody recognises.

                Branching on the name rather than on `loaned_to`, which is a
                relationship and is only populated when the caller joined it.
                The name is the column the database constraint governs. */}
            {loan.loaned_to_name
              ? t("loans.loanedToExternalBy", {
                  name: loan.loaned_to_name,
                  by: loan.loaned_by?.username ?? "",
                })
              : t("loans.loanedToBy", {
                  to: loan.loaned_to?.username ?? "",
                  by: loan.loaned_by?.username ?? "",
                })}
          </p>
          {loan.is_overdue && (
            <span className="inline-block mt-1 text-xs font-medium text-danger-700 bg-danger-100 border border-danger-100 px-2 py-0.5 rounded-full dark:bg-danger-700 dark:border-danger-700 dark:text-danger-100">
              {/* The day count leads, because it is what tells a week from a
                  year at a glance, and the date stays beside it: it is what a
                  person writing to a borrower needs, and the only other place
                  it appears is the `dueOn` line below, which is gated on the
                  loan not being overdue. Leading with the count alone took the
                  deadline off every overdue row past its first day.

                  The count is 0 within the first day past the deadline, which
                  says nothing, so the date carries that case on its own, and
                  the bare word carries a loan flagged with no date at all. */}
              {daysOverdue > 0 && loan.due_at
                ? t(
                    daysOverdue === 1
                      ? "loans.overdueByOneDaySince"
                      : "loans.overdueByDaysSince",
                    {
                      days: daysOverdue,
                      date: new Date(loan.due_at).toLocaleDateString(locale),
                    },
                  )
                : loan.due_at
                  ? t("loans.overdueSince", {
                      date: new Date(loan.due_at).toLocaleDateString(locale),
                    })
                  : t("loans.overdue")}
            </span>
          )}
          {!loan.is_overdue && loan.due_at && !loan.returned_at && (
            <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
              {t("loans.dueOn", {
                date: new Date(loan.due_at).toLocaleDateString(locale),
              })}
            </p>
          )}
          {/* Every open loan, deadline or not. Most lending here has none, so
              a row that said only "overdue" or nothing at all left the common
              case with no answer to the question the page is for.

              Hidden on a returned loan, which reports the date it came back
              instead, and hidden at zero: a book lent this morning would
              otherwise read "Out for 0 days" beside today's date one line
              below. Zero is also what a loan read off a book payload carries,
              because `loan_summary` fills nothing dated, so the same guard
              keeps a defaulted field from rendering as a measurement. */}
          {!isReturned && daysOut > 0 && (
            <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
              {t(daysOut === 1 ? "loans.outForOne" : "loans.outFor", {
                days: daysOut,
              })}
            </p>
          )}
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {new Date(loan.loaned_at).toLocaleDateString(locale)}
            {loan.returned_at && (
              <span className="ml-2 text-green-800 dark:text-green-400">
                {t("loans.returnedOn", {
                  date: new Date(loan.returned_at).toLocaleDateString(locale),
                })}
              </span>
            )}
          </p>
        </div>
      </div>

      {!isReturned && (
        <Button
          variant="secondary"
          fullWidth
          className="mt-3"
          isLoading={isReturning}
          onClick={() => onMarkReturned(loan.id)}
        >
          {t("loans.markReturned")}
        </Button>
      )}
    </div>
  );
}
