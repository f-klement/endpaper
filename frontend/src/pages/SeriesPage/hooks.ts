/**
 * Data for the series browser.
 *
 * One query. The gap calculation lives on the server, because it has to see
 * the whole catalogue rather than whichever page the grid happens to hold.
 *
 * The ordering does not: the endpoint sorts series names by codepoint, which
 * files `Zebra` above `apple` and `Ästhetik` below both. `useSortedByName`
 * puts them where a reader looks for them.
 */

import { useListSeries } from "../../api/generated/endpoints/books/books";
import type { SeriesOut } from "../../api/generated/model";
import { useSortedByName } from "../../i18n";

export interface UseSeriesResult {
  series: SeriesOut[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export function useSeries(): UseSeriesResult {
  const query = useListSeries({ query: { retry: false } });
  const series = useSortedByName(query.data);

  return {
    series,
    isLoading: query.isPending,
    error: query.error,
    refetch: () => void query.refetch(),
  };
}
