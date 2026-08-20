/**
 * The two books the picker previews a look on.
 *
 * Read out of the query cache and never fetched. The reason is the whole
 * argument for previewing on a page rather than in a swatch: invented sample
 * content is not the real page, and a request made to fill a preview would put
 * a book on screen that the reader has not asked for and cannot get to.
 *
 * The cache is Home's, so the two books are the two the reader saw first. It is
 * empty more often than "has never opened the library": React Query's default
 * `gcTime` is five minutes and `query-client.ts` does not raise it, so a reload
 * on this route, or five idle minutes in Settings, leaves nothing here for
 * somebody whose shelf is full. The empty state says the books are not loaded
 * rather than blaming the reader for not having opened anything.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getListBooksInfiniteQueryKey,
  getListBooksQueryKey,
} from "../../api/generated/endpoints/books/books";
import type { BookOut, PageBookOut } from "../../api/generated/model";

/**
 * The two key prefixes a book listing is cached under, with no parameters.
 *
 * Built rather than written out, so a change of route or of orval's key shape
 * moves this with it. `findAll` matches on a prefix, so dropping the parameters
 * is what widens these from one filter combination to every one of them: the
 * reader's first two books are whichever listing they happen to have open.
 */
const BOOK_LIST_KEYS = [
  getListBooksInfiniteQueryKey(),
  getListBooksQueryKey(),
] as const;

/**
 * Whatever a cached listing holds, as books.
 *
 * Two shapes, because two hooks write here: Home pages through
 * `useListBooksInfinite`, which stores `{ pages: [...] }`, and everything else
 * uses `useListBooks`, which stores one page. Neither is asked for by name:
 * this reads whichever is there.
 */
function booksIn(data: unknown): BookOut[] {
  const page = data as Partial<PageBookOut> | undefined;
  if (Array.isArray(page?.items)) return page.items;

  const infinite = data as { pages?: Partial<PageBookOut>[] } | undefined;
  const first = infinite?.pages?.[0];
  return Array.isArray(first?.items) ? first.items : [];
}

/**
 * The reader's own first `count` books, or fewer, or none.
 *
 * Not a query, so it does not subscribe: the picker re-renders on every choice
 * anyway, and a subscription to the whole book cache would re-render it on
 * every write elsewhere in the app.
 */
export function usePreviewBooks(count: number): BookOut[] {
  const cache = useQueryClient().getQueryCache();

  for (const queryKey of BOOK_LIST_KEYS) {
    for (const entry of cache.findAll({ queryKey })) {
      const books = booksIn(entry.state.data);
      if (books.length > 0) return books.slice(0, count);
    }
  }
  return [];
}
