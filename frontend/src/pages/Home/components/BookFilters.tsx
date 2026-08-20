import type { LocationOut, TagOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { TagPicker } from "../../components";
import type { BookFilters as Filters } from "../types";
import {
  FORMAT_FILTERS,
  OWNERSHIP_FILTERS,
  SORT_OPTIONS,
  STATUS_FILTERS,
} from "../types";
import { Icon } from "../../../components";

interface BookFiltersProps {
  filters: Filters;
  tags: TagOut[];
  showTagPanel: boolean;
  onToggleTagPanel: () => void;
  onStatusChange: (status: Filters["status"]) => void;
  onOwnershipChange: (ownership: Filters["ownership"]) => void;
  onLocationChange: (location: Filters["location"]) => void;
  onFormatChange: (format: Filters["format"]) => void;
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
  onFormatChange,
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
                  ? "bg-accent-fill border-accent-fill text-on-accent"
                  : "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
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
          className="shrink-0 text-sm px-2 py-1 rounded-lg border border-paper-200 bg-paper-0 text-paper-600 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300"
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
        <span className="shrink-0 text-xs text-paper-600 dark:text-paper-400">
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
                : "border-paper-200 text-paper-600 bg-paper-0 hover:border-amber-300 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
            }`}
          >
            {t(option.label)}
          </button>
        ))}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select
          value={filters.format ?? ""}
          onChange={(event) =>
            onFormatChange(
              (event.target.value || null) as Filters["format"],
            )
          }
          aria-label={t("copy.format")}
          className="text-xs px-2 py-1 rounded-lg border border-paper-200 bg-paper-0 text-paper-600 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300"
        >
          {FORMAT_FILTERS.map((option) => (
            <option key={option.label} value={option.value ?? ""}>
              {t(option.label)}
            </option>
          ))}
        </select>
      </div>

      {(locations.length > 0 || filters.location) && (
        <div className="mt-2">
          <select
            value={filters.location ?? ""}
            onChange={(event) => onLocationChange(event.target.value || null)}
            aria-label={t("location.label")}
            className="text-xs px-2 py-1 rounded-lg border border-paper-200 bg-paper-0 text-paper-600 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300"
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
          <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-accent-50 border border-accent-200 text-accent-800 dark:bg-accent-950 dark:border-accent-900 dark:text-accent-300">
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
              ? "bg-accent-fill border-accent-fill text-on-accent"
              : "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
          }`}
        >
          <Icon name="tag" className="w-3.5 h-3.5" /> {t("library.tags")} {activeTagCount > 0 && `(${activeTagCount})`}
          <Icon
            name="chevron"
            className={`w-3 h-3 opacity-70 transition-transform duration-150 ${
              showTagPanel ? "-rotate-90" : "rotate-90"
            }`}
          />
        </button>
        {activeTagCount > 0 && (
          <button
            onClick={onClearTags}
            className="ml-2 text-xs text-paper-600 hover:text-paper-800 underline dark:text-paper-400 dark:hover:text-paper-300"
          >
            {t("library.clear")}
          </button>
        )}
      </div>

      {showTagPanel && (
        <div className="mt-2 p-3 bg-paper-50 rounded-xl border border-paper-100 dark:bg-paper-900 dark:border-paper-800">
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
