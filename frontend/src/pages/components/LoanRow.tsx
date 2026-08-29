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
              {loan.due_at
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
