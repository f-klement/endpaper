/**
 * Data for the library grid.
 *
 * This is the whole of Home's contact with the API. The page and its
 * components receive plain values and callbacks, so regenerating the client
 * changes this file and nothing else on the page.
 */

import { keepPreviousData } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  useBulkAction,
  useListBooks,
  useListClassifications,
  useListLocations,
  useListBooksInfinite,
  useListTags,
} from "../../api/generated/endpoints/books/books";
import { useListCollections } from "../../api/generated/endpoints/collections/collections";
import { useMyOverdue as useMyOverdueQuery } from "../../api/generated/endpoints/loans/loans";
import { useGetSenderHealth } from "../../api/generated/endpoints/settings/settings";
import { catalogueMode, type CatalogueMode } from "../../lib/catalogueMode";
import {
  AVAILABLE_COLUMNS,
  clearColumns,
  isDefaultColumns,
  readColumns,
  toggledColumns,
  writeColumns,
  type ColumnKey,
} from "../../lib/libraryColumns";
import {
  readLibraryView,
  writeLibraryView,
  type LibraryView,
} from "../../lib/libraryView";
import {
  BulkAction,
  OwnershipStatus,
  type BookOut,
  type BulkResult,
  type ClassificationFacets,
  type CollectionOut,
  type LocationOut,
  type OverdueSender,
  type SenderHealth,
  type TagOut,
} from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";
import { readFilters, toParams } from "../../lib/bookFilters";
import {
  deleteSearch,
  readSavedSearches,
  saveSearch,
  type SavedSearch,
} from "../../lib/savedSearches";
import { useFeatureFlagsState } from "../../app/hooks";
import { useToast } from "../../app/toast";
import { useSortedByName, useTranslation } from "../../i18n";
import type { BookFilters } from "./types";

/** Rows per request. Enough to fill a wide grid without over-fetching. */
export const PAGE_SIZE = 24;

export interface UseLibraryResult {
  filters: BookFilters;
  /**
   * Change one filter or several, leaving the rest alone.
   *
   * One door rather than a setter per field. Eleven of them cost the type, the
   * hook and every caller a line each to add a filter, and gave a caller
   * nothing it could not have written itself.
   *
   * Applying a saved search goes through the same door: a saved search holds a
   * complete `BookFilters`, so a patch naming every key is a replacement. That
   * is why there is no separate whole-set setter. A stored search written
   * before a field existed is the one case where the two would differ, and
   * merging is the safer of the two answers there: the missing field keeps a
   * real value rather than becoming undefined.
   */
  update: (patch: Partial<BookFilters>) => void;

  /** Filter combinations somebody named and kept. Browser-local. */
  savedSearches: SavedSearch<BookFilters>[];
  saveCurrentSearch: (name: string) => void;
  deleteSavedSearch: (id: string) => void;
  locations: LocationOut[];
  /** Every collection in the library, for the filter. */
  collections: CollectionOut[];
  toggleTag: (tagId: number) => void;
  clearTags: () => void;
  /** One heading, as `scheme:number`. ANDed with the others, like a tag. */
  toggleHeading: (heading: string) => void;
  /** One Dewey division. ORed with the others: see `docs/decisions.md`. */
  toggleDivision: (division: string) => void;
  clearClassifications: () => void;
  classifications: ClassificationFacets | undefined;

  /**
   * Covers, dense rows or metadata. Remembered per mode, in this browser rather
   * than on the account. Library mode opens on the dense rows.
   */
  view: LibraryView;
  setView: (view: LibraryView) => void;

  /** Whether this library is being catalogued or kept. See `libraryColumns`. */
  mode: CatalogueMode;
  /**
   * Whether the mode is settled, and so whether a preference may be written.
   *
   * False only while the feature flags are in flight, which on a warm cache is
   * no renders at all. Every control that writes a per-mode preference is
   * disabled meanwhile, rather than left looking live: the write is refused
   * either way, and a button that answers a press with nothing teaches the
   * reader the page lies.
   */
  modeIsKnown: boolean;
  /** Every column this mode offers, whether drawn or not. */
  availableColumns: readonly ColumnKey[];
  /** The columns the table draws. Remembered per mode, in this browser. */
  columns: readonly ColumnKey[];
  toggleColumn: (key: ColumnKey) => void;
  resetColumns: () => void;
  /** False while `columns` already is this mode's default set. */
  canResetColumns: boolean;

  books: BookOut[];
  total: number;
  tags: TagOut[];

  isLoading: boolean;
  /** Results are on screen but a newer query is still running. */
  isStale: boolean;
  error: unknown;
  refetch: () => void;

  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
}

export function useLibrary(): UseLibraryResult {
  // Read once as the initial value rather than kept in sync, so clicking a
  // filter afterwards is not fought by the URL. What the parameters mean is
  // `lib/bookFilters.ts`.
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState<BookFilters>(() =>
    readFilters(searchParams),
  );

  const update = useCallback(
    (patch: Partial<BookFilters>) =>
      setFilters((current) => ({ ...current, ...patch })),
    [],
  );

  // Read once on mount. Nothing else in the tab writes them, so re-reading
  // storage on every render would be work for no news.
  const [savedSearches, setSavedSearches] = useState(() =>
    readSavedSearches<BookFilters>(),
  );

  // **The view and the column set are derived from the mode, not held as state
  // seeded from it.** The flags are fetched, so `library_mode` is undefined for
  // the first render or two; a `useState` initialiser would capture the
  // household's answer and a cataloguer would keep it for the rest of the
  // session. Re-reading storage when the mode changes is one `getItem` each,
  // and it is what makes the two modes' choices independent rather than merely
  // separately stored.
  //
  // The cost is that a cataloguer sees the household's view and columns for a
  // render or two. That is the trade `catalogueMode` already documents and the
  // other way round is worse: every household would watch a cataloguer's
  // catalogue flash past on every load.
  //
  // **`catalogueMode(undefined)` is a fallback for reading and is not one for
  // writing**, which is `modeIsKnown` below. A cataloguer who picks a view in
  // that window would otherwise have it filed under the household's key: the
  // household loses the choice it made, the cataloguer's key stays empty, and
  // nothing says so. A wrong read costs one paint; a wrong write is permanent
  // and silent, which is the whole of what the two keys exist to prevent.
  //
  // `edits` is bumped by a write so the next render re-reads what was just
  // stored. One counter for both preferences rather than one each, so a change
  // to the columns re-reads the view as well. That is the whole cost: one
  // `getItem` that returns what it returned before. Two counters would be
  // accurate about which preference moved and nothing would read the
  // difference. Storage is the single copy, and keeping a second one in state
  // is how the two come to disagree.
  const { flags, isResolved: modeIsKnown } = useFeatureFlagsState();
  const mode = catalogueMode(flags?.library_mode);
  const [edits, setEdits] = useState(0);
  const columns = useMemo(
    () => readColumns(mode),
    // `edits` is the whole point of the dependency, not an accident.
    [mode, edits],
  );
  const view = useMemo(() => readLibraryView(mode), [mode, edits]);

  /**
   * One door for every write keyed on the mode.
   *
   * The mode is handed to the caller rather than closed over, so a write
   * cannot reach it without passing the gate, and the re-read bump happens
   * here rather than at three call sites that each had to remember it. A
   * fourth per-mode preference gets both properties by construction.
   */
  const writeForMode = useCallback(
    (write: (mode: CatalogueMode) => void) => {
      if (!modeIsKnown) return;
      write(mode);
      setEdits((count) => count + 1);
    },
    [mode, modeIsKnown],
  );

  const params = { ...toParams(filters), page_size: PAGE_SIZE };

  const books = useListBooksInfinite(params, {
    query: {
      initialPageParam: 1,
      // Keep the current results on screen while a new query runs.
      //
      // Without this, changing the search term produces a query key with no
      // cached data, so `isPending` flips true and `data` is undefined for the
      // length of the request. The grid emptied and redrew its skeletons
      // between every debounce window, which reads as a grid of books flashing
      // up for a moment with nothing in it. The results themselves were never
      // the problem; the gap between them was.
      placeholderData: keepPreviousData,
      // Stop asking once the pages so far account for every matching row.
      // Returning undefined is what tells React Query there is no next page.
      getNextPageParam: (lastPage, allPages) => {
        const loaded = allPages.reduce(
          (count, page) => count + page.items.length,
          0,
        );
        return loaded < lastPage.total ? allPages.length + 1 : undefined;
      },
    },
  });

  // Tags and locations drive the filter panel only. A failure there costs the
  // panel, not the grid, so their errors are deliberately not surfaced.
  const tags = useListTags();
  const locations = useListLocations({ query: { staleTime: 5 * 60_000 } });
  // Cached like the locations, and for the same reason: how a library has
  // divided its shelf changes far less often than what is on it.
  const collections = useListCollections({ query: { staleTime: 5 * 60_000 } });
  // Cached longer than the tags beside it. A heading arrives from a catalogue
  // during enrichment rather than from somebody typing, so this list moves when
  // books are added and not while one is being read.
  const classifications = useListClassifications({
    query: { staleTime: 5 * 60_000 },
  });
  // The filter panel and the selection bar both draw this one field, so they
  // are collated once here rather than twice at the two call sites.
  // `locations` is left alone: it arrives most-populated first, which answers
  // a different question. See `lib/nameOrder.ts`.
  const filed = useSortedByName(collections.data);

  const flatBooks = useMemo(
    () => books.data?.pages.flatMap((page) => page.items) ?? [],
    [books.data],
  );

  const total = books.data?.pages[0]?.total ?? 0;

  return {
    filters,
    update,

    savedSearches,
    saveCurrentSearch: (name) => setSavedSearches(saveSearch(name, filters)),
    deleteSavedSearch: (id) => setSavedSearches(deleteSearch(id)),
    locations: locations.data ?? [],
    collections: filed,
    toggleTag: (tagId) =>
      setFilters((current) => ({
        ...current,
        tagIds: current.tagIds.includes(tagId)
          ? current.tagIds.filter((id) => id !== tagId)
          : [...current.tagIds, tagId],
      })),
    clearTags: () => setFilters((current) => ({ ...current, tagIds: [] })),
    toggleHeading: (headingKey) =>
      setFilters((current) => ({
        ...current,
        headings: current.headings.includes(headingKey)
          ? current.headings.filter((entry) => entry !== headingKey)
          : [...current.headings, headingKey],
      })),
    toggleDivision: (division) =>
      setFilters((current) => ({
        ...current,
        ddcDivisions: current.ddcDivisions.includes(division)
          ? current.ddcDivisions.filter((entry) => entry !== division)
          : [...current.ddcDivisions, division],
      })),
    clearClassifications: () =>
      setFilters((current) => ({ ...current, headings: [], ddcDivisions: [] })),
    classifications: classifications.data,

    view,
    // Written under this mode's own key, like the columns below and for the
    // same reason: a household's view has to survive a switch into library
    // mode and back out of it, unmodified.
    setView: (next) => writeForMode((known) => writeLibraryView(known, next)),

    mode,
    modeIsKnown,
    availableColumns: AVAILABLE_COLUMNS[mode],
    columns,
    // Written under this mode's own key, so a household's choice is untouched
    // by anything a cataloguer does and the other way round. A toggle that
    // lands back on the default clears the key instead of storing a copy of
    // it, which `writeColumns` does rather than this call site: turning one
    // column off and straight back on is the ordinary way to get there.
    toggleColumn: (key) =>
      writeForMode((known) =>
        writeColumns(known, toggledColumns(known, columns, key)),
      ),
    resetColumns: () => writeForMode(clearColumns),
    canResetColumns: !isDefaultColumns(mode, columns),

    books: flatBooks,
    total,
    tags: tags.data ?? [],

    // True only when there is genuinely nothing to draw. With previous results
    // held, a re-search is no longer a loading state, it is a stale one.
    isLoading: books.isPending,
    isStale: books.isFetching && !books.isFetchingNextPage && !books.isPending,
    error: books.error,
    refetch: () => void books.refetch(),

    hasMore: books.hasNextPage,
    isLoadingMore: books.isFetchingNextPage,
    loadMore: () => void books.fetchNextPage(),
  };
}

export interface UseBookSelectionResult {
  /** Off until someone starts selecting. Off means normal navigation. */
  isSelecting: boolean;
  start: () => void;
  stop: () => void;
  selectedIds: number[];
  isSelected: (bookId: number) => boolean;
  toggle: (bookId: number) => void;
  selectAll: (bookIds: number[]) => void;
  clear: () => void;

  apply: (ownership: OwnershipStatus) => void;
  /** Any of the other bulk verbs: tagging, status, location, collection,
   * deletion. */
  run: (action: BulkAction, value?: string | number) => void;
  isApplying: boolean;
  result: BulkResult | null;
  error: unknown;
  dismissResult: () => void;
}

/**
 * Picking out several books and marking them all at once.
 *
 * Exists for one flow: import a Goodreads library, which arrives unconfirmed
 * because an export says what somebody read and not what is on their shelf,
 * then tick off the ones actually here. Doing that one book at a time across
 * a few hundred rows is not a real option.
 */
export function useBookSelection(): UseBookSelectionResult {
  const invalidate = useInvalidate();
  const toast = useToast();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [isSelecting, setIsSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const general = useBulkAction({
    mutation: {
      onSuccess: (result, variables) => {
        setSelected(new Set());
        // Every verb here writes several books at once: tagging, status,
        // shelf, collection and delete. The counts on the tag, shelf and
        // collection lists move with them, which is why this is the catalogue
        // and not just the grid.
        invalidate.catalogue();

        // Only the delete verb raises one, and it offers the trash rather than
        // an undo. Undoing a bulk delete means restoring each book in turn,
        // and a toast that quietly fires three hundred requests is not an
        // undo, it is a second bulk operation wearing its coat.
        if (variables.data.action === BulkAction.delete && result.updated > 0) {
          toast.show({
            message: t("trash.movedCount", { count: result.updated }),
            action: {
              label: t("trash.open"),
              onClick: () => navigate("/trash"),
            },
          });
        }
      },
    },
  });

  const run = useCallback(
    (action: BulkAction, value?: string | number) => {
      if (selected.size === 0) return;
      general.mutate({
        data: { book_ids: [...selected], action, value: value ?? null },
      });
    },
    [general, selected],
  );

  const stop = useCallback(() => {
    setIsSelecting(false);
    setSelected(new Set());
    general.reset();
  }, [general]);

  return {
    isSelecting,
    start: () => setIsSelecting(true),
    stop,
    selectedIds: [...selected],
    isSelected: (bookId) => selected.has(bookId),
    toggle: (bookId) =>
      setSelected((current) => {
        const next = new Set(current);
        if (!next.delete(bookId)) next.add(bookId);
        return next;
      }),
    // Only what is loaded: the grid pages, and claiming to select rows nobody
    // has seen would send ids the reader never looked at.
    selectAll: (bookIds) => setSelected(new Set(bookIds)),
    clear: () => setSelected(new Set()),

    // Ownership used to go to a second endpoint with an identical body and an
    // identical result. It is the same verb as the rest now.
    apply: (ownership) => run(BulkAction.set_ownership, ownership),
    run,
    isApplying: general.isPending,
    result: (general.data ?? null) as BulkResult | null,
    error: general.error,
    dismissResult: () => general.reset(),
  };
}

/**
 * How many overdue loans this member is being reminded about (#86).
 *
 * The in app reminder channel. Every other one pushes outward and needs
 * something the household had to obtain first, so a household with no mailbox,
 * no bot and no receiver was told nothing at all. This is the one that works on
 * a fresh install with nothing configured, which is why it ships switched on.
 *
 * Who is counted is the server's decision (`notifications.overdue_for_viewer`):
 * a member reads the loans they borrowed or lent, staff read every overdue loan
 * on their shelf, and in library mode every member reads every overdue loan in
 * the library. All three go through the Shelf, so nobody sees a private book
 * that is not theirs in any mode.
 *
 * Zero when the household switched the channel off, so the banner disappears
 * without this page having to read the admin-only settings record.
 */
export function useMyOverdue(): number {
  const query = useMyOverdueQuery({ query: { staleTime: 60_000 } });
  return query.data?.enabled ? (query.data.count ?? 0) : 0;
}

/**
 * Which reminder channels have stopped working (#82).
 *
 * **Admin only, by the endpoint rather than by a prop.** It answers 403 to
 * anybody else, so a member's query fails and this returns nothing, which is
 * the arrangement `useSettings` already has and what keeps the library page
 * from needing to know who is reading it. `retry: false` so a member costs one
 * request rather than four.
 *
 * `broken` is the server's verdict and is not recomputed here: a refusal the
 * app decided itself counts at once, a transport failure only after 24 hours
 * and at least two consecutive failures. The evidence for that lives in the
 * health record, not in this payload.
 *
 * The record changes at most once an hour, so it is held for five minutes
 * rather than refetched on every return to the library.
 */
export function useBrokenSenders(): OverdueSender[] {
  const query = useGetSenderHealth({
    query: { retry: false, staleTime: 300_000 },
  });
  return (query.data ?? [])
    .filter((entry: SenderHealth) => entry.broken)
    .map((entry: SenderHealth) => entry.sender);
}

/**
 * How many books nobody has confirmed are on the shelf.
 *
 * A count, not a list: the banner only needs the number, and asking for one
 * row is the cheapest way to get the envelope's `total`.
 */
export function useUnconfirmedCount(): number {
  const query = useListBooks(
    { ownership: OwnershipStatus.unknown, page_size: 1 },
    { query: { staleTime: 30_000 } },
  );
  return query.data?.total ?? 0;
}
