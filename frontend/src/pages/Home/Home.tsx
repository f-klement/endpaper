import { useState } from "react";
import { Link } from "react-router-dom";

import { OwnershipStatus } from "../../api/generated/model";
import { Button, EmptyState, ErrorState } from "../../components";
import { Page, PageCount, PageHeader, SearchBar } from "../components";
import { useTranslation } from "../../i18n";
import BookFilters from "./components/BookFilters";
import BookGrid from "./components/BookGrid";
import BookList from "./components/BookList";
import BookTable from "./components/BookTable";
import ChannelAlertBanner from "./components/ChannelAlertBanner";
import OverdueBanner from "./components/OverdueBanner";
import SavedSearches from "./components/SavedSearches";
import SelectionBar from "./components/SelectionBar";
import UnconfirmedBanner from "./components/UnconfirmedBanner";
import {
  useBookSelection,
  useBrokenSenders,
  useLibrary,
  useMyOverdue,
  useUnconfirmedCount,
} from "./hooks";
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
  const overdue = useMyOverdue();
  const brokenSenders = useBrokenSenders();
  const [showTagPanel, setShowTagPanel] = useState(false);
  // Its own flag rather than one "which panel is open" value, so opening the
  // classification panel does not close the tag panel: the two narrow the same
  // shelf and are routinely used together.
  const [showClassificationPanel, setShowClassificationPanel] = useState(false);

  const filtered = hasActiveFilters(library.filters);
  const wishlist = isWishlist(library.filters);

  /** Jump to the unconfirmed books and start ticking them off in one step. */
  function reviewUnconfirmed() {
    library.update({ ownership: OwnershipStatus.unknown });
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
          banner would be asking them to do. All three, for the same reason.

          Overdue first: a book somebody else is holding past its date is the
          one of the three with a person waiting at the other end. The broken
          channel is next because it is about the app rather than the shelf,
          and the unconfirmed nudge is last because its books are not going
          anywhere. Each renders nothing when its own count is zero, so the
          usual library page still has none of them. */}
      {!selection.isSelecting && (
        <>
          <OverdueBanner count={overdue} />
          <ChannelAlertBanner senders={brokenSenders} />
          <UnconfirmedBanner count={unconfirmed} onReview={reviewUnconfirmed} />
        </>
      )}

      <SearchBar onSearch={(query) => library.update({ query })} />

      <BookFilters
        filters={library.filters}
        tags={library.tags}
        showTagPanel={showTagPanel}
        onToggleTagPanel={() => setShowTagPanel((open) => !open)}
        classifications={library.classifications}
        showClassificationPanel={showClassificationPanel}
        onToggleClassificationPanel={() =>
          setShowClassificationPanel((open) => !open)
        }
        onToggleHeading={library.toggleHeading}
        onToggleDivision={library.toggleDivision}
        onClearClassifications={library.clearClassifications}
        onFilterChange={library.update}
        locations={library.locations}
        collections={library.collections}
        onToggleTag={library.toggleTag}
        onClearTags={library.clearTags}
        view={library.view}
        onViewChange={library.setView}
      />

      <SavedSearches
        searches={library.savedSearches}
        canSave={filtered}
        // A saved search is a complete filter set, so applying one writes
        // every field. There is no separate whole-set door for that reason.
        onApply={library.update}
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
                neither a table of twenty one columns nor a dense list is where
                somebody ticks twenty books off. Starting a selection therefore
                shows the covers again, rather than offering a selection that
                does nothing.

                Tested first for that reason: it wins over the remembered view
                whichever one that is, so a third view could not reintroduce a
                selection with nothing to tick. */}
            {selection.isSelecting || library.view === "grid" ? (
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
            ) : library.view === "table" ? (
              <BookTable
                books={library.books}
                sort={library.filters.sort}
                onSortChange={(sort) => library.update({ sort })}
                isLoading={library.isLoading}
                hasMore={library.hasMore}
                isLoadingMore={library.isLoadingMore}
                onLoadMore={library.loadMore}
              />
            ) : (
              <BookList
                books={library.books}
                isLoading={library.isLoading}
                hasMore={library.hasMore}
                isLoadingMore={library.isLoadingMore}
                onLoadMore={library.loadMore}
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
