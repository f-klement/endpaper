import { useState, type FormEvent } from "react";

import type { PatronCreate } from "../../api/generated/model";
import { Button, ErrorState, Modal } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { isSendable, patronBody, type PatronDraft } from "../types";

interface PatronFormProps {
  title: string;
  /** What the form opens holding: blank for a new patron, the record for an edit. */
  initial: PatronDraft;
  submitLabel: string;
  busyLabel: string;
  isSaving: boolean;
  error: unknown;
  onSubmit: (body: PatronCreate) => void;
  onClose: () => void;
}

/** One field: which draft key it writes, its label, and its input type. */
interface Field {
  key: keyof PatronDraft;
  label: MessageKey;
  type: "text" | "email" | "tel" | "date";
  autoComplete?: string;
  required?: boolean;
  maxLength?: number;
  hint?: MessageKey;
}

// The two limits the generated model carries. The optional fields' limits are
// lost on a nullable string by the generator, and the server's 422 states
// them instead.
const NAME_MAX = 120;
const CARD_NUMBER_MAX = 32;

const IDENTITY: Field[] = [
  {
    key: "name",
    label: "patrons.name",
    type: "text",
    autoComplete: "off",
    required: true,
    maxLength: NAME_MAX,
  },
  {
    key: "card_number",
    label: "patrons.cardNumber",
    type: "text",
    autoComplete: "off",
    required: true,
    maxLength: CARD_NUMBER_MAX,
    hint: "patrons.cardNumberHint",
  },
  { key: "expires_on", label: "patrons.expiresOn", type: "date" },
];

const CONTACT: Field[] = [
  { key: "email", label: "patrons.email", type: "email", autoComplete: "off" },
  { key: "phone", label: "patrons.phone", type: "tel", autoComplete: "off" },
];

const ADDRESS: Field[] = [
  { key: "street", label: "patrons.street", type: "text", autoComplete: "off" },
  {
    key: "house_number",
    label: "patrons.houseNumber",
    type: "text",
    autoComplete: "off",
  },
  {
    key: "postcode",
    label: "patrons.postcode",
    type: "text",
    autoComplete: "off",
  },
  { key: "city", label: "patrons.city", type: "text", autoComplete: "off" },
];

/**
 * The patron record as a form, for registering and for editing alike. Two
 * pages hold it: the patron register, and the loan form, which registers the
 * person taking the book without leaving the loan.
 *
 * `autoComplete="off"` on every box: the staff member typing is not the
 * person being registered, and a browser offering the admin's own address
 * into a stranger's record is the wrong person's data one tap away.
 *
 * The submit is held until a name and a card number have more than spaces in
 * them; what the server refuses beyond that (a card number another patron
 * carries, a malformed one) comes back through `error`.
 */
export default function PatronForm({
  title,
  initial,
  submitLabel,
  busyLabel,
  isSaving,
  error,
  onSubmit,
  onClose,
}: PatronFormProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(initial);
  const sendable = isSendable(draft);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sendable || isSaving) return;
    onSubmit(patronBody(draft));
  }

  const fields = (group: Field[]) =>
    group.map((field) => (
      <label key={field.key} className="block text-sm">
        <span className="block text-paper-700 mb-1 dark:text-paper-300">
          {t(field.label)}
        </span>
        <input
          type={field.type}
          value={draft[field.key]}
          onChange={(event) =>
            setDraft({ ...draft, [field.key]: event.target.value })
          }
          required={field.required}
          maxLength={field.maxLength}
          autoComplete={field.autoComplete}
          className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
        />
        {field.hint && (
          <span className="block text-xs text-paper-600 mt-1 dark:text-paper-400">
            {t(field.hint)}
          </span>
        )}
      </label>
    ));

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-3">{fields(IDENTITY)}</div>
        <fieldset className="space-y-3">
          <legend className="text-xs font-semibold uppercase tracking-wide text-paper-600 mb-2 dark:text-paper-400">
            {t("patrons.contact")}
          </legend>
          {fields(CONTACT)}
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="text-xs font-semibold uppercase tracking-wide text-paper-600 mb-2 dark:text-paper-400">
            {t("patrons.address")}
          </legend>
          {fields(ADDRESS)}
        </fieldset>

        {error != null && (
          <ErrorState error={error} fallback={t("patrons.couldNotSave")} />
        )}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!sendable || isSaving}>
            {isSaving ? busyLabel : submitLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
