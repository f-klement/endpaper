import { useState } from "react";

import { Button, Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import { MAX_NAME_LENGTH } from "../../../lib/savedSearches";
import type { SavedSearchChoice } from "../hooks";
import type { BookFilters } from "../types";

interface SavedSearchesProps {
  /** The kept views and the two verbs for them, as one value. */
  saved: SavedSearchChoice;
  /** Whether the grid is currently narrowed, so there is anything to save. */
  canSave: boolean;
  /**
   * Apply one. Stays a callback rather than joining `saved`, because applying a
   * saved view writes the filters and the filters are not a preference: they
   * belong to `useLibrary`, which is the one door they are written through.
   */
  onApply: (filters: BookFilters) => void;
}

/**
 * Filter combinations somebody named and kept.
 *
 * The save control only appears once a filter is active. Offering to save
 * "everything" is offering to save the page somebody is already on.
 */
export default function SavedSearches({
  saved,
  canSave,
  onApply,
}: SavedSearchesProps) {
  const { searches, save, remove } = saved;
  const { t } = useTranslation();
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  function commit() {
    if (!name.trim()) return;
    save(name);
    setName("");
    setNaming(false);
  }

  if (searches.length === 0 && !canSave) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      {searches.map((search) => (
        <span
          key={search.id}
          className="inline-flex items-center gap-1 rounded-full border border-paper-200 bg-paper-0 pl-3 pr-1 text-xs dark:border-paper-700 dark:bg-paper-900"
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
            onClick={() => remove(search.id)}
            aria-label={t("saved.forget", { name: search.name })}
            className="rounded-full p-1 text-paper-600 hover:text-danger-600 dark:text-paper-400 dark:hover:text-danger-300"
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
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-paper-300 px-3 py-1.5 text-xs font-medium text-paper-600 hover:border-accent-400 hover:text-accent-700 dark:border-paper-700 dark:text-paper-400 dark:hover:text-accent-300"
          >
            <Icon name="bookmark" className="h-3 w-3" />
            {t("saved.saveThisView")}
          </button>
        ))}
    </div>
  );
}
