/**
 * Data for the collections page.
 *
 * Every mutation invalidates the collections list and, where it can change
 * what a book payload says, the book caches too: a rename changes the
 * `collection_name` on every book filed there, and a delete unfiles them.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getListCollectionsQueryKey,
  useCreateCollection,
  useDeleteCollection,
  useListCollections,
  useRenameCollection,
} from "../../api/generated/endpoints/collections/collections";
import type { CollectionOut } from "../../api/generated/model";

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
  const query = useListCollections({ query: { retry: false } });

  const refreshList = () =>
    void queryClient.invalidateQueries({ queryKey: getListCollectionsQueryKey() });

  // A rename shows up inside every book payload as `collection_name`, and a
  // delete unfiles books outright, so both drop the book caches as well as the
  // list. Creating one cannot change any book, so it does not.
  const refreshEverything = () => {
    refreshList();
    void queryClient.invalidateQueries({ queryKey: ["/api/books"] });
    void queryClient.invalidateQueries({ queryKey: ["/api/stats"] });
  };

  const create = useCreateCollection({ mutation: { onSuccess: refreshList } });
  const rename = useRenameCollection({
    mutation: { onSuccess: refreshEverything },
  });
  const remove = useDeleteCollection({
    mutation: { onSuccess: refreshEverything },
  });

  return {
    collections: query.data ?? [],
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
