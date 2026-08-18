/**
 * Data for the series browser.
 *
 * One query. The gap calculation lives on the server, because it has to see
 * the whole catalogue rather than whichever page the grid happens to hold.
 */

import { useListSeries } from "../../api/generated/endpoints/books/books";
import type { SeriesOut } from "../../api/generated/model";

export interface UseSeriesResult {
  series: SeriesOut[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export function useSeries(): UseSeriesResult {
  const query = useListSeries({ query: { retry: false } });

  return {
    series: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: () => void query.refetch(),
  };
}
