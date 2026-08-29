import { useEffect, useState } from "react";

import type { MemberEmailOut } from "../../../../api/generated/model";
import { Button } from "../../../../components";
import { useTranslation } from "../../../../i18n";

interface AddressFieldProps {
  member: MemberEmailOut;
  /** The label above the input. A name in the list, a sentence for your own. */
  label: string;
  disabled: boolean;
  onSave: (email: string | null) => void;
}

/**
 * One address, editable or not.
 *
 * The same component for the member's own field and for each row of the admin
 * list, because they are the same control with a different label. Two would be
 * two places to forget the read only case, which is the one that matters: a
 * field an admin can type into and cannot save is worse than no field.
 *
 * **Read only is drawn as text, not as a disabled input.** A disabled input
 * still reads as a form control that is temporarily unavailable, and this one
 * never becomes available: the directory owns it. The sentence beside it says
 * where to change it instead.
 *
 * Empty is sent as `null`, which is what clears the column. The server accepts
 * either spelling, and picking one here keeps the request the same whether
 * somebody cleared the field or never filled it.
 */
export default function AddressField({
  member,
  label,
  disabled,
  onSave,
}: AddressFieldProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(member.email ?? "");

  // The saved value wins whenever it changes under us: an admin editing a row
  // and a directory sign in writing the same row are both reasons the server's
  // answer moves while this input holds an older one.
  useEffect(() => setDraft(member.email ?? ""), [member.email]);

  const trimmed = draft.trim();
  const unchanged = trimmed === (member.email ?? "");

  if (!member.editable) {
    return (
      <div>
        <p className="text-sm font-medium text-paper-900 dark:text-paper-100">
          {label}
        </p>
        <p className="text-sm text-paper-700 dark:text-paper-300">
          {member.email ?? t("account.email.none")}
        </p>
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("account.email.fromDirectory")}
        </p>
      </div>
    );
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSave(trimmed === "" ? null : trimmed);
      }}
    >
      <label className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-paper-900 dark:text-paper-100">
          {label}
        </span>
        {/* `type="email"` for the keyboard on a phone, not as a control: the
            server checks the shape and answers 422, and a browser's own
            validation is neither the same rule nor present in every browser. */}
        <input
          type="email"
          value={draft}
          disabled={disabled}
          placeholder={t("account.email.placeholder")}
          onChange={(event) => setDraft(event.target.value)}
          className="mt-1 w-full rounded-xl border border-paper-200 bg-paper-0 px-3 py-2 text-sm text-paper-900 disabled:opacity-50 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-100"
        />
      </label>
      <Button type="submit" disabled={disabled || unchanged}>
        {t("common.save")}
      </Button>
    </form>
  );
}
