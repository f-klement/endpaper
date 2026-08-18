import type { LocationOut, TagOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { TagPicker } from "../../components";
import type { BookFilters as Filters } from "../types";
import { OWNERSHIP_FILTERS, SORT_OPTIONS, STATUS_FILTERS } from "../types";

interface BookFiltersProps {
  filters: Filters;
  tags: TagOut[];
  showTagPanel: boolean;
  onToggleTagPanel: () => void;
  onStatusChange: (status: Filters["status"]) => void;
  onOwnershipChange: (ownership: Filters["ownership"]) => void;
  onLocationChange: (location: Filters["location"]) => void;
  onSeriesClear: () => void;
  locations: LocationOut[];
  onSortChange: (sort: Filters["sort"]) => void;
  onToggleTag: (tagId: number) => void;
  onClearTags: () => void;
}

/** The status pills, sort select and collapsible tag panel. Presentational. */
export default function BookFilters({
  filters,
  tags,
  showTagPanel,
  onToggleTagPanel,
  onStatusChange,
  onOwnershipChange,
  onLocationChange,
  onSeriesClear,
  locations,
  onSortChange,
  onToggleTag,
  onClearTags,
}: BookFiltersProps) {
  const { t } = useTranslation();
  const activeTagCount = filters.tagIds.length;

  return (
    <>
      <div className="flex items-center gap-2 mt-3 overflow-x-auto pb-1">
        <div className="flex gap-2 flex-1">
          {STATUS_FILTERS.map((option) => (
            <button
              key={option.label}
              onClick={() => onStatusChange(option.value)}
              aria-pressed={filters.status === option.value}
              className={`shrink-0 text-sm px-3 py-1 rounded-full border transition-colors ${
                filters.status === option.value
                  ? "bg-sky-500 border-sky-500 text-white"
                  : "border-gray-200 text-gray-600 bg-white hover:border-sky-300"
              }`}
            >
              {t(option.label)}
            </button>
          ))}
        </div>
        <select
          value={filters.sort}
          onChange={(event) =>
            onSortChange(event.target.value as Filters["sort"])
          }
          aria-label={t("library.sortLabel")}
          className="shrink-0 text-sm px-2 py-1 rounded-lg border border-gray-200 bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.label)}
            </option>
          ))}
        </select>
      </div>

      {/* A second row rather than more pills in the first: ownership and
          reading status are independent, and mixing them into one strip would
          suggest picking one clears the other. */}
      <div
        className="flex items-center gap-2 mt-2 overflow-x-auto pb-1"
        role="group"
        aria-label={t("ownership.label")}
      >
        <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">
          {t("ownership.label")}
        </span>
        {OWNERSHIP_FILTERS.map((option) => (
          <button
            key={option.label}
            onClick={() => onOwnershipChange(option.value)}
            aria-pressed={filters.ownership === option.value}
            className={`shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
              filters.ownership === option.value
                ? "bg-amber-500 border-amber-500 text-white"
                : "border-gray-200 text-gray-600 bg-white hover:border-amber-300"
            }`}
          >
            {t(option.label)}
          </button>
        ))}
      </div>

      {(locations.length > 0 || filters.location) && (
        <div className="mt-2">
          <select
            value={filters.location ?? ""}
            onChange={(event) => onLocationChange(event.target.value || null)}
            aria-label={t("location.label")}
            className="text-xs px-2 py-1 rounded-lg border border-gray-200 bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-sky-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
          >
            <option value="">{t("location.filterAll")}</option>
            {locations.map((place) => (
              <option key={place.name} value={place.name}>
                {place.name} ({place.book_count})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* A series filter is arrived at by following a link from a book, so it
          is shown as a removable chip rather than as another dropdown. */}
      {filters.series && (
        <div className="mt-2">
          <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-sky-50 border border-sky-200 text-sky-700 dark:bg-sky-950 dark:border-sky-800 dark:text-sky-300">
            {t("series.label")}: {filters.series}
            <button
              type="button"
              onClick={onSeriesClear}
              aria-label={t("common.clearSelection")}
              className="opacity-60 hover:opacity-100 leading-none"
            >
              ×
            </button>
          </span>
        </div>
      )}

      <div className="mt-2">
        <button
          onClick={onToggleTagPanel}
          className={`text-sm px-3 py-1 rounded-full border transition-colors inline-flex items-center gap-1.5 ${
            activeTagCount > 0
              ? "bg-indigo-500 border-indigo-500 text-white"
              : "border-gray-200 text-gray-600 bg-white hover:border-indigo-300"
          }`}
        >
          🏷 {t("library.tags")} {activeTagCount > 0 && `(${activeTagCount})`}
          <span className="text-xs opacity-75">{showTagPanel ? "▲" : "▼"}</span>
        </button>
        {activeTagCount > 0 && (
          <button
            onClick={onClearTags}
            className="ml-2 text-xs text-gray-400 hover:text-gray-600 underline dark:text-gray-500 dark:hover:text-gray-300"
          >
            {t("library.clear")}
          </button>
        )}
      </div>

      {showTagPanel && (
        <div className="mt-2 p-3 bg-gray-50 rounded-xl border border-gray-100 dark:bg-gray-900 dark:border-gray-800">
          <TagPicker
            tags={tags}
            selectedIds={filters.tagIds}
            onToggle={onToggleTag}
          />
        </div>
      )}
    </>
  );
}
