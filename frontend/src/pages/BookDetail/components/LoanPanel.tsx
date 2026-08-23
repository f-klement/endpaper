import { useEffect, useState } from "react";

import {
  LendingWillingness,
  type BookDetailsUpdate,
  type BookOut,
  type UserOut,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { LENDING_LABELS, LENDING_ORDER } from "../../types";

interface LoanPanelProps {
  book: BookOut;
  members: UserOut[];
  isBusy: boolean;
  /** Saving the willingness, which goes through the ordinary details PATCH. */
  isSavingDetails: boolean;
  onSaveLending: (fields: BookDetailsUpdate) => void;
  onLend: (
    borrower: Borrower,
    dueAt: string | null,
    acknowledgeNotLendable: boolean,
  ) => void;
  onMarkReturned: (loanId: number) => void;
}

// Built from the shared table rather than restated, so this panel and the
// card's fold out cannot call the same value two different things.
const WILLINGNESS: { value: LendingWillingness; label: MessageKey }[] =
  LENDING_ORDER.map((value) => ({ value, label: LENDING_LABELS[value] }));

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
  isSavingDetails,
  onSaveLending,
  onLend,
  onMarkReturned,
}: LoanPanelProps) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<Kind>("member");
  const [target, setTarget] = useState("");
  const [externalName, setExternalName] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  const isNeverLent = book.lending === LendingWillingness.never;

  // Untick when the book stops being one that needs the confirmation, and when
  // the loan completes. A checkbox left ticked from the last lend would make
  // the next one a single click again, which is the whole thing this guards.
  useEffect(() => {
    setAcknowledged(false);
  }, [book.id, book.lending, book.active_loan?.id]);

  const trimmedName = externalName.trim();
  const hasBorrower = kind === "member" ? Boolean(target) : Boolean(trimmedName);
  const canLend = hasBorrower && (!isNeverLent || acknowledged);

  function lend() {
    onLend(
      kind === "member"
        ? { kind: "member", userId: Number(target) }
        : { kind: "external", name: trimmedName },
      // A date input gives a bare date; the API wants a timestamp. End of day
      // rather than midnight, or a book due "today" is overdue from the moment
      // it is lent.
      dueAt ? `${dueAt}T23:59:59` : null,
      // Sent only when it is the answer to a question that was asked. The
      // server refuses a never-lent book without it, and accepts it as noise
      // on any other book.
      isNeverLent && acknowledged,
    );
  }

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-2 dark:text-paper-200">
        {t("loans.management")}
      </p>

      {/* The willingness lives here rather than in the copy panel, which is
          about the object. This is the panel it governs, and a rule the lend
          button enforces has to be visible from the lend button. */}
      <label className="block text-sm mb-3">
        <span className="block text-xs text-paper-600 mb-1 dark:text-paper-400">
          {t("lending.label")}
        </span>
        <select
          value={book.lending ?? ""}
          disabled={isSavingDetails}
          onChange={(event) =>
            onSaveLending({
              // Empty means "clear". The API tells absent from null apart, and
              // an empty string is neither.
              lending: (event.target.value ||
                null) as LendingWillingness | null,
            })
          }
          className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm bg-paper-0 dark:border-paper-700 dark:bg-paper-900"
        >
          <option value="">{t("lending.unset")}</option>
          {WILLINGNESS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.label)}
            </option>
          ))}
        </select>
      </label>

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
          {/* Refused once, not forbidden. A household lends a never-lent book
              to a sibling sometimes, and an app that will not let them record
              it gets the loan kept in somebody's head instead. So the button
              stays disabled until this is ticked, and the server asks for the
              same acknowledgement whatever the client does. */}
          {isNeverLent && (
            <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 dark:border-amber-500/40 dark:bg-amber-500/10">
              <p className="text-xs text-paper-700 dark:text-paper-200">
                {t("lending.neverWarning")}
              </p>
              <label className="mt-1.5 flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                  className="w-4 h-4 rounded border-paper-300 text-accent-600"
                />
                <span className="text-xs font-medium text-paper-700 dark:text-paper-200">
                  {t("lending.lendAnyway")}
                </span>
              </label>
            </div>
          )}

          {/* Two radios rather than a select with an "Other..." row: the second
              choice needs a text field, and a select cannot grow one. */}
          <fieldset className="mb-2">
            <legend className="text-xs text-paper-600 mb-1 dark:text-paper-400">
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
                    className="w-4 h-4 text-accent-600"
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
                className="flex-1 px-3 py-2.5 rounded-lg border border-paper-200 text-sm bg-paper-0 dark:border-paper-700 dark:bg-paper-900"
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
                className="flex-1 px-3 py-2.5 rounded-lg border border-paper-200 text-sm bg-paper-0 dark:border-paper-700 dark:bg-paper-900"
              />
            )}
            <button
              onClick={lend}
              disabled={!canLend || isBusy}
              className="px-4 py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-sm font-semibold transition-colors"
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
            className="block text-xs text-paper-600 mb-1 dark:text-paper-400"
          >
            {t("loans.dueDate")}
          </label>
          <input
            id="loan-due"
            type="date"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
          />
        </div>
      )}
    </div>
  );
}
