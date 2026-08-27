/**
 * Finding duplicate entries and folding them together.
 *
 * Detection is a suggestion, not a verdict: matching is deliberately lossy, so
 * a person picks which entry survives and the merge only happens on confirm.
 */

import {
  useListDuplicates,
  useMergeBooks,
} from "../../api/generated/endpoints/books/books";
import type { DuplicateGroup } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";

export interface UseDuplicatesResult {
  groups: DuplicateGroup[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  merge: (bookIds: number[], keepId: number) => void;
  isMerging: boolean;
  mergeError: unknown;
  hasMerged: boolean;
}

export function useDuplicates(): UseDuplicatesResult {
  const invalidate = useInvalidate();
  const query = useListDuplicates({ query: { retry: false } });

  const merge = useMergeBooks({
    mutation: {
      onSuccess: () => {
        // One of the two writes that earns the whole cache. A merge deletes
        // rows and moves notes, loans, quotes and reading statuses between
        // books, and the response says which book survived but not which
        // children moved, so there is nothing narrower to name. This page
        // holds one query, so the cost is the shell and no more.
        invalidate.everything();
      },
    },
  });

  return {
    groups: query.data ?? [],
    isLoading: query.isPending,
    error: query.error,
    refetch: () => void query.refetch(),

    merge: (bookIds, keepId) =>
      merge.mutate({ data: { book_ids: bookIds, keep_id: keepId } }),
    isMerging: merge.isPending,
    mergeError: merge.error,
    hasMerged: merge.isSuccess,
  };
}
