/**
 * Data for the library grid.
 *
 * This is the whole of Home's contact with the API. The page and its
 * components receive plain values and callbacks, so regenerating the client
 * changes this file and nothing else on the page.
 */

import { keepPreviousData, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  useBulkAction,
  useListBooks,
  useListLocations,
  useListBooksInfinite,
  useListTags,
} from "../../api/generated/endpoints/books/books";
import {
  BookFormat,
  BulkAction,
  OwnershipStatus,
  ReadStatus,
  type BookOut,
  type BulkResult,
  type ListBooksParams,
  type LocationOut,
  type TagOut,
} from "../../api/generated/model";
import { BookSort } from "../../api/generated/model";
import {
  deleteSearch,
  readSavedSearches,
  saveSearch,
  type SavedSearch,
} from "../../lib/savedSearches";
import { useToast } from "../../app/toast";
import { useTranslation } from "../../i18n";
import { DEFAULT_FILTERS, type BookFilters } from "./types";

/** Rows per request. Enough to fill a wide grid without over-fetching. */
export const PAGE_SIZE = 24;

function toParams(filters: BookFilters): ListBooksParams {
  return {
    // Empty values are omitted rather than sent blank, so the query key (and
    // therefore the cache entry) is the same as an unfiltered request.
    ...(filters.query ? { q: filters.query } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.ownership ? { ownership: filters.ownership } : {}),
    ...(filters.series ? { series: filters.series } : {}),
    ...(filters.location ? { location: filters.location } : {}),
    ...(filters.format ? { format: filters.format } : {}),
    ...(filters.tagIds.length ? { tags: filters.tagIds.join(",") } : {}),
    sort: filters.sort,
    page_size: PAGE_SIZE,
  };
}

export interface UseLibraryResult {
  filters: BookFilters;
  setQuery: (query: string) => void;
  setStatus: (status: BookFilters["status"]) => void;
  setOwnership: (ownership: BookFilters["ownership"]) => void;
  setSeries: (series: BookFilters["series"]) => void;
  setLocation: (location: BookFilters["location"]) => void;
  setFormat: (format: BookFilters["format"]) => void;
  /** Replace the whole filter set, for a saved view such as the wishlist. */
  setFilters: (filters: BookFilters) => void;

  /** Filter combinations somebody named and kept. Browser-local. */
  savedSearches: SavedSearch<BookFilters>[];
  saveCurrentSearch: (name: string) => void;
  deleteSavedSearch: (id: string) => void;
  locations: LocationOut[];
  setSort: (sort: BookFilters["sort"]) => void;
  toggleTag: (tagId: number) => void;
  clearTags: () => void;

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

function isStatus(value: string | null): value is ReadStatus {
  return (
    value !== null && (Object.values(ReadStatus) as string[]).includes(value)
  );
}

function isSort(value: string | null): value is BookSort {
  return (
    value !== null && (Object.values(BookSort) as string[]).includes(value)
  );
}

function isFormat(value: string | null): value is BookFormat {
  return (
    value !== null && (Object.values(BookFormat) as string[]).includes(value)
  );
}

function isOwnership(value: string | null): value is OwnershipStatus {
  return (
    value === OwnershipStatus.owned ||
    value === OwnershipStatus.not_owned ||
    value === OwnershipStatus.unknown
  );
}

export function useLibrary(): UseLibraryResult {
  // `?ownership=unknown` is a real entry point, not decoration: it is the link
  // the Goodreads import result offers, and the banner below uses the same one.
  // Read once as the initial value rather than kept in sync, so clicking a
  // filter afterwards is not fought by the URL.
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState<BookFilters>(() => {
    const ownership = searchParams.get("ownership");
    const sort = searchParams.get("sort");
    const status = searchParams.get("status");
    return {
      ...DEFAULT_FILTERS,
      ...(isOwnership(ownership) ? { ownership } : {}),
      ...(isStatus(status) ? { status } : {}),
      ...(isSort(sort) ? { sort } : {}),
      ...(isFormat(searchParams.get("format"))
        ? { format: searchParams.get("format") as BookFormat }
        : {}),
      series: searchParams.get("series"),
      location: searchParams.get("location"),
    };
  });

  // Read once on mount. Nothing else in the tab writes them, so re-reading
  // storage on every render would be work for no news.
  const [savedSearches, setSavedSearches] = useState(() =>
    readSavedSearches<BookFilters>(),
  );

  const params = toParams(filters);

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

  const flatBooks = useMemo(
    () => books.data?.pages.flatMap((page) => page.items) ?? [],
    [books.data],
  );

  const total = books.data?.pages[0]?.total ?? 0;

  return {
    filters,
    setQuery: (query) => setFilters((current) => ({ ...current, query })),
    setStatus: (status) => setFilters((current) => ({ ...current, status })),
    setOwnership: (ownership) =>
      setFilters((current) => ({ ...current, ownership })),
    setSeries: (series) => setFilters((current) => ({ ...current, series })),
    setLocation: (location) =>
      setFilters((current) => ({ ...current, location })),
    setFormat: (format) => setFilters((current) => ({ ...current, format })),
    setFilters: (next) => setFilters(next),

    savedSearches,
    saveCurrentSearch: (name) => setSavedSearches(saveSearch(name, filters)),
    deleteSavedSearch: (id) => setSavedSearches(deleteSearch(id)),
    locations: locations.data ?? [],
    setSort: (sort) => setFilters((current) => ({ ...current, sort })),
    toggleTag: (tagId) =>
      setFilters((current) => ({
        ...current,
        tagIds: current.tagIds.includes(tagId)
          ? current.tagIds.filter((id) => id !== tagId)
          : [...current.tagIds, tagId],
      })),
    clearTags: () => setFilters((current) => ({ ...current, tagIds: [] })),

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
  /** Any of the other bulk verbs: tagging, status, location, deletion. */
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
  const queryClient = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [isSelecting, setIsSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const general = useBulkAction({
    mutation: {
      onSuccess: (result, variables) => {
        setSelected(new Set());
        void queryClient.invalidateQueries();

        // Only the delete verb raises one, and it offers the trash rather than
        // an undo. Undoing a bulk delete means restoring each book in turn,
        // and a toast that quietly fires three hundred requests is not an
        // undo, it is a second bulk operation wearing its coat.
        if (variables.data.action === BulkAction.delete && result.updated > 0) {
          toast.show({
            message: t("trash.movedCount", { count: result.updated }),
            action: { label: t("trash.open"), onClick: () => navigate("/trash") },
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
    apply: (ownership) =>
      run(BulkAction.set_ownership, ownership),
    run,
    isApplying: general.isPending,
    result: (general.data ?? null) as BulkResult | null,
    error: general.error,
    dismissResult: () => general.reset(),
  };
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
