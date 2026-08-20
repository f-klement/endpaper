import { useState } from "react";

import type { TagOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { TagPicker } from "../../components";
import { TAG_PILL_CLASSES } from "../../types";

interface TagEditorProps {
  bookTags: TagOut[];
  allTags: TagOut[];
  onAdd: (tagId: number) => void;
  onRemove: (tagId: number) => void;
  /** Invent a tag and put it straight on this book. */
  onCreate: (name: string) => void;
  isCreating?: boolean;
  /** Delete a household tag everywhere. Seeded ones are not offered. */
  onDelete: (tag: TagOut) => void;
}

/** The book's tags, plus a panel for adding more. Used only by BookDetail. */
export default function TagEditor({
  bookTags,
  allTags,
  onAdd,
  onRemove,
  onCreate,
  isCreating = false,
  onDelete,
}: TagEditorProps) {
  const { t } = useTranslation();
  const [showPicker, setShowPicker] = useState(false);

  // Only offer tags the book does not already carry.
  const assigned = new Set(bookTags.map((tag) => tag.id));
  const available = allTags.filter((tag) => !assigned.has(tag.id));

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-paper-700 dark:text-paper-200">
          {t("library.tags")}
        </p>
        <button
          onClick={() => setShowPicker((open) => !open)}
          className="text-xs text-accent-600 hover:text-accent-800 dark:text-accent-400 dark:hover:text-accent-300"
        >
          {showPicker ? t("common.done") : t("book.addTag")}
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-2">
        {bookTags.length === 0 && !showPicker && (
          <p className="text-xs text-paper-600 italic dark:text-paper-400">
            {t("book.noTags")}
          </p>
        )}
        {bookTags.map((tag) => (
          <span
            key={tag.id}
            className={`inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium ${TAG_PILL_CLASSES[tag.category]}`}
          >
            {tag.name}
            <button
              onClick={() => onRemove(tag.id)}
              className="opacity-60 hover:opacity-100 leading-none"
              aria-label={t("book.removeTag", { tag: tag.name })}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      {/* Not gated on `available.length`: with every tag already on the book
          there is nothing to pick and still every reason to invent one. */}
      {showPicker && (
        <div className="p-3 bg-paper-50 rounded-xl border border-paper-100 dark:bg-paper-900 dark:border-paper-800">
          {/* selectedIds is empty by design: this panel only offers tags the
              book lacks, so nothing in it is ever in a selected state. */}
          <TagPicker
            tags={available}
            selectedIds={[]}
            onToggle={onAdd}
            onCreate={onCreate}
            isCreating={isCreating}
            onDelete={onDelete}
          />
        </div>
      )}
    </div>
  );
}
