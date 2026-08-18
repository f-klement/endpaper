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
}

/** The book's tags, plus a panel for adding more. Used only by BookDetail. */
export default function TagEditor({
  bookTags,
  allTags,
  onAdd,
  onRemove,
}: TagEditorProps) {
  const { t } = useTranslation();
  const [showPicker, setShowPicker] = useState(false);

  // Only offer tags the book does not already carry.
  const assigned = new Set(bookTags.map((tag) => tag.id));
  const available = allTags.filter((tag) => !assigned.has(tag.id));

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-semibold text-gray-700 dark:text-gray-200">
          {t("library.tags")}
        </p>
        <button
          onClick={() => setShowPicker((open) => !open)}
          className="text-xs text-sky-500 hover:text-sky-700"
        >
          {showPicker ? t("common.done") : t("book.addTag")}
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-2">
        {bookTags.length === 0 && !showPicker && (
          <p className="text-xs text-gray-400 italic dark:text-gray-500">
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

      {showPicker && available.length > 0 && (
        <div className="p-3 bg-gray-50 rounded-xl border border-gray-100 dark:bg-gray-900 dark:border-gray-800">
          {/* selectedIds is empty by design: this panel only offers tags the
              book lacks, so nothing in it is ever in a selected state. */}
          <TagPicker tags={available} selectedIds={[]} onToggle={onAdd} />
        </div>
      )}
    </div>
  );
}
