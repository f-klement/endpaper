import { Link } from "react-router-dom";

import type { LoanOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

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
      className={`bg-white rounded-xl border shadow-sm p-4 ${
        isReturned
          ? "border-gray-100 opacity-60"
          : loan.is_overdue
            ? "border-red-200"
            : "border-orange-100"
      }`}
    >
      <div className="flex gap-3">
        <Link to={`/book/${loan.book_id}`} className="shrink-0">
          {loan.book?.cover_url ? (
            <img
              src={loan.book.cover_url}
              alt={loan.book.title}
              className="w-12 h-16 object-cover rounded shadow-sm"
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
          ) : (
            <div className="w-12 h-16 bg-sky-100 rounded flex items-center justify-center text-xl">
              📖
            </div>
          )}
        </Link>

        <div className="flex-1 min-w-0">
          <Link to={`/book/${loan.book_id}`}>
            <h3 className="font-semibold text-sm leading-tight line-clamp-1 hover:text-sky-600">
              {loan.book?.title}
            </h3>
          </Link>
          {loan.book?.author && (
            <p className="text-xs text-gray-400 truncate dark:text-gray-500">
              {loan.book.author}
            </p>
          )}
          <p className="text-xs text-gray-500 mt-1 dark:text-gray-400">
            {t("loans.loanedToBy", {
              to: loan.loaned_to?.username ?? "",
              by: loan.loaned_by?.username ?? "",
            })}
          </p>
          {loan.is_overdue && (
            <span className="inline-block mt-1 text-xs font-medium text-red-700 bg-red-50 border border-red-100 px-2 py-0.5 rounded-full dark:bg-red-950 dark:border-red-900">
              {loan.due_at
                ? t("loans.overdueSince", {
                    date: new Date(loan.due_at).toLocaleDateString(locale),
                  })
                : t("loans.overdue")}
            </span>
          )}
          {!loan.is_overdue && loan.due_at && !loan.returned_at && (
            <p className="text-xs text-gray-500 mt-1 dark:text-gray-400">
              {t("loans.dueOn", {
                date: new Date(loan.due_at).toLocaleDateString(locale),
              })}
            </p>
          )}
          <p className="text-xs text-gray-400 dark:text-gray-500">
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
        <button
          onClick={() => onMarkReturned(loan.id)}
          disabled={isReturning}
          className="mt-3 w-full py-2 border border-orange-200 text-orange-600 hover:bg-orange-50 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 dark:text-orange-400"
        >
          {isReturning ? t("loans.updating") : t("loans.markReturned")}
        </button>
      )}
    </div>
  );
}
