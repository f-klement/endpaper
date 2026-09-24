/**
 * Data for the library grid, and the choices this browser remembers about it.
 *
 * This is the whole of Home's contact with the API. The page and its
 * components receive plain values and callbacks, so regenerating the client
 * changes this file and nothing else on the page.
 *
 * **`useLibrary` returns the library and nothing a browser remembered.** Every
 * member of it is a request or something derived from one, and the remembered
 * choices are the three hooks below it, each of which is one cluster behind one
 * name. It had grown the other way: ten of its members were a view, a column
 * set and a list of saved searches, and the interface, the page and two panels
 * each paid a line per member. `tests/pages/Home/hooks.test.tsx` holds the rule
 * as a guard, because a preference read through this hook works, so no other
 * test would see it come back.
 *
 * **Where the counter went.** Two of those preferences were derived from the
 * mode on every render and a counter was bumped by every write so the next
 * render would re-read what had just been stored. `lib/preference.ts` notifies
 * its readers instead, so the counter, the wrapper that bumped it and the
 * comment explaining both are gone. What was load bearing in that comment did
 * not go with it: that the mode is fetched and so a state initialiser would
 * capture the household's answer, and that a fallback for reading is not one for
 * writing, are now `useCatalogueScope` in `app/hooks.ts`.
 */

import { keepPreviousData } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  useCatalogueScope,
  usePreference,
  useScopedPreference,
  type RememberedPerScope,
} from "../../app/hooks";

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
import {
  AVAILABLE_COLUMNS,
  DEFAULT_COLUMNS,
  isDefaultColumns,
  libraryColumnsPreference,
  toggledColumns,
  type ColumnKey,
} from "../../lib/libraryColumns";
import type { CatalogueMode } from "../../lib/catalogueMode";
import { libraryViewPreference, type LibraryView } from "../../lib/libraryView";
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
  savedSearchesPreference,
  withSearchDeleted,
  withSearchSaved,
  type SavedSearch,
} from "../../lib/savedSearches";
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
   * is why there is no separate whole-set setter.
   *
   * **A search stored before a field existed is now a replacement too, where it
   * used to be a merge, and the reason the merge was safer has gone.** The
   * stored entry was parsed and cast, so a field a later version added was
   * simply absent from the patch and the spread left whatever the reader
   * currently had. That was chosen because the alternative was `undefined`
   * reaching `toParams`. Entries are rebuilt from `DEFAULT_FILTERS` outwards
   * now, so every field is present with a real value and `undefined` cannot
   * arise; what the old behaviour actually delivered was a blend of the saved
   * view and the reader's current one, which is not the view they named.
   * Applying a saved search gives that search.
   *
   * A control that picks one value out of a list filter comes through here too,
   * with the patch `lib/bookFilters.ts` builds for it.
   */
  update: (patch: Partial<BookFilters>) => void;

  locations: LocationOut[];
  /** Every collection in the library, for the filter. */
  collections: CollectionOut[];
  classifications: ClassificationFacets | undefined;

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

    locations: locations.data ?? [],
    collections: filed,
    classifications: classifications.data,

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

/**
 * Covers, dense rows or metadata, remembered per mode in this browser.
 *
 * Handed to the filter panel as one value rather than as a value, a setter and a
 * flag, which is three props for one choice. `canSet` is false only while the
 * feature flags are in flight, and the panel draws the buttons disabled on it:
 * the write is refused either way, and a control that answers a press with
 * nothing teaches the reader the page lies.
 */
export function useViewChoice(): RememberedPerScope<
  CatalogueMode,
  LibraryView
> {
  return useScopedPreference(libraryViewPreference, useCatalogueScope());
}

/** Which columns the table draws, which it could draw, and how to change that. */
export interface ColumnChoice {
  /** The columns the table draws. */
  columns: readonly ColumnKey[];
  /** Every column this mode offers, whether drawn or not. */
  available: readonly ColumnKey[];
  /** Whether this already is the mode's default set, so no reset is offered. */
  isDefault: boolean;
  toggle: (key: ColumnKey) => void;
  reset: () => void;
  /** False while the mode is unsettled. See `useViewChoice`. */
  canChange: boolean;
}

/**
 * The column set for whichever reader this catalogue is being drawn for.
 *
 * **One name where the library hook offered five.** `available` and `isDefault`
 * are derived from the set and the mode, so as members of a hook that also
 * returned both they were lines a caller could have written. They are not
 * deleted: the caller that needs them is the picker, which has no mode of its
 * own, and handing it the mode so it could index a record would be making a
 * caller learn something rather than stop knowing it.
 *
 * **`reset` writes the default rather than removing the key.** Those are the
 * same operation, because the column preference clears its key on a set equal to
 * the default, and they were two exported names saying so separately.
 *
 * **`mode` below is the reading mode**, which is the household before the flags
 * land, and it is what `available` and `isDefault` are drawn from: a wrong read
 * there costs one paint.
 *
 * **Both writers take the mode they are written under rather than that one**,
 * through `setFromScope`. The gate would refuse a write in that window anyway,
 * so this is not what makes it safe today; it is what stops the gate being the
 * only thing that does. A reset computed from a stale household mode and stored
 * under the cataloguer's scope is not equal to the cataloguer's default, so it
 * would be stored rather than clear the key, and the reset control would stay
 * drawn and never reset.
 */
export function useColumnChoice(): ColumnChoice {
  const scope = useCatalogueScope();
  const remembered = useScopedPreference(libraryColumnsPreference, scope);
  const mode = scope ?? libraryColumnsPreference.whenUnknown;
  const columns = remembered.value;
  return {
    columns,
    available: AVAILABLE_COLUMNS[mode],
    isDefault: isDefaultColumns(mode, columns),
    toggle: (key) =>
      remembered.setFromScope((known) => toggledColumns(known, columns, key)),
    reset: () => remembered.setFromScope((known) => DEFAULT_COLUMNS[known]),
    canChange: remembered.canSet,
  };
}

/** Filter combinations somebody named and kept, and the two verbs for them. */
export interface SavedSearchChoice {
  searches: readonly SavedSearch[];
  save: (name: string) => void;
  remove: (id: string) => void;
}

/**
 * The saved views, kept in this browser rather than on the account.
 *
 * Takes the filters rather than reading them, because what "save" means is the
 * set currently on screen, and this hook has no view of that. The two verbs are
 * pure functions over the list applied through one write, so the rules about
 * names and the cap are testable without a browser.
 *
 * Not keyed on anything, so there is no window in which a write is refused.
 */
export function useSavedSearches(filters: BookFilters): SavedSearchChoice {
  const remembered = usePreference(savedSearchesPreference);
  const searches = remembered.value;
  return {
    searches,
    save: (name) => remembered.set(withSearchSaved(searches, name, filters)),
    remove: (id) => remembered.set(withSearchDeleted(searches, id)),
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
