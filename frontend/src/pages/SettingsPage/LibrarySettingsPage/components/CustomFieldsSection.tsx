import { useState, type FormEvent } from "react";

import {
  CustomFieldKind,
  type CustomFieldOut,
} from "../../../../api/generated/model";
import { Button, ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { SettingsSection } from "../../../components";
import type { RenameCallbacks } from "../hooks";

/** Matches `CUSTOM_FIELD_NAME_MAX` in the backend's models.py. A courtesy, not
 * a check: the server is the authority. */
const NAME_MAX = 60;

interface CustomFieldsSectionProps {
  fields: CustomFieldOut[];
  /** Deleting is admin only, so the control is drawn only where it would work. */
  isAdmin: boolean;
  isBusy: boolean;
  error: unknown;
  onDefine: (name: string, kind: CustomFieldKind) => void;
  /**
   * Reports per call, so a refusal can be told from a success and the row can
   * survive one. See `saveRename` below.
   */
  onRename: (fieldId: number, name: string, callbacks: RenameCallbacks) => void;
  onRemove: (fieldId: number) => void;
}

/**
 * The facts this library keeps about a book that Endpaper has no column for.
 *
 * Here rather than on the book page, unlike the tag vocabulary, and the reason
 * is the delete. Defining a field is additive and open to any member; deleting
 * one destroys what everybody typed, on books the caller may not see, so it is
 * admin only. An admin only destructive control inline on a page every member
 * uses is the arrangement worth avoiding.
 *
 * **A rename keeps every value**, which is why it is offered at all: a badly
 * chosen name is fixable without anybody retyping anything.
 *
 * **Offered where `renamable` says so, and that flag is the server's answer
 * rather than a rule repeated here.** The rule has more arms than a reader
 * would guess and one of its questions is about every book in the library,
 * which no payload this app holds could answer, so it is not enumerated here
 * either: an enumeration is the repetition the flag exists to avoid, and the
 * one that stood here was already an arm short.
 * `backend/schemas/custom_field.py` has the rule and why it ships as an answer
 * instead of the author's member id.
 *
 * **A flag that has gone stale restrictive shows no sentence at all**, which
 * is the direction worth naming because the other one ends in a refusal the
 * member can read. Its single cause is an admin flag flipping inside one
 * account: across accounts the cache is cleared before anything is painted.
 * The control is then absent where the server would have obeyed.
 *
 * **A refused rename keeps the row open and the name that was typed**, and the
 * sentence appears beside that row rather than above the section. The server
 * refuses a rename for reasons that are about one field, a name already taken
 * or a field somebody else defined, and the member's answer to either is to
 * edit what they typed: closing the row discards it and leaves the message
 * pointing at nothing.
 *
 * **The delete confirmation names no count.** A number would have to be
 * counted across books the reader may not see, so it would understate what is
 * about to go; "every book" is the true sentence and needs no query.
 */
export default function CustomFieldsSection({
  fields,
  isAdmin,
  isBusy,
  error,
  onDefine,
  onRename,
  onRemove,
}: CustomFieldsSectionProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<CustomFieldKind>(CustomFieldKind.text);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  // This row's own failure, kept here rather than taken from `error`: that one
  // is the section's, and `useCustomFields` deliberately leaves the rename out
  // of it so the two cannot both render the same sentence.
  const [renameError, setRenameError] = useState<unknown>(null);

  function stopRenaming() {
    setRenamingId(null);
    setRenameError(null);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    onDefine(trimmed, kind);
    setName("");
    setKind(CustomFieldKind.text);
  }

  /**
   * Rename, and **close the row only once the server has said yes**.
   *
   * This used to call the mutation and clear the editing state in the next
   * statement, which is a close on dispatch rather than on success: the 403
   * for a field somebody else defined, and the 409 for a name already taken,
   * both arrived at a row that was no longer there, with the name that was
   * typed already discarded. The only way forward was to press Edit and type
   * it again.
   */
  function saveRename(fieldId: number) {
    const trimmed = renameDraft.trim();
    if (!trimmed) return;
    setRenameError(null);
    onRename(fieldId, trimmed, {
      onSuccess: stopRenaming,
      onError: setRenameError,
    });
  }

  return (
    <SettingsSection title={t("customFields.title")} icon="book">
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("customFields.explain")}
      </p>

      {error != null && <ErrorState error={error} />}

      {fields.length === 0 ? (
        <p className="text-sm text-paper-600 italic dark:text-paper-400">
          {t("customFields.none")}
        </p>
      ) : (
        <ul className="space-y-2">
          {fields.map((field) => (
            <li key={field.id} className="text-sm">
              <div className="flex items-center gap-2">
                {renamingId === field.id ? (
                  <>
                    <input
                      type="text"
                      value={renameDraft}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      maxLength={NAME_MAX}
                      aria-label={t("customFields.renameLabel", {
                        name: field.name,
                      })}
                      className="flex-1 px-3 py-1.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
                    />
                    <Button
                      size="sm"
                      onClick={() => saveRename(field.id)}
                      disabled={isBusy}
                    >
                      {t("common.save")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={stopRenaming}
                    >
                      {t("common.cancel")}
                    </Button>
                  </>
                ) : (
                  <>
                    <span className="flex-1 text-paper-700 dark:text-paper-200">
                      {field.name}
                    </span>
                    <span className="text-xs text-paper-600 dark:text-paper-400">
                      {field.kind === CustomFieldKind.url
                        ? t("customFields.kindUrl")
                        : t("customFields.kindText")}
                    </span>
                    {field.renamable && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setRenamingId(field.id);
                          setRenameDraft(field.name);
                          setRenameError(null);
                        }}
                      >
                        {t("common.edit")}
                      </Button>
                    )}
                    {isAdmin && (
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={isBusy}
                        onClick={() => {
                          // A confirm rather than a toast with an undo, unlike
                          // deleting a book: there is no undo for this one. The
                          // same call `delete_tag` asks the reader to make.
                          if (
                            window.confirm(
                              t("customFields.deleteConfirm", {
                                name: field.name,
                              }),
                            )
                          ) {
                            onRemove(field.id);
                          }
                        }}
                      >
                        {t("common.delete")}
                      </Button>
                    )}
                  </>
                )}
              </div>
              {renamingId === field.id && renameError != null && (
                // Inside the row, so the sentence and the box it is about are
                // read together. `ErrorState` rather than a bare span: this is
                // a failed request like any other and looks like one.
                <div className="mt-1">
                  <ErrorState error={renameError} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="flex flex-wrap gap-2 items-end">
        <label className="flex-1 min-w-40">
          <span className="text-xs text-paper-600 dark:text-paper-400">
            {t("customFields.nameLabel")}
          </span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={NAME_MAX}
            placeholder={t("customFields.namePlaceholder")}
            className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
          />
        </label>
        <label>
          <span className="text-xs text-paper-600 dark:text-paper-400">
            {t("customFields.kindLabel")}
          </span>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as CustomFieldKind)}
            className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
          >
            <option value={CustomFieldKind.text}>
              {t("customFields.kindText")}
            </option>
            <option value={CustomFieldKind.url}>
              {t("customFields.kindUrl")}
            </option>
          </select>
        </label>
        <Button type="submit" size="sm" disabled={isBusy || !name.trim()}>
          {t("customFields.addButton")}
        </Button>
      </form>
    </SettingsSection>
  );
}
