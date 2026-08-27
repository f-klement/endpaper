import { useState } from "react";

import type { BookOut, CollectionOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";

interface CollectionPickerProps {
  book: BookOut;
  collections: CollectionOut[];
  isSaving: boolean;
  onChange: (collectionId: number | null) => void;
  onCreate: (name: string) => void;
}

/**
 * Which part of the shelf this copy belongs to.
 *
 * A select rather than free text with suggestions, which is what `location`
 * gets: a collection is a real row that other books point at, so a typo makes
 * a second shelf rather than a second spelling. The escape hatch is the input
 * beside it, which creates one and files this book into it in a single press.
 *
 * **Per copy.** Two copies of one title are two objects, and this control is
 * about the one on screen. The sentence under it says so, because the panel
 * above lists the other copies and the reader would otherwise reasonably
 * assume this covers all of them.
 */
export default function CollectionPicker({
  book,
  collections,
  isSaving,
  onChange,
  onCreate,
}: CollectionPickerProps) {
  const { t } = useTranslation();
  const [newName, setNewName] = useState("");

  function create() {
    const name = newName.trim();
    if (!name) return;
    onCreate(name);
    setNewName("");
  }

  return (
    <div>
      {/* h3, not h2: the section handle that folds this panel away is the
          h2 above it, so a flat h2 here would show a reader's heading list a
          page with no grouping in it at all. */}
      <h3 className="text-sm font-semibold text-paper-900 mb-2 dark:text-paper-100">
        {t("collections.label")}
      </h3>
      <select
        value={book.collection_id === null ? "" : String(book.collection_id)}
        disabled={isSaving}
        onChange={(event) =>
          onChange(
            event.target.value === "" ? null : Number(event.target.value),
          )
        }
        aria-label={t("collections.label")}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm bg-paper-0 disabled:opacity-50 dark:border-paper-700 dark:bg-paper-900"
      >
        <option value="">{t("collections.none")}</option>
        {collections.map((collection) => (
          <option key={collection.id} value={collection.id}>
            {collection.name}
          </option>
        ))}
      </select>

      <div className="flex gap-2 mt-2">
        <input
          type="text"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              // The picker is not inside a form of its own, and Enter in a
              // bare input submits whichever ancestor form is nearest. Handled
              // here so the key does what it looks like it does.
              event.preventDefault();
              create();
            }
          }}
          placeholder={t("collections.newPlaceholder")}
          aria-label={t("collections.newName")}
          maxLength={80}
          className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
        />
        <button
          type="button"
          onClick={create}
          disabled={isSaving || newName.trim() === ""}
          className="px-3 py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
        >
          {isSaving ? t("collections.saving") : t("collections.create")}
        </button>
      </div>

      <p className="text-xs text-paper-600 mt-1.5 dark:text-paper-400">
        {t("collections.explain")}
      </p>
    </div>
  );
}
