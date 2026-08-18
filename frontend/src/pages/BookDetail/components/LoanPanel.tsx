import { useState } from "react";

import type { BookOut, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface LoanPanelProps {
  book: BookOut;
  members: UserOut[];
  isBusy: boolean;
  onLend: (toUserId: number, dueAt: string | null) => void;
  onMarkReturned: (loanId: number) => void;
}

/** Lend the book, or record its return. Used only by BookDetail. */
export default function LoanPanel({
  book,
  members,
  isBusy,
  onLend,
  onMarkReturned,
}: LoanPanelProps) {
  const { t } = useTranslation();
  const [target, setTarget] = useState("");
  const [dueAt, setDueAt] = useState("");

  return (
    <div>
      <p className="text-sm font-semibold text-gray-700 mb-2 dark:text-gray-200">
        {t("loans.management")}
      </p>

      {book.active_loan ? (
        <button
          onClick={() => onMarkReturned(book.active_loan!.id)}
          disabled={isBusy}
          className="w-full py-2.5 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300 text-white rounded-lg text-sm font-semibold transition-colors"
        >
          {isBusy ? t("loans.updating") : t("loans.markAsReturned")}
        </button>
      ) : (
        <div className="flex gap-2">
          <select
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            aria-label={t("loans.loanToLabel")}
            className="flex-1 px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-white dark:border-gray-700 dark:bg-gray-900"
          >
            <option value="">{t("loans.loanTo")}</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.username}
              </option>
            ))}
          </select>
          <button
            onClick={() =>
              // A date input gives a bare date; the API wants a timestamp. End
              // of day rather than midnight, or a book due "today" is overdue
              // from the moment it is lent.
              onLend(Number(target), dueAt ? `${dueAt}T23:59:59` : null)
            }
            disabled={!target || isBusy}
            className="px-4 py-2.5 bg-sky-500 hover:bg-sky-600 disabled:bg-sky-300 text-white rounded-lg text-sm font-semibold transition-colors"
          >
            {t("loans.loanButton")}
          </button>
        </div>
      )}

      {!book.active_loan && (
        <div className="mt-2">
          <label
            htmlFor="loan-due"
            className="block text-xs text-gray-500 mb-1 dark:text-gray-400"
          >
            {t("loans.dueDate")}
          </label>
          <input
            id="loan-due"
            type="date"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 dark:border-gray-700"
          />
        </div>
      )}
    </div>
  );
}
