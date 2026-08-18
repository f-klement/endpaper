/**
 * Finding duplicate entries and folding them together.
 *
 * Detection is a suggestion, not a verdict: matching is deliberately lossy, so
 * a person picks which entry survives and the merge only happens on confirm.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  useListDuplicates,
  useMergeBooks,
} from "../../api/generated/endpoints/books/books";
import type { DuplicateGroup } from "../../api/generated/model";

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
  const queryClient = useQueryClient();
  const query = useListDuplicates({ query: { retry: false } });

  const merge = useMergeBooks({
    mutation: {
      onSuccess: () => {
        // A merge deletes rows and moves notes, loans and statuses between
        // books, so nothing cached about the catalogue survives it intact.
        void queryClient.invalidateQueries();
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
