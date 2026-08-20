import { useState } from "react";

import { Button, Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import { MAX_NAME_LENGTH, type SavedSearch } from "../../../lib/savedSearches";
import type { BookFilters } from "../types";

interface SavedSearchesProps {
  searches: SavedSearch<BookFilters>[];
  /** Whether the grid is currently narrowed, so there is anything to save. */
  canSave: boolean;
  onApply: (filters: BookFilters) => void;
  onSave: (name: string) => void;
  onDelete: (id: string) => void;
}

/**
 * Filter combinations somebody named and kept.
 *
 * The save control only appears once a filter is active. Offering to save
 * "everything" is offering to save the page somebody is already on.
 */
export default function SavedSearches({
  searches,
  canSave,
  onApply,
  onSave,
  onDelete,
}: SavedSearchesProps) {
  const { t } = useTranslation();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  function commit() {
    if (!name.trim()) return;
    onSave(name);
    setName("");
    setNaming(false);
  }

  if (searches.length === 0 && !canSave) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {searches.map((search) => (
        <span
          key={search.id}
          className="inline-flex items-center gap-1 rounded-full border border-paper-200 bg-white pl-3 pr-1 text-xs dark:border-paper-700 dark:bg-paper-900"
        >
          <button
            type="button"
            onClick={() => onApply(search.filters)}
            className="py-1.5 font-medium text-paper-700 hover:text-accent-700 dark:text-paper-200 dark:hover:text-accent-300"
          >
            {search.name}
          </button>
          <button
            type="button"
            onClick={() => onDelete(search.id)}
            aria-label={t("saved.forget", { name: search.name })}
            className="rounded-full p-1 text-paper-400 hover:text-bloom-600 dark:hover:text-bloom-300"
          >
            <Icon name="close" className="h-3 w-3" />
          </button>
        </span>
      ))}

      {canSave &&
        (naming ? (
          <span className="inline-flex items-center gap-1">
            <input
              autoFocus
              value={name}
              maxLength={MAX_NAME_LENGTH}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") commit();
                if (event.key === "Escape") setNaming(false);
              }}
              placeholder={t("saved.namePlaceholder")}
              aria-label={t("saved.nameLabel")}
              className="field h-8 w-44 text-xs"
            />
            <Button size="sm" onClick={commit} disabled={!name.trim()}>
              {t("common.save")}
            </Button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setNaming(true)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-paper-300 px-3 py-1.5 text-xs font-medium text-paper-500 hover:border-accent-400 hover:text-accent-700 dark:border-paper-700 dark:text-paper-400 dark:hover:text-accent-300"
          >
            <Icon name="bookmark" className="h-3 w-3" />
            {t("saved.saveThisView")}
          </button>
        ))}
    </div>
  );
}
