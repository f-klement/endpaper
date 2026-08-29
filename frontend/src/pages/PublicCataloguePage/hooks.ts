/**
 * The public catalogue's data, and the only file here that touches the client.
 *
 * Nothing outside a `hooks.ts` imports from `api/generated/endpoints`, and this
 * page is no exception to that rule despite being the one page a stranger can
 * open.
 *
 * **No token is attached and none is needed.** `customFetch` sends an
 * `Authorization` header only when one is stored, so these calls are identical
 * whether a member happens to be signed in or not. They are also the only calls
 * in the app that answer 404 rather than 401 when they are refused, because an
 * unpublished catalogue must not confirm that this deployment has one.
 */

import { keepPreviousData } from "@tanstack/react-query";

import {
  useGetPublicBook,
  useListPublicBooksInfinite,
} from "../../api/generated/endpoints/public/public";
import type { PublicBookOut } from "../../api/generated/model";
import { ApiError } from "../../api/mutator";

/** How many records one page of the public catalogue holds. */
export const PUBLIC_PAGE_SIZE = 24;

export interface UsePublicCatalogueResult {
  /** Every page fetched so far, flattened, in order. */
  books: PublicBookOut[];
  total: number;
  /** True while the first page is on its way, not while a later one is. */
  isLoading: boolean;
  error: unknown;
  /** True when the server said there is no published catalogue here. */
  isClosed: boolean;
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
}

/**
 * The published catalogue, page by page, accumulating.
 *
 * **An infinite query, and the first version was a plain one.** That version
 * returned a single page and nothing accumulated, so "Show more" replaced the
 * results instead of adding to them; worse, with no cached data for the new
 * page's key, `total` was 0 for the length of the request, which made
 * `hasMore` false, took the button out of the DOM under the reader who had
 * just pressed it and dropped focus to `body`. `Home/hooks.ts` had already met
 * that and its comment names it.
 *
 * `keepPreviousData` is what holds the list still while a new search runs. The
 * grid emptying and redrawing between debounce windows is a visual bug there
 * and a focus bug here.
 *
 * **More pages arrive behind a button, never by scrolling**, which is the
 * page's decision rather than this hook's; what this owes it is a `loadMore`
 * that can be called from one and a `hasMore` that does not flicker.
 */
export function usePublicCatalogue(query: string): UsePublicCatalogueResult {
  const result = useListPublicBooksInfinite(
    { q: query || undefined, page_size: PUBLIC_PAGE_SIZE },
    {
      query: {
        initialPageParam: 1,
        placeholderData: keepPreviousData,
        // `retry: false` so a closed catalogue answers immediately rather than
        // after three attempts at a 404 that is never going to change.
        retry: false,
        staleTime: 60_000,
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
    },
  );

  const books = result.data?.pages.flatMap((page) => page.items) ?? [];

  return {
    books,
    total: result.data?.pages[0]?.total ?? 0,
    isLoading: result.isLoading,
    error: result.error,
    isClosed: isNotFound(result.error),
    // React Query's own answer, not arithmetic over a `total` that is 0 while a
    // request is in flight. That arithmetic is what unmounted the button.
    hasMore: result.hasNextPage,
    isLoadingMore: result.isFetchingNextPage,
    loadMore: () => void result.fetchNextPage(),
  };
}

export interface UsePublicBookResult {
  book: PublicBookOut | undefined;
  isLoading: boolean;
  error: unknown;
  /** A book that is not published, does not exist, or is in the trash. */
  isMissing: boolean;
}

/**
 * One published record.
 *
 * `isMissing` collapses three server answers into one, deliberately: the
 * backend answers 404 for a book that never existed, one somebody trashed and
 * one a member marked private, so that a stranger cannot count through ids to
 * learn how many private books a library holds. A client that told them apart
 * would give back exactly what the server withheld.
 */
export function usePublicBook(bookId: number): UsePublicBookResult {
  const result = useGetPublicBook(bookId, {
    query: { retry: false, staleTime: 60_000 },
  });

  return {
    book: result.data,
    isLoading: result.isLoading,
    error: result.error,
    isMissing: isNotFound(result.error),
  };
}

/**
 * Whether a failure was the server saying "there is nothing here".
 *
 * Orval types the error as the endpoint's declared error body rather than as
 * what the mutator actually throws, so the status is only reachable through
 * this guard. Same shape as `useSettings().isForbidden`.
 */
function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}
