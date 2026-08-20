import { Link } from "react-router-dom";

import type { LoanOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { Button } from "../../../components";
import { CoverImage } from "../../components";

interface LoanRowProps {
  loan: LoanOut;
  isReturning: boolean;
  onMarkReturned: (loanId: number) => void;
}

/** One lending record. Presentational, used only by LoansPage. */
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
            ? "border-bloom-300 dark:border-bloom-700"
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
            <h3 className="font-semibold text-sm leading-tight line-clamp-1 hover:text-accent-700">
              {loan.book?.title}
            </h3>
          </Link>
          {loan.book?.author && (
            <p className="text-xs text-paper-400 truncate dark:text-paper-500">
              {loan.book.author}
            </p>
          )}
          <p className="text-xs text-paper-500 mt-1 dark:text-paper-400">
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
            <span className="inline-block mt-1 text-xs font-medium text-bloom-700 bg-bloom-100 border border-bloom-100 px-2 py-0.5 rounded-full dark:bg-bloom-700 dark:border-bloom-700">
              {loan.due_at
                ? t("loans.overdueSince", {
                    date: new Date(loan.due_at).toLocaleDateString(locale),
                  })
                : t("loans.overdue")}
            </span>
          )}
          {!loan.is_overdue && loan.due_at && !loan.returned_at && (
            <p className="text-xs text-paper-500 mt-1 dark:text-paper-400">
              {t("loans.dueOn", {
                date: new Date(loan.due_at).toLocaleDateString(locale),
              })}
            </p>
          )}
          <p className="text-xs text-paper-400 dark:text-paper-500">
            {new Date(loan.loaned_at).toLocaleDateString(locale)}
            {loan.returned_at && (
              <span className="ml-2 text-green-600 dark:text-green-400">
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
