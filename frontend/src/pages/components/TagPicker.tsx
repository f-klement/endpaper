import type { TagOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import {
  TAG_CATEGORY_LABELS,
  TAG_CATEGORY_ORDER,
  TAG_CHIP_CLASSES,
  groupTagsByCategory,
} from "../types";

interface TagPickerProps {
  tags: TagOut[];
  selectedIds: number[];
  onToggle: (tagId: number) => void;
}

/**
 * Tag chips grouped by category, with a selected state.
 *
 * Lives at `pages/components/` rather than inside a page folder because three
 * pages use it: Home's filter panel, ScanPage's tag step and BookDetail's tag
 * editor. It is still dumb: it renders what it is given and reports clicks.
 */
export default function TagPicker({
  tags,
  selectedIds,
  onToggle,
}: TagPickerProps) {
  const { t } = useTranslation();
  const byCategory = groupTagsByCategory(tags);

  return (
    <div className="space-y-2.5">
      {TAG_CATEGORY_ORDER.map((category) =>
        byCategory[category].length > 0 ? (
          <div key={category}>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1 dark:text-gray-500">
              {t(TAG_CATEGORY_LABELS[category])}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {byCategory[category].map((tag) => {
                const selected = selectedIds.includes(tag.id);
                const styles = TAG_CHIP_CLASSES[category];
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => onToggle(tag.id)}
                    aria-pressed={selected}
                    className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      selected ? styles.active : styles.base
                    }`}
                  >
                    {tag.name}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null,
      )}
    </div>
  );
}
