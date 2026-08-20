import { useState } from "react";

import type { BookOut, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface LoanPanelProps {
  book: BookOut;
  members: UserOut[];
  isBusy: boolean;
  onLend: (borrower: Borrower, dueAt: string | null) => void;
  onMarkReturned: (loanId: number) => void;
}

/**
 * Who the book is going to.
 *
 * A union rather than two optional fields, because the API accepts exactly one
 * of the two and rejects both with a 422. Making that a compile-time choice
 * here means the impossible request cannot be assembled.
 */
export type Borrower =
  | { kind: "member"; userId: number }
  | { kind: "external"; name: string };

type Kind = Borrower["kind"];

/** Lend the book, or record its return. Used only by BookDetail. */
export default function LoanPanel({
  book,
  members,
  isBusy,
  onLend,
  onMarkReturned,
}: LoanPanelProps) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<Kind>("member");
  const [target, setTarget] = useState("");
  const [externalName, setExternalName] = useState("");
  const [dueAt, setDueAt] = useState("");

  const trimmedName = externalName.trim();
  const canLend = kind === "member" ? Boolean(target) : Boolean(trimmedName);

  function lend() {
    onLend(
      kind === "member"
        ? { kind: "member", userId: Number(target) }
        : { kind: "external", name: trimmedName },
      // A date input gives a bare date; the API wants a timestamp. End of day
      // rather than midnight, or a book due "today" is overdue from the moment
      // it is lent.
      dueAt ? `${dueAt}T23:59:59` : null,
    );
  }

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-2 dark:text-paper-200">
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
        <>
          {/* Two radios rather than a select with an "Other..." row: the second
              choice needs a text field, and a select cannot grow one. */}
          <fieldset className="mb-2">
            <legend className="text-xs text-paper-500 mb-1 dark:text-paper-400">
              {t("loans.borrowerKind")}
            </legend>
            <div className="flex gap-4">
              {(["member", "external"] as const).map((option) => (
                <label
                  key={option}
                  className="flex items-center gap-1.5 text-sm text-paper-700 cursor-pointer dark:text-paper-200"
                >
                  <input
                    type="radio"
                    name="borrower-kind"
                    value={option}
                    checked={kind === option}
                    onChange={() => setKind(option)}
                    className="w-4 h-4 text-accent-600 focus:ring-accent-400"
                  />
                  {option === "member"
                    ? t("loans.borrowerMember")
                    : t("loans.borrowerExternal")}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex gap-2">
            {kind === "member" ? (
              <select
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                aria-label={t("loans.loanToLabel")}
                className="flex-1 px-3 py-2.5 rounded-lg border border-paper-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-400 bg-white dark:border-paper-700 dark:bg-paper-900"
              >
                <option value="">{t("loans.loanTo")}</option>
                {members.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.username}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={externalName}
                maxLength={120}
                onChange={(event) => setExternalName(event.target.value)}
                aria-label={t("loans.externalNameLabel")}
                placeholder={t("loans.externalNamePlaceholder")}
                className="flex-1 px-3 py-2.5 rounded-lg border border-paper-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-400 bg-white dark:border-paper-700 dark:bg-paper-900"
              />
            )}
            <button
              onClick={lend}
              disabled={!canLend || isBusy}
              className="px-4 py-2.5 bg-accent-600 hover:bg-accent-700 disabled:bg-accent-300 text-white rounded-lg text-sm font-semibold transition-colors"
            >
              {t("loans.loanButton")}
            </button>
          </div>
        </>
      )}

      {!book.active_loan && (
        <div className="mt-2">
          <label
            htmlFor="loan-due"
            className="block text-xs text-paper-500 mb-1 dark:text-paper-400"
          >
            {t("loans.dueDate")}
          </label>
          <input
            id="loan-due"
            type="date"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm focus:outline-none focus:ring-2 focus:ring-accent-400 dark:border-paper-700"
          />
        </div>
      )}
    </div>
  );
}
