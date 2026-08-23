import { useState } from "react";
import { Link } from "react-router-dom";

import { OwnershipStatus } from "../../api/generated/model";
import { Button, EmptyState, ErrorState } from "../../components";
import { Page, PageCount, PageHeader } from "../components";
import { useTranslation } from "../../i18n";
import BookFilters from "./components/BookFilters";
import BookGrid from "./components/BookGrid";
import BookTable from "./components/BookTable";
import SavedSearches from "./components/SavedSearches";
import SearchBar from "./components/SearchBar";
import SelectionBar from "./components/SelectionBar";
import UnconfirmedBanner from "./components/UnconfirmedBanner";
import { useBookSelection, useLibrary, useUnconfirmedCount } from "./hooks";
import { hasActiveFilters, isWishlist } from "./types";

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
  const wishlist = isWishlist(library.filters);

  /** Jump to the unconfirmed books and start ticking them off in one step. */
  function reviewUnconfirmed() {
    library.setOwnership(OwnershipStatus.unknown);
    selection.start();
  }

  return (
    <Page width="wide">
      <PageHeader
        icon="library"
        title={t(wishlist ? "wishlist.title" : "library.title")}
        badge={library.total > 0 && <PageCount>{library.total}</PageCount>}
        actions={
          <>
          {!selection.isSelecting && library.books.length > 0 && (
            <Button variant="ghost" size="sm" onClick={selection.start}>
              {t("library.select")}
            </Button>
          )}
          {/* A link that looks like the primary button, so the two agree.
              Not <Button as={Link}>: a polymorphic prop is a lot of type
              machinery for one call site. */}
          <Link
            to="/scan"
            className="inline-flex items-center justify-center gap-2 h-10 px-4 rounded-lg text-sm font-medium bg-accent-fill text-on-accent shadow-[var(--shadow-soft)] transition-[background-color,box-shadow,transform] duration-150 ease-[var(--ease-out-soft)] active:scale-[0.97] hover:bg-accent-fill-hover hover:shadow-[var(--shadow-lift)]"
          >
            {t("library.scanButton")}
          </Link>
          </>
        }
      />

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
        onFormatChange={library.setFormat}
        onLendingChange={library.setLending}
        onDiscussChange={library.setDiscuss}
        onLocationChange={library.setLocation}
        onCollectionChange={library.setCollection}
        onSeriesClear={() => library.setSeries(null)}
        locations={library.locations}
        collections={library.collections}
        onSortChange={library.setSort}
        onToggleTag={library.toggleTag}
        onClearTags={library.clearTags}
        view={library.view}
        onViewChange={library.setView}
      />

      <SavedSearches
        searches={library.savedSearches}
        canSave={filtered}
        onApply={library.setFilters}
        onSave={library.saveCurrentSearch}
        onDelete={library.deleteSavedSearch}
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
            icon="inbox"
            title={t(wishlist ? "wishlist.empty" : "library.noBooks")}
            hint={
              wishlist
                ? t("wishlist.emptyHint")
                : filtered
                  ? t("library.adjustFilters")
                  : t("library.scanFirstBook")
            }
          />
        ) : (
          // Dimmed rather than emptied while a newer search runs. Replacing the
          // grid with skeletons on every keystroke is the flicker this avoids.
          <div
            className={
              library.isStale
                ? "opacity-60 transition-opacity duration-150"
                : "transition-opacity duration-150"
            }
            aria-busy={library.isStale}
          >
            {/* Selecting forces the grid: the checkbox lives on a card, and
                a table of nineteen columns is not where somebody ticks twenty
                books off. Starting a selection therefore shows the covers
                again, rather than offering a selection that does nothing. */}
            {library.view === "table" && !selection.isSelecting ? (
              <BookTable
                books={library.books}
                sort={library.filters.sort}
                onSortChange={library.setSort}
                isLoading={library.isLoading}
                hasMore={library.hasMore}
                isLoadingMore={library.isLoadingMore}
                onLoadMore={library.loadMore}
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
        )}
      </div>

      {selection.isSelecting && (
        <SelectionBar
          selectedCount={selection.selectedIds.length}
          isApplying={selection.isApplying}
          result={selection.result}
          error={selection.error}
          tags={library.tags}
          collections={library.collections}
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
    </Page>
  );
}
