/**
 * Everything BookDetail needs from the API.
 *
 * Split into three hooks by concern (the book itself, its notes, its loan)
 * rather than one that returns thirty fields. Every mutation
 * invalidates what it actually changed, so the page never patches the cache by
 * hand and never re-reads stale data.
 */

import { useQueryClient } from "@tanstack/react-query";

import {
  getGetBookQueryKey,
  getGetNotesQueryKey,
  useAddBookTag,
  useAddNote,
  useDeleteBook,
  useDeleteNote,
  useEditNote,
  useEnrichBook,
  useGetBook,
  useGetNotes,
  useListLocations,
  useListTags,
  useRefreshMetadata,
  useRemoveBookTag,
  useSetOwnership,
  useSetPrivacy,
  useSetRating,
  useUpdateBookDetails,
  useUpdateStatus,
  useUploadCover,
} from "../../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../../api/generated/endpoints/settings/settings";
import {
  useCreateLoan,
  useReturnLoan,
} from "../../api/generated/endpoints/loans/loans";
import { useListUsers } from "../../api/generated/endpoints/users/users";
import type {
  BookDetailsUpdate,
  LocationOut,
  BookEnrichmentOut,
  BookOut,
  NoteOut,
  OwnershipStatus,
  ReadStatus,
  TagOut,
  UserOut,
} from "../../api/generated/model";

/** Query keys touched by anything that changes a book. */
function useInvalidateBook(bookId: number) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: getGetBookQueryKey(bookId),
    });
    // The grid and the loans list both embed book state.
    void queryClient.invalidateQueries({ queryKey: ["/api/books"] });
    void queryClient.invalidateQueries({ queryKey: ["/api/loans"] });
  };
}

export interface UseBookResult {
  book: BookOut | undefined;
  tags: TagOut[];
  users: UserOut[];
  /** Existing shelf locations, offered as suggestions when editing one. */
  locations: LocationOut[];
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export function useBook(bookId: number): UseBookResult {
  const book = useGetBook(bookId);
  const tags = useListTags();
  const users = useListUsers();
  // Cached longer than the book: the set of shelves in a house changes far
  // less often than the book being looked at.
  const locations = useListLocations({ query: { staleTime: 5 * 60_000 } });

  return {
    book: book.data,
    tags: tags.data ?? [],
    users: users.data ?? [],
    locations: locations.data ?? [],
    isLoading: book.isPending,
    error: book.error,
    refetch: () => void book.refetch(),
  };
}

export interface UseBookActionsResult {
  setStatus: (status: ReadStatus) => void;
  setPrivacy: (isPrivate: boolean) => void;
  addTag: (tagId: number) => void;
  removeTag: (tagId: number) => void;
  uploadCover: (file: File) => void;
  refreshMetadata: () => void;
  setOwnership: (ownership: OwnershipStatus) => void;
  setRating: (rating: number | null) => void;
  updateDetails: (fields: BookDetailsUpdate) => void;
  isSavingDetails: boolean;
  remove: () => void;

  isRefreshing: boolean;
  refreshError: unknown;
  error: unknown;
}

export function useBookActions(
  bookId: number,
  onDeleted: () => void,
): UseBookActionsResult {
  const invalidate = useInvalidateBook(bookId);
  const mutation = { onSuccess: invalidate };

  const status = useUpdateStatus({ mutation });
  const privacy = useSetPrivacy({ mutation });
  const addTag = useAddBookTag({ mutation });
  const removeTag = useRemoveBookTag({ mutation });
  const cover = useUploadCover({ mutation });
  const refresh = useRefreshMetadata({ mutation });
  const ownership = useSetOwnership({ mutation });
  const rating = useSetRating({ mutation });
  const details = useUpdateBookDetails({ mutation });
  const remove = useDeleteBook({
    mutation: {
      onSuccess: () => {
        invalidate();
        onDeleted();
      },
    },
  });

  return {
    setStatus: (value) => status.mutate({ bookId, data: { status: value } }),
    setPrivacy: (isPrivate) =>
      privacy.mutate({ bookId, data: { is_private: isPrivate } }),
    addTag: (tagId) => addTag.mutate({ bookId, tagId }),
    removeTag: (tagId) => removeTag.mutate({ bookId, tagId }),
    uploadCover: (file) => cover.mutate({ bookId, data: { file } }),
    refreshMetadata: () => refresh.mutate({ bookId }),
    setRating: (value) => rating.mutate({ bookId, data: { rating: value } }),
    updateDetails: (fields) => details.mutate({ bookId, data: fields }),
    isSavingDetails: details.isPending,
    setOwnership: (value) =>
      ownership.mutate({ bookId, data: { ownership: value } }),
    remove: () => remove.mutate({ bookId }),

    // Refresh reports separately: it is slow (two upstream lookups) and its
    // failure is shown next to its own button rather than at the page top.
    isRefreshing: refresh.isPending,
    refreshError: refresh.error,
    error:
      status.error ??
      privacy.error ??
      addTag.error ??
      removeTag.error ??
      cover.error ??
      ownership.error ??
      rating.error ??
      details.error ??
      remove.error,
  };
}

export interface UseBookNotesResult {
  notes: NoteOut[];
  add: (content: string) => void;
  edit: (noteId: number, content: string) => void;
  remove: (noteId: number) => void;
  isAdding: boolean;
  error: unknown;
}

export function useBookNotes(bookId: number): UseBookNotesResult {
  const queryClient = useQueryClient();
  const notes = useGetNotes(bookId);

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getGetNotesQueryKey(bookId),
      });
    },
  };

  const add = useAddNote({ mutation });
  const edit = useEditNote({ mutation });
  const remove = useDeleteNote({ mutation });

  return {
    notes: notes.data ?? [],
    add: (content) => add.mutate({ bookId, data: { content } }),
    edit: (noteId, content) =>
      edit.mutate({ bookId, noteId, data: { content } }),
    remove: (noteId) => remove.mutate({ bookId, noteId }),
    isAdding: add.isPending,
    error: notes.error ?? add.error ?? edit.error ?? remove.error,
  };
}

export interface UseBookLoanResult {
  lend: (toUserId: number, dueAt?: string | null) => void;
  markReturned: (loanId: number) => void;
  isBusy: boolean;
  error: unknown;
}

export function useBookLoan(bookId: number): UseBookLoanResult {
  const invalidate = useInvalidateBook(bookId);
  const mutation = { onSuccess: invalidate };

  const create = useCreateLoan({ mutation });
  const complete = useReturnLoan({ mutation });

  return {
    lend: (toUserId, dueAt) =>
      create.mutate({
        data: {
          book_id: bookId,
          loaned_to_user_id: toUserId,
          due_at: dueAt ?? null,
        },
      }),
    markReturned: (loanId) => complete.mutate({ loanId }),
    isBusy: create.isPending || complete.isPending,
    error: create.error ?? complete.error,
  };
}

export interface UseBookEnrichmentResult {
  /** Whether to render the button at all. Follows the admin's toggle. */
  isEnabled: boolean;
  /** Whether pressing it will work: the toggle is on AND a key is stored. */
  isConfigured: boolean;
  enrich: () => void;
  isWorking: boolean;
  /** The last run's outcome, or null before the first run. */
  result: BookEnrichmentOut | null;
  error: unknown;
  dismiss: () => void;
}

/**
 * Filling in missing details from Google Books.
 *
 * Kept apart from `useBookActions` because it is the only action whose result
 * the page has to report back: enrichment routinely finds the volume and has
 * nothing new to add, and a button that silently does nothing in that case
 * looks broken. `updated_fields` is what the page shows.
 */
export function useBookEnrichment(bookId: number): UseBookEnrichmentResult {
  const invalidate = useInvalidateBook(bookId);
  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });

  const enrich = useEnrichBook({ mutation: { onSuccess: invalidate } });

  return {
    isEnabled: flags.data?.google_books_enabled ?? false,
    isConfigured: flags.data?.google_books_ready ?? false,
    // Never with `overwrite`: the button fills gaps. A typed-in publisher is
    // a deliberate correction and outranks anything upstream says.
    enrich: () => enrich.mutate({ bookId, params: { overwrite: false } }),
    isWorking: enrich.isPending,
    result: enrich.data ?? null,
    error: enrich.error,
    dismiss: () => enrich.reset(),
  };
}

/** Whether Goodreads lookup links should be rendered. */
export function useGoodreadsLookup(): boolean {
  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });
  return flags.data?.goodreads_lookup_enabled ?? false;
}
