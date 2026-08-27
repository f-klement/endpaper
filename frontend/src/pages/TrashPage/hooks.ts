/**
 * The trash page's whole contact with the API.
 *
 * Deleting is reversible now, so this is where a book goes to be put back or
 * finished off. The two verbs are deliberately different weights: restoring is
 * one tap, deleting for good asks first, because that one really is final.
 */

import {
  useEmptyTrash,
  useListTrash,
  usePurgeBook,
  useRestoreBook,
} from "../../api/generated/endpoints/books/books";
import type { BookOut } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";
import { useToast } from "../../app/toast";
import { useTranslation } from "../../i18n";

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
  /** Which book is mid-request, so the row can show it. */
  busyId: number | null;
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

  const restore = useRestoreBook({
    mutation: {
      onSuccess: () => {
        refresh();
        toast.show({ message: t("trash.restored") });
      },
    },
  });
  const purge = usePurgeBook({ mutation: { onSuccess: refresh } });
  const empty = useEmptyTrash({
    mutation: {
      onSuccess: (result) => {
        refresh();
        toast.show({ message: t("trash.emptied", { count: result.purged }) });
      },
    },
  });

  return {
    books: trash.data?.items ?? [],
    total: trash.data?.total ?? 0,
    isLoading: trash.isPending,
    error: trash.error ?? restore.error ?? purge.error ?? empty.error,
    refetch: () => void trash.refetch(),

    restore: (bookId) => restore.mutate({ bookId }),
    purge: (bookId) => purge.mutate({ bookId }),
    empty: () => empty.mutate(),
    busyId: restore.isPending
      ? (restore.variables?.bookId ?? null)
      : purge.isPending
        ? (purge.variables?.bookId ?? null)
        : null,
    isEmptying: empty.isPending,
  };
}
