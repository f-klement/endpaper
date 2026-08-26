/**
 * Data for the cross-book quotes page.
 *
 * Read only. Editing a quote is done where it was saved, on the book it came
 * from, because that is where the page number and the passage can be checked
 * against the book in somebody's hand. A second editor here would be a second
 * place for the same rules to be got wrong.
 */

import { useListQuotes } from "../../api/generated/endpoints/books/books";
import type { QuoteWithBookOut } from "../../api/generated/model";

/** Rows per request. Enough that a library's whole shelf of quotes is one
 * or two pages, and inside the API's own ceiling of 200. */
export const QUOTES_PER_PAGE = 50;

export interface UseAllQuotesResult {
  quotes: QuoteWithBookOut[];
  total: number;
  page: number;
  pageCount: number;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export function useAllQuotes(page: number): UseAllQuotesResult {
  const query = useListQuotes(
    { page, page_size: QUOTES_PER_PAGE },
    {
      query: {
        retry: false,
        // Keep the page that is on screen while the next one is fetched. The
        // page number is part of the query key, so without this every paging
        // click drops the whole list back to a spinner and takes the heading
        // with it, which reads as the page reloading rather than as it turning.
        placeholderData: (previous) => previous,
      },
    },
  );

  const total = query.data?.total ?? 0;

  return {
    quotes: query.data?.items ?? [],
    total,
    page,
    // At least one, so an empty shelf reads as "page 1 of 1" rather than
    // "page 1 of 0", and the paging controls have something coherent to
    // disable against.
    pageCount: Math.max(1, Math.ceil(total / QUOTES_PER_PAGE)),
    isLoading: query.isPending,
    error: query.error,
    refetch: () => void query.refetch(),
  };
}
