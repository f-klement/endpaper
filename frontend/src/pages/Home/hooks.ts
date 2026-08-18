/**
 * Data for the library grid.
 *
 * This is the whole of Home's contact with the API. The page and its
 * components receive plain values and callbacks, so regenerating the client
 * changes this file and nothing else on the page.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  useBulkAction,
  useBulkSetOwnership,
  useListBooks,
  useListLocations,
  useListBooksInfinite,
  useListTags,
} from "../../api/generated/endpoints/books/books";
import {
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
  /** Replace the whole filter set, for a saved view such as the wishlist. */
  setFilters: (filters: BookFilters) => void;
  locations: LocationOut[];
  setSort: (sort: BookFilters["sort"]) => void;
  toggleTag: (tagId: number) => void;
  clearTags: () => void;

  books: BookOut[];
  total: number;
  tags: TagOut[];

  isLoading: boolean;
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
      series: searchParams.get("series"),
      location: searchParams.get("location"),
    };
  });

  const params = toParams(filters);

  const books = useListBooksInfinite(params, {
    query: {
      initialPageParam: 1,
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
    setFilters: (next) => setFilters(next),
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

    isLoading: books.isPending,
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
  const [isSelecting, setIsSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const general = useBulkAction({
    mutation: {
      onSuccess: () => {
        setSelected(new Set());
        void queryClient.invalidateQueries();
      },
    },
  });

  const bulk = useBulkSetOwnership({
    mutation: {
      onSuccess: () => {
        setSelected(new Set());
        // Every list and every book detail can now be showing a stale
        // ownership value, and the count behind the banner has moved too.
        void queryClient.invalidateQueries();
      },
    },
  });

  const stop = useCallback(() => {
    setIsSelecting(false);
    setSelected(new Set());
    bulk.reset();
    general.reset();
  }, [bulk, general]);

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

    apply: (ownership) => {
      if (selected.size === 0) return;
      bulk.mutate({ data: { book_ids: [...selected], ownership } });
    },
    run: (action, value) => {
      if (selected.size === 0) return;
      general.mutate({
        data: { book_ids: [...selected], action, value: value ?? null },
      });
    },
    // Either mutation can be the one in flight, and the bar shows one result
    // area, so both are folded together here rather than in the component.
    isApplying: bulk.isPending || general.isPending,
    result: (bulk.data ?? general.data ?? null) as BulkResult | null,
    error: bulk.error ?? general.error,
    dismissResult: () => {
      bulk.reset();
      general.reset();
    },
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
