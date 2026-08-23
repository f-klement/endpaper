/**
 * Everything BookDetail needs from the API.
 *
 * Split by concern (the book itself, its notes, its loan, its reading log)
 * rather than one hook that returns thirty fields. Every mutation invalidates
 * what it actually changed, so the page never patches the cache by hand and
 * never re-reads stale data.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  getGetBookQueryKey,
  getGetNotesQueryKey,
  getListCopiesQueryKey,
  getListProgressQueryKey,
  useAddBookTag,
  useAddCopy,
  useListCopies,
  useAddProgress,
  useDeleteProgress,
  useListProgress,
  useAddNote,
  useApplyEnrichment,
  useDeleteBook,
  useDeleteNote,
  useEditNote,
  useEnrichmentCandidates,
  useGetBook,
  useGetNotes,
  useListLocations,
  useListTags,
  useCreateTag,
  useDeleteTag,
  getListTagsQueryKey,
  useRefreshMetadata,
  useRestoreBook,
  useRemoveBookTag,
  useSetCollection,
  useSetDiscuss,
  useSetOwnership,
  useSetPrivacy,
  useSetRating,
  useUpdateBookDetails,
  useUpdateStatus,
  useUploadCover,
} from "../../api/generated/endpoints/books/books";
import {
  getListCollectionsQueryKey,
  useCreateCollection,
  useListCollections,
} from "../../api/generated/endpoints/collections/collections";
import { useGetFeatureFlags } from "../../api/generated/endpoints/settings/settings";
import {
  useCreateLoan,
  useReturnLoan,
} from "../../api/generated/endpoints/loans/loans";
import { useListUsers } from "../../api/generated/endpoints/users/users";
import { useToast } from "../../app/toast";
import type { Borrower } from "./components/LoanPanel";
import { useTranslation } from "../../i18n";
import type {
  BookMatch,
  BookDetailsUpdate,
  CollectionOut,
  LocationOut,
  BookEnrichmentOut,
  BookOut,
  NoteOut,
  OwnershipStatus,
  ProgressCreate,
  ProgressOut,
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
  /** The household's collections, for the picker. */
  collections: CollectionOut[];
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
  const collections = useListCollections({ query: { staleTime: 5 * 60_000 } });

  return {
    book: book.data,
    tags: tags.data ?? [],
    users: users.data ?? [],
    locations: locations.data ?? [],
    collections: collections.data ?? [],
    isLoading: book.isPending,
    error: book.error,
    refetch: () => void book.refetch(),
  };
}

export interface UseBookActionsResult {
  setStatus: (status: ReadStatus) => void;
  setPrivacy: (isPrivate: boolean) => void;
  addTag: (tagId: number) => void;
  /** Invent a tag and put it on this book in one step. */
  createTag: (name: string) => void;
  isCreatingTag: boolean;
  /** Delete a household tag everywhere, after confirming. */
  deleteTag: (tag: TagOut) => void;
  removeTag: (tagId: number) => void;
  uploadCover: (file: File) => void;
  refreshMetadata: () => void;
  setOwnership: (ownership: OwnershipStatus) => void;
  /** File this copy into a collection, or take it out of one with null. */
  setCollection: (collectionId: number | null) => void;
  /** Invent a collection and file this copy into it in one step. */
  createCollection: (name: string) => void;
  isFiling: boolean;
  setRating: (rating: number | null) => void;
  /** Offer to talk about this book, or withdraw the offer. */
  setDiscuss: (wantsToDiscuss: boolean) => void;
  updateDetails: (fields: BookDetailsUpdate) => void;
  isSavingDetails: boolean;
  /** Move the book to the trash. Reversible from the toast this raises. */
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
  const queryClient = useQueryClient();
  const toast = useToast();
  const { t } = useTranslation();

  const status = useUpdateStatus({ mutation });
  const privacy = useSetPrivacy({ mutation });
  const addTag = useAddBookTag({ mutation });

  const deleteTag = useDeleteTag({
    mutation: {
      onSuccess: () => {
        // It came off every book in the household, not only this one.
        void queryClient.invalidateQueries();
      },
    },
  });

  const createTag = useCreateTag({
    mutation: {
      onSuccess: (tag) => {
        // Straight onto the book. Somebody typing a tag name while looking at
        // a book means "this book is that", not "add a word to the list".
        addTag.mutate({ bookId, tagId: tag.id });
        // The tag list is its own cache entry, and the new tag has to appear
        // in the picker as well as on the book.
        void queryClient.invalidateQueries({ queryKey: getListTagsQueryKey() });
      },
    },
  });
  const removeTag = useRemoveBookTag({ mutation });
  const cover = useUploadCover({ mutation });
  const refresh = useRefreshMetadata({ mutation });
  const ownership = useSetOwnership({ mutation });
  const collection = useSetCollection({ mutation });

  const createCollection = useCreateCollection({
    mutation: {
      onSuccess: (created) => {
        // Straight onto the book, like `createTag`: somebody typing a
        // collection name while looking at a book means "this one goes there".
        collection.mutate({ bookId, data: { collection_id: created.id } });
        // Its own cache entry, and the new collection has to appear in every
        // other picker and in the library filter too.
        void queryClient.invalidateQueries({
          queryKey: getListCollectionsQueryKey(),
        });
      },
    },
  });
  const rating = useSetRating({ mutation });
  const discuss = useSetDiscuss({ mutation });
  const details = useUpdateBookDetails({ mutation });
  const restore = useRestoreBook({
    mutation: {
      onSuccess: () => {
        // A restored book is back in every listing, every count and every
        // statistic, so the whole cache is dropped rather than patched.
        void queryClient.invalidateQueries();
      },
    },
  });

  const remove = useDeleteBook({
    mutation: {
      onSuccess: () => {
        invalidate();
        // The offer to undo is the point. A delete is one tap away from every
        // book and this used to be the only thing in the app that repeating
        // could not reverse.
        toast.show({
          message: t("book.movedToTrash"),
          action: {
            label: t("common.undo"),
            onClick: () => restore.mutate({ bookId }),
          },
        });
        onDeleted();
      },
    },
  });

  return {
    setStatus: (value) => status.mutate({ bookId, data: { status: value } }),
    setPrivacy: (isPrivate) =>
      privacy.mutate({ bookId, data: { is_private: isPrivate } }),
    addTag: (tagId) => addTag.mutate({ bookId, tagId }),
    createTag: (name) => createTag.mutate({ data: { name } }),
    isCreatingTag: createTag.isPending,
    deleteTag: (tag) => {
      // Household-wide and not undoable, unlike deleting a book. The count is
      // in the message because "delete this tag" and "take this off 214 books"
      // are different decisions.
      if (
        confirm(
          t("tags.deleteConfirm", {
            name: tag.name,
            count: tag.book_count ?? 0,
          }),
        )
      )
        deleteTag.mutate({ tagId: tag.id });
    },
    removeTag: (tagId) => removeTag.mutate({ bookId, tagId }),
    uploadCover: (file) => cover.mutate({ bookId, data: { file } }),
    refreshMetadata: () => refresh.mutate({ bookId }),
    setRating: (value) => rating.mutate({ bookId, data: { rating: value } }),
    setDiscuss: (wantsToDiscuss) =>
      discuss.mutate({ bookId, data: { wants_to_discuss: wantsToDiscuss } }),
    updateDetails: (fields) => details.mutate({ bookId, data: fields }),
    isSavingDetails: details.isPending,
    setOwnership: (value) =>
      ownership.mutate({ bookId, data: { ownership: value } }),
    setCollection: (collectionId) =>
      collection.mutate({ bookId, data: { collection_id: collectionId } }),
    createCollection: (name) => createCollection.mutate({ data: { name } }),
    // One flag for both, because they are one action from the reader's side:
    // the second half of creating a collection here is filing the book into it.
    isFiling: collection.isPending || createCollection.isPending,
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
      collection.error ??
      createCollection.error ??
      rating.error ??
      discuss.error ??
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
  lend: (
    borrower: Borrower,
    dueAt?: string | null,
    acknowledgeNotLendable?: boolean,
  ) => void;
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
    // Exactly one of the two borrower fields, which is what the API accepts
    // and what the CHECK constraint behind it enforces. The union is what
    // stops the both-or-neither request being expressible at all.
    lend: (borrower, dueAt, acknowledgeNotLendable = false) =>
      create.mutate({
        data: {
          book_id: bookId,
          loaned_to_user_id:
            borrower.kind === "member" ? borrower.userId : null,
          loaned_to_name: borrower.kind === "external" ? borrower.name : null,
          due_at: dueAt ?? null,
          // A book marked "never lent" is a 409 without this. It says
          // something about one request and is not stored, so it is passed
          // through rather than remembered here.
          acknowledge_not_lendable: acknowledgeNotLendable,
        },
      }),
    markReturned: (loanId) => complete.mutate({ loanId }),
    isBusy: create.isPending || complete.isPending,
    error: create.error ?? complete.error,
  };
}

export interface UseBookCopiesResult {
  /** Every copy of this title the caller may see, this one included. */
  copies: BookOut[];
  /** Record another copy. Nothing is offered to fill in: the new row is opened. */
  add: () => void;
  isAdding: boolean;
  /** Why the add failed, or why the list could not be read. Distinct, because
   * they need different sentences: one is a write that did not happen, the
   * other is a panel that would otherwise quietly claim there is one copy. */
  error: unknown;
  listError: unknown;
}

/**
 * The other objects on the shelf that are this same book.
 *
 * Fetched even for the overwhelming majority of books that have exactly one
 * copy, because the answer is a one-element list rather than an empty one and
 * the panel offers the add action either way. It is one request against a
 * page that already makes six.
 */
export function useBookCopies(bookId: number): UseBookCopiesResult {
  const queryClient = useQueryClient();
  const invalidateBook = useInvalidateBook(bookId);
  const copies = useListCopies(bookId);

  const add = useAddCopy({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getListCopiesQueryKey(bookId),
        });
        // The book itself, because `copy_count` has just changed on it.
        invalidateBook();
      },
    },
  });

  return {
    copies: copies.data ?? [],
    // An empty body rather than the scan form's fields. The person is standing
    // at the shelf with the second copy in hand, and asking them to fill a form
    // before the row exists is friction in front of the one press this whole
    // feature is. Everything on it is editable afterwards, on the copy's own
    // page.
    add: () => add.mutate({ bookId, data: {} }),
    isAdding: add.isPending,
    error: add.error,
    listError: copies.error,
  };
}

export interface UseBookEnrichmentResult {
  /** Whether to render the button at all. Always: no API key is needed. */
  isEnabled: boolean;
  /** Whether Google Books is configured, for the note about what it adds. */
  isConfigured: boolean;

  /** Open the picker and look for editions. Writes nothing. */
  browse: () => void;
  close: () => void;
  isPickerOpen: boolean;
  candidates: BookMatch[];
  isSearching: boolean;

  /** Take the details from one chosen edition. This is what writes. */
  choose: (match: BookMatch) => void;
  isWorking: boolean;

  /** The last run's outcome, or null before the first run. */
  result: BookEnrichmentOut | null;
  error: unknown;
  dismiss: () => void;
}

/**
 * Filling in missing details from a catalogue.
 *
 * Two steps rather than one, and the split is the point. The old button went
 * straight to whatever the first search result happened to be, and a search
 * will happily return the wrong printing of the right book: a paperback and
 * its hardback are different page counts and different covers. So the button
 * now opens a picker, and nothing is written until somebody has looked at the
 * candidates and said which one it is.
 *
 * Kept apart from `useBookActions` because it is the only action whose result
 * the page has to report back: enrichment routinely finds the edition and has
 * nothing new to add, and a button that silently does nothing looks broken.
 */
export function useBookEnrichment(bookId: number): UseBookEnrichmentResult {
  const invalidate = useInvalidateBook(bookId);
  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });
  const [isPickerOpen, setIsPickerOpen] = useState(false);

  const candidates = useEnrichmentCandidates(bookId, {
    query: {
      // Only once the picker is open. Fetching on mount would put six
      // catalogue requests behind every book anybody looks at.
      enabled: isPickerOpen,
      retry: false,
      staleTime: 5 * 60_000,
    },
  });

  const apply = useApplyEnrichment({
    mutation: {
      onSuccess: () => {
        invalidate();
        setIsPickerOpen(false);
      },
    },
  });

  return {
    // No key is required any more: Open Library and the national catalogues
    // answer without one. The flag now only decides the note about what a key
    // would add.
    isEnabled: true,
    isConfigured: flags.data?.google_books_ready ?? false,

    browse: () => {
      apply.reset();
      setIsPickerOpen(true);
    },
    close: () => setIsPickerOpen(false),
    isPickerOpen,
    candidates: candidates.data ?? [],
    isSearching: candidates.isFetching,

    // Never with `overwrite`: the picker fills gaps. A typed-in publisher is a
    // deliberate correction and outranks anything a catalogue says.
    choose: (match) =>
      apply.mutate({ bookId, data: match, params: { overwrite: false } }),
    isWorking: apply.isPending,

    result: apply.data ?? null,
    error: apply.error ?? candidates.error,
    dismiss: () => apply.reset(),
  };
}

/** Whether Goodreads lookup links should be rendered. */
export function useGoodreadsLookup(): boolean {
  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });
  return flags.data?.goodreads_lookup_enabled ?? false;
}

export interface UseBookProgressResult {
  entries: ProgressOut[];
  /** Record a position. Exactly one of `page` and `percent`. */
  record: (entry: ProgressCreate) => void;
  remove: (progressId: number) => void;
  isRecording: boolean;
  error: unknown;
}

/**
 * The reading log for one book.
 *
 * Its own hook rather than another field on `useBookActions`, because both
 * writes invalidate two things rather than one: the log itself, and the book,
 * whose payload carries the newest position and whose status the first entry
 * promotes to reading.
 */
export function useBookProgress(bookId: number): UseBookProgressResult {
  const queryClient = useQueryClient();
  const invalidateBook = useInvalidateBook(bookId);
  const entries = useListProgress(bookId);

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getListProgressQueryKey(bookId),
      });
      // Recording a position moves `my_progress_*` on the book, and the first
      // one moves `my_status` with it.
      invalidateBook();
    },
  };

  const record = useAddProgress({ mutation });
  const remove = useDeleteProgress({ mutation });

  return {
    entries: entries.data ?? [],
    // `mutate`, not `mutateAsync`: nothing awaits these, and mutateAsync
    // rejects, leaving an unhandled rejection on every failure. The failure is
    // rendered from `error`.
    record: (entry) => record.mutate({ bookId, data: entry }),
    remove: (progressId) => remove.mutate({ bookId, progressId }),
    isRecording: record.isPending,
    error: entries.error ?? record.error ?? remove.error,
  };
}
