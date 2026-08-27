/**
 * Data for the collections page.
 *
 * Every mutation invalidates the collections list and, where it can change
 * what a book payload says, the book caches too: a rename changes the
 * `collection_name` on every book filed there, and a delete unfiles them.
 */

import { useQueryClient } from "@tanstack/react-query";

import { useSortedByName } from "../../i18n";

import {
  getListCollectionsQueryKey,
  useCreateCollection,
  useDeleteCollection,
  useListCollections,
  useRenameCollection,
} from "../../api/generated/endpoints/collections/collections";
import { getGetStatsQueryKey } from "../../api/generated/endpoints/stats/stats";
import type { CollectionOut } from "../../api/generated/model";
import { useInvalidate } from "../../api/invalidate";

export interface UseCollectionsResult {
  collections: CollectionOut[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;

  create: (name: string) => void;
  isCreating: boolean;
  createError: unknown;

  rename: (collection: CollectionOut, name: string) => void;
  isRenaming: boolean;
  renameError: unknown;

  remove: (collection: CollectionOut) => void;
  isRemoving: boolean;
  removeError: unknown;
}

export function useCollections(): UseCollectionsResult {
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const query = useListCollections({ query: { retry: false } });
  // The endpoint orders by `lower(name)`, which is a case fold and not a
  // collation: it still files every accented name after `z`. See
  // `lib/nameOrder.ts`.
  const collections = useSortedByName(query.data);

  const refreshList = () =>
    void queryClient.invalidateQueries({
      queryKey: getListCollectionsQueryKey(),
    });

  // A rename shows up inside every book payload as `collection_name`, and a
  // delete unfiles books outright, so both drop the book caches as well as the
  // list. Creating one cannot change any book, so it does not.
  const refreshEverything = () => {
    refreshList();
    // `invalidate.listings()` rather than `["/api/books"]`: the grid is an
    // infinite query and a hand-written key does not match it.
    invalidate.listings();
    void queryClient.invalidateQueries({ queryKey: getGetStatsQueryKey() });
  };

  const create = useCreateCollection({ mutation: { onSuccess: refreshList } });
  const rename = useRenameCollection({
    mutation: { onSuccess: refreshEverything },
  });
  const remove = useDeleteCollection({
    mutation: { onSuccess: refreshEverything },
  });

  return {
    collections,
    isLoading: query.isPending,
    error: query.error,
    refetch: () => void query.refetch(),

    create: (name) => create.mutate({ data: { name } }),
    isCreating: create.isPending,
    createError: create.error,

    rename: (collection, name) =>
      rename.mutate({ collectionId: collection.id, data: { name } }),
    isRenaming: rename.isPending,
    renameError: rename.error,

    remove: (collection) => remove.mutate({ collectionId: collection.id }),
    isRemoving: remove.isPending,
    removeError: remove.error,
  };
}
