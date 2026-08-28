import { useState, type FormEvent } from "react";

import {
  CustomFieldKind,
  type CustomFieldOut,
} from "../../../../api/generated/model";
import { Button, ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { SettingsSection } from "../../../components";

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
  onRename: (fieldId: number, name: string) => void;
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

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    onDefine(trimmed, kind);
    setName("");
    setKind(CustomFieldKind.text);
  }

  function saveRename(fieldId: number) {
    const trimmed = renameDraft.trim();
    if (!trimmed) return;
    onRename(fieldId, trimmed);
    setRenamingId(null);
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
            <li key={field.id} className="flex items-center gap-2 text-sm">
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
                    onClick={() => setRenamingId(null)}
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
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setRenamingId(field.id);
                      setRenameDraft(field.name);
                    }}
                  >
                    {t("common.edit")}
                  </Button>
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
