/**
 * The trash page's whole contact with the API.
 *
 * Deleting is reversible now, so this is where a book goes to be put back or
 * finished off. The two verbs are deliberately different weights: restoring is
 * one tap, deleting for good asks first, because that one really is final.
 */

import {
  getPurgeBookMutationKey,
  getRestoreBookMutationKey,
  useEmptyTrash,
  useListTrash,
  usePurgeBook,
  useRestoreBook,
  type PurgeBookMutationVariables,
  type RestoreBookMutationVariables,
} from "../../api/generated/endpoints/books/books";
import type { BookOut } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";
import { useToast } from "../../app/toast";
import { useTranslation } from "../../i18n";
import { usePendingRows, useWriteFailure } from "../hooks";

/** Rows per request. The trash is small and read top-down. */
export const PAGE_SIZE = 50;

export interface UseTrashResult {
  books: BookOut[];
  total: number;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  restore: (bookId: number) => void;
  purge: (bookId: number) => void;
  empty: () => void;
  /**
   * Every book with a put back or a delete still out, so each such row shows
   * it and refuses a second press until that write answers.
   */
  busyIds: ReadonlySet<number>;
  isEmptying: boolean;
}

export function useTrash(): UseTrashResult {
  const invalidate = useInvalidate();
  const toast = useToast();
  const { t } = useTranslation();

  const trash = useListTrash({ page_size: PAGE_SIZE });

  // Every one of these moves a book between two lists and changes counts and
  // statistics, so the catalogue is dropped rather than patched by hand. Not
  // the accounts or the settings: emptying the trash cannot touch either.
  const refresh = () => invalidate.catalogue();

  // One slot each, so pressing one verb leaves the other's failure on screen,
  // as reading each hook's own `error` did.
  const restoreFailure = useWriteFailure();
  const purgeFailure = useWriteFailure();
  const restore = useRestoreBook({
    mutation: {
      ...restoreFailure.report,
      onSuccess: () => {
        refresh();
        toast.show({ message: t("trash.restored") });
      },
    },
  });
  const purge = usePurgeBook({
    mutation: { ...purgeFailure.report, onSuccess: refresh },
  });
  const empty = useEmptyTrash({
    mutation: {
      onSuccess: (result) => {
        refresh();
        toast.show({ message: t("trash.emptied", { count: result.purged }) });
      },
    },
  });
  const busyIds = usePendingRows<
    RestoreBookMutationVariables | PurgeBookMutationVariables
  >("bookId", getRestoreBookMutationKey(), getPurgeBookMutationKey());

  return {
    books: trash.data?.items ?? [],
    total: trash.data?.total ?? 0,
    isLoading: trash.isPending,
    error:
      trash.error ?? restoreFailure.error ?? purgeFailure.error ?? empty.error,
    refetch: () => void trash.refetch(),

    restore: (bookId) => restore.mutate({ bookId }),
    purge: (bookId) => purge.mutate({ bookId }),
    empty: () => empty.mutate(),
    busyIds,
    isEmptying: empty.isPending,
  };
}
