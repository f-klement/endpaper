import { useEffect, useState } from "react";

import {
  LendingWillingness,
  type BookDetailsUpdate,
  type BookOut,
  type UserOut,
} from "../../../api/generated/model";
import { useTranslation, type MessageKey } from "../../../i18n";
import { endOfDayInstant } from "../../../lib/date";
import { LENDING_LABELS, LENDING_ORDER } from "../../types";
import PatronPicker, { type PickedPatron } from "./PatronPicker";

interface LoanPanelProps {
  book: BookOut;
  members: UserOut[];
  /**
   * Whether the reader may lend to a registered patron, which is an admin
   * alone: finding one reads people's contact details. A member is offered
   * the other two kinds of borrower and never sees the patron doors.
   */
  canLendToPatron: boolean;
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
 * A union rather than three optional fields, because the API accepts exactly
 * one of them and rejects more with a 422. Making that a compile-time choice
 * here means the impossible request cannot be assembled.
 */
export type Borrower =
  | { kind: "member"; userId: number }
  | { kind: "external"; name: string }
  | { kind: "patron"; patronId: number };

type Kind = Borrower["kind"];

/** The borrower the form names, or null while the chosen kind is unanswered. */
function chosenBorrower(
  kind: Kind,
  target: string,
  name: string,
  picked: PickedPatron | null,
): Borrower | null {
  if (kind === "member") {
    return target ? { kind: "member", userId: Number(target) } : null;
  }
  if (kind === "external") return name ? { kind: "external", name } : null;
  return picked ? { kind: "patron", patronId: picked.patron.id } : null;
}

/**
 * The lend form's state, kept by the panel rather than by the form, so a
 * borrower and a due date picked before a loan are still there once it is
 * returned.
 */
function useLendForm(book: BookOut, onLend: LoanPanelProps["onLend"]) {
  const [kind, setKind] = useState<Kind>("member");
  const [target, setTarget] = useState("");
  const [externalName, setExternalName] = useState("");
  const [picked, setPicked] = useState<PickedPatron | null>(null);
  const [dueAt, setDueAt] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  const isNeverLent = book.lending === LendingWillingness.never;

  // Untick when the book stops being one that needs the confirmation, and when
  // the loan completes. A checkbox left ticked from the last lend would make
  // the next one a single click again, which is the whole thing this guards.
  useEffect(() => {
    setAcknowledged(false);
  }, [book.id, book.lending, book.active_loan?.id]);

  const borrower = chosenBorrower(kind, target, externalName.trim(), picked);
  const canLend = borrower !== null && (!isNeverLent || acknowledged);

  function lend() {
    if (borrower === null) return;
    onLend(
      borrower,
      // End of the picked day **where the member is**, as an instant.
      // `lib/date.ts::endOfDayInstant` carries why the offset is on it: sent
      // without one the server reads this wall clock as a UTC clock and the
      // deadline lands late by the viewer's offset.
      endOfDayInstant(dueAt),
      // Sent only when it is the answer to a question that was asked. The
      // server refuses a never-lent book without it, and accepts it as noise
      // on any other book.
      isNeverLent && acknowledged,
    );
  }

  return {
    kind,
    setKind,
    target,
    setTarget,
    externalName,
    setExternalName,
    picked,
    setPicked,
    dueAt,
    setDueAt,
    acknowledged,
    setAcknowledged,
    isNeverLent,
    canLend,
    lend,
  };
}

type LendForm = ReturnType<typeof useLendForm>;

const MEMBER_KINDS: readonly Kind[] = ["member", "external"];
const PATRON_KINDS: readonly Kind[] = ["member", "external", "patron"];

const KIND_LABELS: Record<Kind, MessageKey> = {
  member: "loans.borrowerMember",
  external: "loans.borrowerExternal",
  patron: "loans.borrowerPatron",
};

/**
 * The willingness to lend. It lives here rather than in the copy panel, which
 * is about the object: this is the panel it governs, and a rule the lend
 * button enforces has to be visible from the lend button.
 */
function LendingSelect({
  book,
  isSavingDetails,
  onSaveLending,
}: Pick<LoanPanelProps, "book" | "isSavingDetails" | "onSaveLending">) {
  const { t } = useTranslation();
  return (
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
            lending: (event.target.value || null) as LendingWillingness | null,
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
  );
}

/** Who the book goes to, and the button that lends it to them. */
function LendControls({
  form,
  members,
  canLendToPatron,
  isBusy,
}: {
  form: LendForm;
  members: UserOut[];
  canLendToPatron: boolean;
  isBusy: boolean;
}) {
  const { t } = useTranslation();
  const kinds = canLendToPatron ? PATRON_KINDS : MEMBER_KINDS;
  return (
    <>
      {/* Refused once, not forbidden. A library lends a never-lent book to a
          sibling sometimes, and an app that will not let them record it gets
          the loan kept in somebody's head instead. So the button stays
          disabled until this is ticked, and the server asks for the same
          acknowledgement whatever the client does. */}
      {form.isNeverLent && (
        <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 dark:border-amber-500/40 dark:bg-amber-500/10">
          <p className="text-xs text-paper-700 dark:text-paper-200">
            {t("lending.neverWarning")}
          </p>
          <label className="mt-1.5 flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={form.acknowledged}
              onChange={(event) => form.setAcknowledged(event.target.checked)}
              className="w-4 h-4 rounded border-paper-300 text-accent-600"
            />
            <span className="text-xs font-medium text-paper-700 dark:text-paper-200">
              {t("lending.lendAnyway")}
            </span>
          </label>
        </div>
      )}

      {/* Radios rather than a select with an "Other..." row: the second and
          third choices need a field of their own, and a select cannot grow one. */}
      <fieldset className="mb-2">
        <legend className="text-xs text-paper-600 mb-1 dark:text-paper-400">
          {t("loans.borrowerKind")}
        </legend>
        <div className="flex gap-4">
          {kinds.map((option) => (
            <label
              key={option}
              className="flex items-center gap-1.5 text-sm text-paper-700 cursor-pointer dark:text-paper-200"
            >
              <input
                type="radio"
                name="borrower-kind"
                value={option}
                checked={form.kind === option}
                onChange={() => form.setKind(option)}
                className="w-4 h-4 text-accent-600"
              />
              {t(KIND_LABELS[option])}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex gap-2">
        {form.kind === "patron" ? (
          <PatronPicker picked={form.picked} onPick={form.setPicked} />
        ) : form.kind === "member" ? (
          <select
            value={form.target}
            onChange={(event) => form.setTarget(event.target.value)}
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
            value={form.externalName}
            maxLength={120}
            onChange={(event) => form.setExternalName(event.target.value)}
            aria-label={t("loans.externalNameLabel")}
            placeholder={t("loans.externalNamePlaceholder")}
            className="flex-1 px-3 py-2.5 rounded-lg border border-paper-200 text-sm bg-paper-0 dark:border-paper-700 dark:bg-paper-900"
          />
        )}
        <button
          onClick={form.lend}
          disabled={!form.canLend || isBusy}
          className="px-4 py-2.5 bg-accent-fill hover:bg-accent-fill-hover disabled:bg-accent-300 text-on-accent rounded-lg text-sm font-semibold transition-colors"
        >
          {t("loans.loanButton")}
        </button>
      </div>
    </>
  );
}

/** Lend the book, or record its return. Used only by BookDetail. */
export default function LoanPanel({
  book,
  members,
  canLendToPatron,
  isBusy,
  isSavingDetails,
  onSaveLending,
  onLend,
  onMarkReturned,
}: LoanPanelProps) {
  const { t } = useTranslation();
  const form = useLendForm(book, onLend);
  const activeLoan = book.active_loan;

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-2 dark:text-paper-200">
        {t("loans.management")}
      </p>

      <LendingSelect
        book={book}
        isSavingDetails={isSavingDetails}
        onSaveLending={onSaveLending}
      />

      {activeLoan ? (
        <button
          onClick={() => onMarkReturned(activeLoan.id)}
          disabled={isBusy}
          className="w-full py-2.5 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300 text-white rounded-lg text-sm font-semibold transition-colors"
        >
          {isBusy ? t("loans.updating") : t("loans.markAsReturned")}
        </button>
      ) : (
        <>
          <LendControls
            form={form}
            members={members}
            canLendToPatron={canLendToPatron}
            isBusy={isBusy}
          />
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
              value={form.dueAt}
              onChange={(event) => form.setDueAt(event.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
            />
          </div>
        </>
      )}
    </div>
  );
}
