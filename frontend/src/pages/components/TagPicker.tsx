import { useId, useState } from "react";

import type { TagOut } from "../../api/generated/model";
import { Icon } from "../../components";
import { tagName, useTranslation } from "../../i18n";
import {
  TAG_CATEGORY_LABELS,
  TAG_CATEGORY_ORDER,
  TAG_CHIP_CLASSES,
  TAG_CHIP_SELECTED,
  groupTagsByCategory,
} from "../types";

interface TagPickerProps {
  tags: TagOut[];
  selectedIds: number[];
  onToggle: (tagId: number) => void;
  /**
   * Invent a tag from here. Omitted where the picker is a filter rather than
   * an editor: inventing a tag while narrowing a list is a different act from
   * putting one on a book, and offering it there produces tags nothing carries.
   */
  onCreate?: (name: string) => void;
  isCreating?: boolean;
  /**
   * Delete a tag the library invented, everywhere. Offered only alongside
   * `onCreate`, because the place you invent a vocabulary is the place you
   * correct it.
   */
  onDelete?: (tag: TagOut) => void;
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
  onCreate,
  isCreating = false,
  onDelete,
}: TagPickerProps) {
  const { t, locale } = useTranslation();
  const [name, setName] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const panelId = useId();
  const byCategory = groupTagsByCategory(tags, locale);

  /**
   * A category starts closed unless something in it is selected.
   *
   * The curated vocabulary is a hundred and five tags. All of them on screen
   * at once is not a picker, it is a wall, and the genre list alone would push
   * everything below it off the page. Closed by default keeps the shape of the
   * thing visible (four headings, with counts) and opens the one being used.
   *
   * A category holding a selected tag opens itself, because a selection you
   * cannot see is worse than a long list.
   */
  function isOpen(category: string, ids: number[]): boolean {
    return open.has(category) || ids.some((id) => selectedIds.includes(id));
  }

  function toggleCategory(category: string) {
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(category)) next.add(category);
      return next;
    });
  }

  function create() {
    const trimmed = name.trim();
    if (!trimmed) return;
    onCreate?.(trimmed);
    setName("");
  }

  return (
    <div className="space-y-2.5">
      {TAG_CATEGORY_ORDER.map((category) => {
        const inCategory = byCategory[category];
        if (inCategory.length === 0) return null;

        const ids = inCategory.map((tag) => tag.id);
        const chosen = ids.filter((id) => selectedIds.includes(id)).length;
        const expanded = isOpen(category, ids);

        return (
          <div key={category}>
            <button
              type="button"
              onClick={() => toggleCategory(category)}
              aria-expanded={expanded}
              aria-controls={`${panelId}-${category}`}
              className="flex w-full items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-paper-600 hover:text-paper-800 dark:text-paper-400 dark:hover:text-paper-300"
            >
              <Icon
                name="chevron"
                className={`h-3 w-3 transition-transform duration-150 ${
                  expanded ? "rotate-90" : ""
                }`}
              />
              {t(TAG_CATEGORY_LABELS[category])}{" "}
              <span className="font-normal normal-case text-paper-600 dark:text-paper-400">
                {chosen > 0
                  ? t("tags.countWithChosen", {
                      count: inCategory.length,
                      chosen,
                    })
                  : t("tags.count", { count: inCategory.length })}
              </span>
            </button>

            {expanded && (
              <div
                id={`${panelId}-${category}`}
                role="group"
                aria-label={t(TAG_CATEGORY_LABELS[category])}
                className="mt-1 flex flex-wrap gap-1.5"
              >
                {inCategory.map((tag) => {
                  const selected = selectedIds.includes(tag.id);
                  // Only a tag the library invented can go. A seeded one
                  // comes straight back at the next restart, so offering it
                  // would be offering an action that undoes itself.
                  const removable = Boolean(onDelete) && !tag.is_predefined;
                  return (
                    <span
                      key={tag.id}
                      className={`inline-flex items-center rounded-full border text-xs transition-colors ${
                        selected
                          ? TAG_CHIP_SELECTED
                          : TAG_CHIP_CLASSES[category]
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => onToggle(tag.id)}
                        aria-pressed={selected}
                        className={`px-2.5 py-1 ${removable ? "pr-1" : ""}`}
                      >
                        {tagName(tag, locale)}
                      </button>
                      {removable && (
                        <button
                          type="button"
                          onClick={() => onDelete?.(tag)}
                          aria-label={t("tags.delete", {
                            name: tagName(tag, locale),
                          })}
                          className="pr-1.5 pl-0.5 opacity-60 hover:opacity-100"
                        >
                          <Icon name="close" className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {onCreate && (
        <div className="flex gap-1.5 pt-1">
          <input
            type="text"
            value={name}
            maxLength={100}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                // The picker sits inside forms. Without this the Enter that
                // means "add this tag" submits the book instead.
                event.preventDefault();
                create();
              }
            }}
            placeholder={t("tags.newPlaceholder")}
            aria-label={t("tags.newLabel")}
            className="field h-8 flex-1 text-xs"
          />
          <button
            type="button"
            onClick={create}
            disabled={isCreating || !name.trim()}
            className="inline-flex items-center gap-1 rounded-lg border border-paper-200 px-2.5 text-xs font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
          >
            <Icon name="tag" className="h-3 w-3" />
            {t("tags.create")}
          </button>
        </div>
      )}
    </div>
  );
}
