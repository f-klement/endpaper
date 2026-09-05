import type {
  ClassificationFacets,
  CollectionOut,
  LocationOut,
  TagOut,
} from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import type { LibraryView } from "../../../lib/libraryView";
import { TagPicker } from "../../components";
import ClassificationPicker from "./ClassificationPicker";
import type { BookFilters as Filters } from "../types";
import {
  FORMAT_FILTERS,
  LENDING_FILTERS,
  OWNERSHIP_FILTERS,
  SORT_OPTIONS,
  STATUS_FILTERS,
  VIEW_OPTIONS,
} from "../types";
import { Icon } from "../../../components";

interface BookFiltersProps {
  filters: Filters;
  tags: TagOut[];
  showTagPanel: boolean;
  onToggleTagPanel: () => void;
  /**
   * Change one or more filters. One callback, not one per field.
   *
   * Ten of these were separate props, each spelled in the interface, in the
   * destructure and at its handler: thirty spellings for one object. Adding a
   * filter cost a line in each, which is the abstraction making the next change
   * harder rather than easier. The panel now says what changed and the caller
   * decides what that means.
   */
  onFilterChange: (patch: Partial<Filters>) => void;
  locations: LocationOut[];
  collections: CollectionOut[];
  onToggleTag: (tagId: number) => void;
  onClearTags: () => void;
  classifications: ClassificationFacets | undefined;
  showClassificationPanel: boolean;
  onToggleClassificationPanel: () => void;
  onToggleHeading: (heading: string) => void;
  onToggleDivision: (division: string) => void;
  onClearClassifications: () => void;
  view: LibraryView;
  onViewChange: (view: LibraryView) => void;
  /**
   * False while the library cannot yet say which view a pick would be saved
   * under, so the group is disabled rather than left looking live. The window
   * is the feature flags being in flight, and `pages/Home/hooks.ts` says why a
   * write in it cannot be allowed through.
   */
  canChangeView: boolean;
}

/**
 * The status pills, the sort select, and the two collapsible panels.
 * Presentational.
 */
export default function BookFilters({
  filters,
  tags,
  showTagPanel,
  onToggleTagPanel,
  onFilterChange,
  locations,
  collections,
  onToggleTag,
  onClearTags,
  classifications,
  showClassificationPanel,
  onToggleClassificationPanel,
  onToggleHeading,
  onToggleDivision,
  onClearClassifications,
  view,
  onViewChange,
  canChangeView,
}: BookFiltersProps) {
  const { t } = useTranslation();
  const activeTagCount = filters.tagIds.length;
  // Both groups count towards one badge, because the pill is one control and
  // "3" beside it should mean three things are narrowing the shelf.
  const activeClassificationCount =
    filters.headings.length + filters.ddcDivisions.length;

  return (
    <>
      <div className="flex items-center gap-2 mt-3 overflow-x-auto pb-1">
        <div className="flex gap-2 flex-1">
          {STATUS_FILTERS.map((option) => (
            <button
              key={option.label}
              onClick={() => onFilterChange({ status: option.value })}
              aria-pressed={filters.status === option.value}
              className={`shrink-0 text-sm px-3 py-1 rounded-full border transition-colors ${
                filters.status === option.value
                  ? "bg-accent-fill border-accent-fill text-on-accent"
                  : "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 " +
                    "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
              }`}
            >
              {t(option.label)}
            </button>
          ))}
        </div>
        <select
          value={filters.sort}
          onChange={(event) =>
            onFilterChange({ sort: event.target.value as Filters["sort"] })
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

        {/* Beside the sort, because both answer "how am I looking at this",
            rather than up with the filters, which answer "at what". */}
        <div
          role="group"
          aria-label={t("library.viewLabel")}
          className="shrink-0 flex rounded-lg border border-paper-200 dark:border-paper-700"
        >
          {VIEW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onViewChange(option.value)}
              aria-pressed={view === option.value}
              // `disabled` rather than a hidden group: the buttons say which
              // view is on, and taking them away for a paint would move the
              // strip under the reader's finger.
              disabled={!canChangeView}
              // **The house `disabled:opacity` is on the unpressed arm only.**
              // `opacity` on a button composites its fill and its text
              // together, and on the pressed arm that pair is
              // `on-accent`/`accent-fill`, which `palettes.test.ts` floors at
              // 4.5:1 and which halves to 2.83:1 light and 3.52:1 dark under
              // it. `ColumnPicker` records those figures where it hit the same
              // wall. Leaving the pressed button undimmed also keeps the group
              // answering which view is on while it cannot be changed.
              className={`px-2.5 py-1 text-sm transition-colors first:rounded-l-md last:rounded-r-md disabled:cursor-not-allowed ${
                view === option.value
                  ? "bg-accent-fill text-on-accent"
                  : "bg-paper-0 text-paper-600 hover:text-accent-700 " +
                    "disabled:opacity-50 " +
                    "dark:bg-paper-900 dark:text-paper-300 dark:hover:text-accent-300"
              }`}
            >
              {t(option.label)}
            </button>
          ))}
        </div>
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
            onClick={() => onFilterChange({ ownership: option.value })}
            aria-pressed={filters.ownership === option.value}
            className={`shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
              filters.ownership === option.value
                ? "bg-amber-500 border-amber-500 text-white"
                : "border-paper-200 text-paper-600 bg-paper-0 hover:border-amber-300 " +
                  "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
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
            onFilterChange({
              format: (event.target.value || null) as Filters["format"],
            })
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

        {/* Beside the format, because both narrow what kind of copy this is
            rather than what the reader has done with it. */}
        <select
          value={filters.lending ?? ""}
          onChange={(event) =>
            onFilterChange({
              lending: (event.target.value || null) as Filters["lending"],
            })
          }
          aria-label={t("lending.label")}
          className="text-xs px-2 py-1 rounded-lg border border-paper-200 bg-paper-0 text-paper-600 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300"
        >
          {LENDING_FILTERS.map((option) => (
            <option key={option.label} value={option.value ?? ""}>
              {t(option.label)}
            </option>
          ))}
        </select>

        {/* A toggle rather than a third dropdown: it has one useful state.
            The books nobody has offered to talk about are the whole library,
            which is what the button already off shows. */}
        <button
          type="button"
          onClick={() => onFilterChange({ discuss: !filters.discuss })}
          aria-pressed={filters.discuss}
          className={`shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
            filters.discuss
              ? "bg-accent-fill border-accent-fill text-on-accent"
              : "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 " +
                "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
          }`}
        >
          {t("discuss.badge")}
        </button>
      </div>

      {/* Only once a library has divided its shelf: a picker offering one
          option, "Any collection", is a control that cannot do anything.
          **Or whenever a collection is being filtered on**, which is not the
          same condition and is the one that bites. An admin deleting the
          collection somebody else is browsing empties the list while the id
          stays in filter state and keeps being sent, so on `length > 0` alone
          the picker vanishes and leaves an empty grid with no control to clear
          it. The location filter three blocks down has always had this second
          clause; this one was missing it.

          Deliberately **not** clearing a filter whose id is absent from the
          list, which is the other obvious fix and is wrong: `collections` is
          `[]` while the query is in flight, so it would wipe a `?collection=4`
          deep link on first render. The grid's empty state already says
          "adjust your filters", because `hasActiveFilters` counts this one. */}
      {(collections.length > 0 || filters.collection !== null) && (
        <div className="mt-2">
          <select
            value={
              filters.collection === null ? "" : String(filters.collection)
            }
            onChange={(event) => {
              const chosen = event.target.value;
              onFilterChange({
                collection:
                  chosen === ""
                    ? null
                    : chosen === "unfiled"
                      ? "unfiled"
                      : Number(chosen),
              });
            }}
            aria-label={t("collections.label")}
            className="text-xs px-2 py-1 rounded-lg border border-paper-200 bg-paper-0 text-paper-600 dark:border-paper-700 dark:bg-paper-900 dark:text-paper-300"
          >
            <option value="">{t("collections.filterAll")}</option>
            {collections.map((collection) => (
              <option key={collection.id} value={collection.id}>
                {collection.name} ({collection.book_count})
              </option>
            ))}
            {/* Last, and separate: "in none of them" is not one of them. It is
                how somebody finds what they have not filed yet, which is the
                job the whole feature creates. */}
            <option value="unfiled">{t("collections.filterUnfiled")}</option>
          </select>
        </div>
      )}

      {(locations.length > 0 || filters.location) && (
        <div className="mt-2">
          <select
            value={filters.location ?? ""}
            onChange={(event) =>
              onFilterChange({ location: event.target.value || null })
            }
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

      {/* An author filter is arrived at by following a link, like the series
          one below, so it is a removable chip rather than a dropdown over
          every name on the shelf. The chip shows the key, which is what the
          link carried: the display name is on the authors page, and showing it
          here would need a second request to find out what it is. */}
      {filters.author && (
        <div className="mt-2">
          <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-accent-50 border border-accent-200 text-accent-800 dark:bg-accent-950 dark:border-accent-900 dark:text-accent-300">
            {t("authors.label")}: {filters.author}
            <button
              type="button"
              onClick={() => onFilterChange({ author: null })}
              aria-label={t("common.clearSelection")}
              className="opacity-60 hover:opacity-100 leading-none"
            >
              ×
            </button>
          </span>
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
              onClick={() => onFilterChange({ series: null })}
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
              : "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 " +
                "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
          }`}
        >
          <Icon name="tag" className="w-3.5 h-3.5" /> {t("library.tags")}{" "}
          {activeTagCount > 0 && `(${activeTagCount})`}
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

      {/* Beside the tag pill and never inside it. The two filter the same
          shelf and mean different things: a tag is this library's word, a
          heading is a published scheme's. Folding them into one control would
          be the flattening the whole store exists to avoid. */}
      <div className="mt-2">
        <button
          onClick={onToggleClassificationPanel}
          className={`text-sm px-3 py-1 rounded-full border transition-colors inline-flex items-center gap-1.5 ${
            activeClassificationCount > 0
              ? "bg-accent-fill border-accent-fill text-on-accent"
              : "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 " +
                "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300"
          }`}
        >
          <Icon name="library" className="w-3.5 h-3.5" />{" "}
          {t("classification.filter")}{" "}
          {activeClassificationCount > 0 && `(${activeClassificationCount})`}
          <Icon
            name="chevron"
            className={`w-3 h-3 opacity-70 transition-transform duration-150 ${
              showClassificationPanel ? "-rotate-90" : "rotate-90"
            }`}
          />
        </button>
        {activeClassificationCount > 0 && (
          <button
            onClick={onClearClassifications}
            className="ml-2 text-xs text-paper-600 hover:text-paper-800 underline dark:text-paper-400 dark:hover:text-paper-300"
          >
            {t("library.clear")}
          </button>
        )}
      </div>

      {showClassificationPanel && (
        <div className="mt-2 p-3 bg-paper-50 rounded-xl border border-paper-100 dark:bg-paper-900 dark:border-paper-800">
          <ClassificationPicker
            facets={classifications}
            selectedHeadings={filters.headings}
            selectedDivisions={filters.ddcDivisions}
            onToggleHeading={onToggleHeading}
            onToggleDivision={onToggleDivision}
          />
        </div>
      )}
    </>
  );
}
