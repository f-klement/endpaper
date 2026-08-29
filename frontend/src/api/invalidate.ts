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
import {
  getListLoansQueryKey,
  getListOverdueQueryKey,
  getMyOverdueQueryKey,
} from "./generated/endpoints/loans/loans";
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
  // The in app overdue count, which the library page draws as a banner. It is
  // a count over loans and books, so it moves when a book is trashed or a loan
  // comes back, and it is the one entry here whose staleness a reader meets
  // before they meet any list: the banner is above the grid.
  getMyOverdueQueryKey()[0],
  // The overdue page's own list (#102). Same reasoning as the count above it,
  // one level of detail down: it is a list over loans and books, so a returned
  // loan or a trashed book changes it. Separate from `listLoans` because it is
  // a separate path, and react-query matches on the path.
  getListOverdueQueryKey()[0],
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
 * test is the guard on the four exclusions below, all of which are outward
 * calls this app does not own: `/api/books/lookup` (Open Library),
 * `/api/books/search` (Google Books, billed), `/api/authors/authority` (lobid
 * and Wikidata, rate limited at 10 a minute) and `/api/authors/wikipedia`
 * (Wikidata, sharing that same counter). None is derived from the books table,
 * so none belongs to any write, and a fifth one arriving unclassified fails
 * that test rather than quietly joining every invalidate.
 *
 * **The third and the fourth both arrived exactly that way.** `authorAuthority`
 * landed with the author identifier work and `authorWikipedia` with the author
 * card's outward link, and the inventory assertion failed on each in turn,
 * which is why this sentence can be written in the past tense twice.
 *
 * **The fourth is the one whose cost is paid on a page render** rather than on
 * a deliberate act, so an invalidate would spend a member's confirmation budget
 * by navigation. That is the sharpest version of what this list is for.
 *
 * **The published catalogue is outside all of this too, and for a different
 * reason, which is why it is a separate paragraph rather than a fifth item
 * above.** Those four cannot be made stale by a write. `/api/public/books` and
 * `/api/public/books/{id}` can: editing a book does change what a visitor sees.
 * They are excluded because of who pays for the refresh. They are the only
 * queries here with no session behind them, answered under a rate limit keyed
 * on the **source address**, which behind a reverse proxy is close to a global
 * cap shared with every real visitor; joining the catalogue group would make a
 * signed-in member's writes spend that budget, and a bulk import could 429 the
 * catalogue for the people it was published for.
 *
 * What that gives up is bounded: a signed-out reader never invalidates anything,
 * so the only client holding both is an admin previewing, and both public hooks
 * carry a sixty second `staleTime`. **It falls out of the path predicates today
 * rather than out of a rule**, since `BOOK_RECORD` is anchored at
 * `^/api/books/` and `/api/public/books` is not in `LIBRARY_WIDE`, so
 * `tests/api/invalidate.test.ts` pins it as a decision instead of leaving it an
 * accident of path shape.
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
   * The lending views, and the library list that draws a loan.
   *
   * For a write that changes who has what: a loan recorded, a loan returned.
   * The loans list, the overdue list and the in app count, plus the library
   * listings, because a book row draws its own `active_loan`.
   *
   * **One group rather than the same four keys assembled at each call site.**
   * The loans page and the overdue page perform the identical write, and
   * spelling out what it makes stale twice is how the second one comes to be
   * missing a key: the loans page invalidated the count and the list and not
   * the overdue page's own list, which is a screen going stale behind a
   * reader's back button.
   */
  loans: () => void;

  /**
   * One book, and the lists that show it.
   *
   * The record and its copies, plus the listings, the loans, the statistics
   * and the in app overdue count: a status or ownership change is counted by
   * `/api/stats`, and that page is one tap away.
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

    loans: () => {
      const own = new Set<unknown>([
        BOOKS,
        getListLoansQueryKey()[0],
        getListOverdueQueryKey()[0],
        getMyOverdueQueryKey()[0],
      ]);
      drop((query) => own.has(pathOf(query)));
    },

    book: (bookId) => {
      // Built from the generated key getters rather than by pasting the paths
      // together, so a regeneration that moves an endpoint moves this with it.
      const own = new Set<unknown>([
        getGetBookQueryKey(bookId)[0],
        getListCopiesQueryKey(bookId)[0],
        BOOKS,
        getListLoansQueryKey()[0],
        getGetStatsQueryKey()[0],
        // Returning a loan from a book page is the commonest way the overdue
        // banner stops being true, and it is drawn on the page the reader goes
        // back to.
        getMyOverdueQueryKey()[0],
        // And the list that banner links to, for the same reason: a loan
        // returned from a book page is a row that has to leave that page.
        getListOverdueQueryKey()[0],
      ]);
      drop((query) => own.has(pathOf(query)));
    },

    catalogue: () => drop(isCatalogueQuery),

    // The only keyless invalidate in the app. `houseRules.test.ts` holds that.
    everything: () => void queryClient.invalidateQueries(),
  };
}
