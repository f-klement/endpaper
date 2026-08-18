import { useState } from "react";
import { Link } from "react-router-dom";

import { OwnershipStatus } from "../../api/generated/model";
import { EmptyState, ErrorState } from "../../components";
import { useTranslation } from "../../i18n";
import BookFilters from "./components/BookFilters";
import BookGrid from "./components/BookGrid";
import SearchBar from "./components/SearchBar";
import SelectionBar from "./components/SelectionBar";
import UnconfirmedBanner from "./components/UnconfirmedBanner";
import { useBookSelection, useLibrary, useUnconfirmedCount } from "./hooks";
import { hasActiveFilters } from "./types";

/**
 * The library grid.
 *
 * Composition only: every request lives in `useLibrary` and `useBookSelection`,
 * and each child below receives plain values and callbacks. That is what keeps
 * the components reusable and testable without a query client.
 */
export default function Home() {
  const { t } = useTranslation();
  const library = useLibrary();
  const selection = useBookSelection();
  const unconfirmed = useUnconfirmedCount();
  const [showTagPanel, setShowTagPanel] = useState(false);

  const filtered = hasActiveFilters(library.filters);

  /** Jump to the unconfirmed books and start ticking them off in one step. */
  function reviewUnconfirmed() {
    library.setOwnership(OwnershipStatus.unknown);
    selection.start();
  }

  return (
    <div className="max-w-6xl mx-auto px-4 pt-5 pb-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
          📚 {t("library.title")}
          {library.total > 0 && (
            <span className="ml-2 text-sm font-normal text-gray-400 dark:text-gray-500">
              {library.total}
            </span>
          )}
        </h1>
        <div className="flex items-center gap-2">
          {!selection.isSelecting && library.books.length > 0 && (
            <button
              type="button"
              onClick={selection.start}
              className="text-sm font-medium text-gray-500 hover:text-gray-800 px-2 py-1.5 transition-colors dark:text-gray-400 dark:hover:text-gray-100"
            >
              {t("library.select")}
            </button>
          )}
          <Link
            to="/scan"
            className="bg-sky-500 hover:bg-sky-600 text-white text-sm font-medium px-3 py-1.5 rounded-lg transition-colors"
          >
            {t("library.scanButton")}
          </Link>
        </div>
      </div>

      {/* Hidden while selecting: the reader is already doing the thing the
          banner would be asking them to do. */}
      {!selection.isSelecting && (
        <UnconfirmedBanner count={unconfirmed} onReview={reviewUnconfirmed} />
      )}

      <SearchBar onSearch={library.setQuery} />

      <BookFilters
        filters={library.filters}
        tags={library.tags}
        showTagPanel={showTagPanel}
        onToggleTagPanel={() => setShowTagPanel((open) => !open)}
        onStatusChange={library.setStatus}
        onOwnershipChange={library.setOwnership}
        onLocationChange={library.setLocation}
        onSeriesClear={() => library.setSeries(null)}
        locations={library.locations}
        onSortChange={library.setSort}
        onToggleTag={library.toggleTag}
        onClearTags={library.clearTags}
      />

      <div className="mt-4">
        {library.error ? (
          <ErrorState
            error={library.error}
            fallback={t("library.couldNotLoad")}
            onRetry={library.refetch}
          />
        ) : !library.isLoading && library.books.length === 0 ? (
          <EmptyState
            glyph="📭"
            title={t("library.noBooks")}
            hint={
              filtered ? t("library.adjustFilters") : t("library.scanFirstBook")
            }
          />
        ) : (
          <BookGrid
            books={library.books}
            isLoading={library.isLoading}
            hasMore={library.hasMore}
            isLoadingMore={library.isLoadingMore}
            onLoadMore={library.loadMore}
            isSelecting={selection.isSelecting}
            isSelected={selection.isSelected}
            onToggleSelect={selection.toggle}
          />
        )}
      </div>

      {selection.isSelecting && (
        <SelectionBar
          selectedCount={selection.selectedIds.length}
          isApplying={selection.isApplying}
          result={selection.result}
          error={selection.error}
          tags={library.tags}
          // Only the books actually loaded into the grid. "Select all" cannot
          // honestly mean rows the reader has not paged in yet.
          onSelectAll={() =>
            selection.selectAll(library.books.map((book) => book.id))
          }
          onClear={selection.clear}
          onApply={selection.apply}
          onRun={selection.run}
          onDone={selection.stop}
        />
      )}
    </div>
  );
}
