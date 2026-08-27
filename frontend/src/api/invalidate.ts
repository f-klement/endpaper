/**
 * What a write makes stale.
 *
 * Every mutation in the app has to say which cached queries its write
 * invalidated. Eleven of them said "all of them", by calling
 * `queryClient.invalidateQueries()` with no key, and that is not free: a
 * keyless invalidate refetches every **mounted** query on the page, whatever
 * it is about and whatever staleTime it was given.
 *
 * Measured on 2026-08-26, with the suite's own network stub counting requests:
 *
 * | Flow | Mounted queries | Refetched, keyless | Refetched, narrowed |
 * |---|---|---|---|
 * | BookDetail, delete a curated tag | 10 | 10 | 5 |
 * | BookDetail, undo a delete | 10 | 10 | 5 |
 * | ScanPage, confirm a book found by search | 4 | 4 | 2 |
 *
 * The scan row is the one that costs money rather than time. `useSearchBooks`
 * carries `staleTime: 5 * 60_000` and a comment saying that going back to edit
 * a draft must not re-spend the Google Books quota. An invalidate ignores
 * staleTime, so confirming a book found by search re-ran the search: one
 * billed call per book added that way, and the comment was describing
 * something that had stopped being true.
 *
 * So the vocabulary here is four groups, smallest first, and the call sites
 * pick one instead of assembling keys. What each one covers is a fact about
 * this API and is stated once, here.
 */

import { useMemo } from "react";

import {
  useQueryClient,
  type Query,
  type QueryClient,
} from "@tanstack/react-query";

import {
  getListAuthorSuggestionsQueryKey,
  getListAuthorsQueryKey,
  getGetBookQueryKey,
  getListBooksInfiniteQueryKey,
  getListBooksQueryKey,
  getListCopiesQueryKey,
  getListDuplicatesQueryKey,
  getListLocationsQueryKey,
  getListQuotesQueryKey,
  getListSeriesQueryKey,
  getListTagsQueryKey,
  getListTrashQueryKey,
} from "./generated/endpoints/books/books";
import { getListCollectionsQueryKey } from "./generated/endpoints/collections/collections";
import { getListLoansQueryKey } from "./generated/endpoints/loans/loans";
import { getGetStatsQueryKey } from "./generated/endpoints/stats/stats";

/**
 * The marker orval puts in front of an infinite query's path.
 *
 * Read off a generated key rather than written as `"infinite"`, because it is
 * the whole reason this module exists. The library grid is
 * `useListBooksInfinite`, whose key is `["infinite", "/api/books", params]`,
 * and react-query matches a filter key element by element: `["/api/books"]`
 * compares `"/api/books"` against `"infinite"` and does not match. Four call
 * sites invalidated `["/api/books"]` by hand, each with a comment about
 * dropping "the book caches", and all four missed the grid, which is the book
 * cache a reader actually looks at.
 */
const INFINITE = getListBooksInfiniteQueryKey()[0];

/** The endpoint path a key is about, with the infinite marker stepped over. */
function pathOf(query: Query): unknown {
  const [first, second] = query.queryKey;
  return first === INFINITE ? second : first;
}

/** Both spellings of the library list: the paginated one and the grid. */
const BOOKS = getListBooksQueryKey()[0];

/**
 * The library-wide views derived from the books table.
 *
 * Every one of these is a list or a count over books, so adding, removing or
 * editing a book changes it. `TagOut`, `LocationOut` and `CollectionOut` all
 * carry a `book_count`, which is why the tag, shelf and collection lists are
 * here rather than treated as separate vocabularies.
 *
 * Paths only, so a key carrying paging or filter parameters matches the same
 * way a bare one does.
 */
const LIBRARY_WIDE: ReadonlySet<unknown> = new Set([
  BOOKS,
  getListAuthorsQueryKey()[0],
  getListAuthorSuggestionsQueryKey()[0],
  getListSeriesQueryKey()[0],
  getListLocationsQueryKey()[0],
  getListDuplicatesQueryKey()[0],
  getListTagsQueryKey()[0],
  getListTrashQueryKey()[0],
  getListQuotesQueryKey()[0],
  getListCollectionsQueryKey()[0],
  getGetStatsQueryKey()[0],
  getListLoansQueryKey()[0],
]);

/**
 * One book's own record, for any book.
 *
 * A wide invalidate has no id to hand, so this is a pattern rather than a key.
 * `copies` is here and the other children of `/api/books/{id}` are not: a copy
 * list is a list of books and moves when the catalogue does, whereas notes,
 * quotes, progress and enrichment candidates change only when written through
 * their own hooks, which invalidate them there. `tests/api/invalidate.test.ts`
 * pins both halves of that.
 *
 * **One endpoint breaks that sentence, and it is why `everything()` exists.**
 * Merging duplicates writes all four without going through any of those hooks:
 * it moves a deleted book's notes, quotes, progress and reading statuses onto
 * the survivor. So `DuplicatesPage` does not call this group.
 */
const BOOK_RECORD = /^\/api\/books\/\d+(\/copies)?$/;

/**
 * Whether a cached query is part of the catalogue.
 *
 * Exported for the inventory test, which walks every query key the generated
 * client can produce and asserts each one is classified deliberately. That
 * test is the guard on the two exclusions below, both of which are outward
 * calls this app does not own: `/api/books/lookup` (Open Library) and
 * `/api/books/search` (Google Books, billed). Neither is derived from the
 * books table, so neither belongs to any write, and a third one arriving
 * unclassified fails that test rather than quietly joining every invalidate.
 */
export function isCatalogueQuery(query: Query): boolean {
  const path = pathOf(query);
  if (LIBRARY_WIDE.has(path)) return true;
  return typeof path === "string" && BOOK_RECORD.test(path);
}

export interface Invalidate {
  /**
   * The library list, in both its spellings.
   *
   * For a write that changes what a book row says without changing which
   * books exist: a merged author, a returned loan, a renamed collection.
   */
  listings: () => void;

  /**
   * One book, and the lists that show it.
   *
   * The record and its copies, plus the listings, the loans and the
   * statistics: a status or ownership change is counted by `/api/stats`, and
   * that page is one tap away.
   */
  book: (bookId: number) => void;

  /**
   * Everything this API derives from the books table.
   *
   * For a write that changes which books exist or what several of them say:
   * adding, deleting, restoring, importing, a bulk action, a curated tag
   * removed from every book, or an edit to a field the indexes are built from
   * (author, series, shelf).
   */
  catalogue: () => void;

  /**
   * The whole cache, accounts and settings included.
   *
   * Two callers, and both earn it: restoring a backup replaces every row in
   * the database, and merging duplicates moves notes, loans and reading
   * statuses between books with no viewer-independent account of what moved.
   */
  everything: () => void;
}

/** The vocabulary above, bound to this render's client. */
export function useInvalidate(): Invalidate {
  const queryClient = useQueryClient();
  return useMemo(() => invalidateWith(queryClient), [queryClient]);
}

/** The same vocabulary outside a component, for a caller holding a client. */
export function invalidateWith(queryClient: QueryClient): Invalidate {
  const drop = (predicate: (query: Query) => boolean) =>
    void queryClient.invalidateQueries({ predicate });

  return {
    listings: () => drop((query) => pathOf(query) === BOOKS),

    book: (bookId) => {
      // Built from the generated key getters rather than by pasting the paths
      // together, so a regeneration that moves an endpoint moves this with it.
      const own = new Set<unknown>([
        getGetBookQueryKey(bookId)[0],
        getListCopiesQueryKey(bookId)[0],
        BOOKS,
        getListLoansQueryKey()[0],
        getGetStatsQueryKey()[0],
      ]);
      drop((query) => own.has(pathOf(query)));
    },

    catalogue: () => drop(isCatalogueQuery),

    // The only keyless invalidate in the app. `houseRules.test.ts` holds that.
    everything: () => void queryClient.invalidateQueries(),
  };
}
