/**
 * Everything BookDetail needs from the API.
 *
 * Split by concern (the book itself, its notes, its loan, its reading log)
 * rather than one hook that returns thirty fields. `useBookSections` is the one
 * exception to the title: it holds no server state, only which parts of the
 * page this device has folded away.
 *
 * Every mutation invalidates what it actually changed, so the page never
 * patches the cache by hand and never re-reads stale data.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useInvalidate } from "../../api/invalidate";
import {
  readSectionChoices,
  resolveOpen,
  writeSectionChoice,
  type SectionChoices,
} from "../../lib/sectionState";

import {
  getGetCustomFieldsQueryKey,
  getListAccessRequestsQueryKey,
  getListPendingHeadingsQueryKey,
  getListCustomFieldsQueryKey,
  getGetHighlightsQueryKey,
  getGetNotesQueryKey,
  getSetHighlightSharingMutationOptions,
  getDeleteHighlightMutationOptions,
  getGetQuotesQueryKey,
  getListQuotesQueryKey,
  getListProgressQueryKey,
  getDeleteNoteMutationOptions,
  getDeleteProgressMutationOptions,
  getDeleteQuoteMutationOptions,
  getDeleteTagMutationOptions,
  getEditNoteMutationOptions,
  getEditQuoteMutationOptions,
  getForgetBookIdentifierMutationOptions,
  getForgetOnlineLinkMutationOptions,
  getForgetDigitalReferenceMutationOptions,
  getListDigitalReferencesQueryKey,
  getListCoverImagesQueryKey,
  getDeleteCoverImageMutationOptions,
  getShelveCoverImageMutationOptions,
  getRemoveBookTagMutationOptions,
  useAddBookTag,
  useAddCopy,
  useAddHeading,
  useListSuggestingVocabularies,
  useSuggestHeadings,
  useConfirmPendingHeadings,
  useDiscardPendingHeadings,
  useListPendingHeadings,
  useDecideAccess,
  useListAccessRequests,
  useListDigitalReferences,
  useListCoverImages,
  useUploadCoverImage,
  useListCopies,
  useRequestAccess,
  useAddProgress,
  useListProgress,
  useAddNote,
  useAddQuote,
  useApplyEnrichment,
  useDeleteBook,
  useEnrichmentCandidates,
  useGetBook,
  useGetCustomFields,
  useGetHighlights,
  useGetNotes,
  useGetQuotes,
  useListLocations,
  useListTags,
  useAddBookTagByName,
  getListTagsQueryKey,
  useRefreshMetadata,
  useRestoreBook,
  useListCustomFields,
  useSetCollection,
  useSetCustomField,
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
import {
  useCreateLoan,
  useReturnLoan,
} from "../../api/generated/endpoints/loans/loans";
import { useListUsers } from "../../api/generated/endpoints/users/users";
import {
  getListKosyncDocumentsQueryKey,
  getListKosyncInboxQueryKey,
  useLinkKosyncDocument,
  useListKosyncDocuments,
  useListKosyncInbox,
  useUnlinkKosyncDocument,
} from "../../api/generated/endpoints/kosync/kosync";
import { useGoogleBooksReady, useLibraryMode } from "../../app/hooks";
import { useToast } from "../../app/toast";
import type { Borrower } from "./components/LoanPanel";
import { useRowWrite } from "../hooks";
import { isRequestedNotLent } from "./types";
import { tagName, useSortedByName, useTranslation } from "../../i18n";
import type {
  AccessRequestOut,
  BookMatch,
  BookDetailsUpdate,
  BookIdentifierOut,
  ClassificationOut,
  OnlineLinkOut,
  CollectionOut,
  CoverImageOut,
  DigitalReferenceOut,
  CustomFieldOut,
  CustomFieldValueOut,
  HighlightOut,
  LocationOut,
  BookEnrichmentOut,
  BookOut,
  NoteOut,
  OwnershipStatus,
  ProgressCreate,
  ProgressOut,
  QuoteCreate,
  QuoteOut,
  ReadStatus,
  TagOut,
  UserOut,
  KosyncDocumentOut,
  SuggestingVocabularyOut,
} from "../../api/generated/model";
import { BookFormat, HeadingUse } from "../../api/generated/model";

export interface UseBookResult {
  book: BookOut | undefined;
  tags: TagOut[];
  users: UserOut[];
  /** Existing shelf locations, offered as suggestions when editing one. */
  locations: LocationOut[];
  /** The library's collections, for the picker. */
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

  // The picker is a name list, and the endpoint's `lower(name)` is a fold
  // rather than a collation. `locations` is deliberately left alone: it arrives
  // most-populated first, which is an answer to a different question. See
  // `lib/nameOrder.ts`.
  const filed = useSortedByName(collections.data);

  return {
    book: book.data,
    tags: tags.data ?? [],
    users: users.data ?? [],
    locations: locations.data ?? [],
    collections: filed,
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
  /** Delete a curated tag everywhere, after confirming. */
  deleteTag: (tag: TagOut) => void;
  removeTag: (tagId: number) => void;
  /** Take one store identifier off the book, after confirming. */
  removeIdentifier: (identifier: BookIdentifierOut) => void;
  /** Take one catalogue link off the book, after confirming. */
  removeOnlineLink: (link: OnlineLinkOut) => void;
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
  const invalidate = useInvalidate();
  const invalidateBook = () => invalidate.book(bookId);
  const mutation = { onSuccess: invalidateBook };
  const queryClient = useQueryClient();
  const toast = useToast();
  const { t, locale } = useTranslation();

  const status = useUpdateStatus({ mutation });
  const privacy = useSetPrivacy({ mutation });
  const addTag = useAddBookTag({ mutation });

  const deleteTag = useRowWrite(getDeleteTagMutationOptions, "tagId", () => {
    // It came off every book in the library, not only this one, and the tag
    // list itself is now a name shorter.
    invalidate.catalogue();
  });

  // Somebody typing a tag name while looking at a book means "this book is
  // that", not "add a word to the list", so it is one request that invents
  // the tag if it is new and puts it on the book either way.
  //
  // **This replaced a create followed by an attach, and what went with the
  // second request is the reason to prefer this shape.** The two answered
  // different questions, the create by name and the attach by id, and the
  // attach refused a name colliding with a tag on a book the reader cannot
  // see: the member was shown "Tag not found" one beat after typing a name
  // they had never been told about. The ordering between the attach and the
  // tag list refetch went too, along with the paragraph explaining it, since
  // there is now nothing to order.
  const createTag = useAddBookTagByName({
    mutation: {
      onSuccess: () => {
        invalidateBook();
        // The tag list is its own cache entry, and a newly invented tag has
        // to appear in the picker as well as on the book.
        void queryClient.invalidateQueries({ queryKey: getListTagsQueryKey() });
      },
    },
  });
  const removeTag = useRowWrite(
    getRemoveBookTagMutationOptions,
    "tagId",
    invalidateBook,
  );
  // The book's own invalidation, so the book and the listings both drop it:
  // `books_to_out` carries these onto every row of every page, so a page
  // cached before the removal still holds the row.
  const removeIdentifier = useRowWrite(
    getForgetBookIdentifierMutationOptions,
    "identifierId",
    invalidateBook,
  );
  // The book's own invalidation, for the identifiers' reason: listings carry
  // the links too.
  const removeOnlineLink = useRowWrite(
    getForgetOnlineLinkMutationOptions,
    "linkId",
    invalidateBook,
  );
  const cover = useUploadCover({ mutation });
  // Not `mutation`: a metadata refresh rewrites the title, the author and the
  // series, which the author index, the series index and the shelf list are
  // all built from. On `book()` alone those three stayed on the old name.
  const refresh = useRefreshMetadata({
    mutation: { onSuccess: () => invalidate.catalogue() },
  });
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
  // Same reason as `refresh`: `BookDetailsUpdate` carries `author`,
  // `series_name` and `location`.
  const details = useUpdateBookDetails({
    mutation: { onSuccess: () => invalidate.catalogue() },
  });
  const restore = useRestoreBook({
    mutation: {
      onSuccess: () => {
        // A restored book is back in every listing, every count and every
        // statistic, and out of the trash, so the catalogue goes rather than
        // this one book. Not the accounts or the settings: a restore cannot
        // touch either, and this page has both on screen.
        invalidate.catalogue();
      },
    },
  });

  const remove = useDeleteBook({
    mutation: {
      onSuccess: () => {
        invalidateBook();
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
    createTag: (name) => createTag.mutate({ bookId, data: { name } }),
    isCreatingTag: createTag.isPending,
    deleteTag: (tag) => {
      // Library wide and not undoable, unlike deleting a book, and the message
      // says "every book" rather than a number. `book_count` is the reader's
      // count and the delete is not: an admin was told to take a tag off 3
      // books when it was on two hundred, and the gap is exactly other members'
      // private books, so publishing a true count is not available either.
      // `customFields.deleteConfirm` settled the same question first.
      if (
        confirm(
          t("tags.deleteConfirm", {
            // Only an invented tag can be deleted, so this is the name they
            // typed. Through `tagName` all the same, because the rule is that
            // no tag reaches a reader by any other road.
            name: tagName(tag, locale),
          }),
        )
      )
        deleteTag.mutate({ tagId: tag.id });
    },
    removeTag: (tagId) => removeTag.mutate({ bookId, tagId }),
    removeIdentifier: (identifier) => {
      // Asked about, where removing a tag is not, and the difference is that
      // nothing here adds one back rather than that this is graver. A tag goes
      // back on from the picker beside it. The message says that much and no
      // more: the question of whether any road exists has a condition in it,
      // and a confirm cannot carry one. `models.BookIdentifier` holds it.
      if (confirm(t("identifier.removeConfirm", { value: identifier.value })))
        removeIdentifier.mutate({ bookId, identifierId: identifier.id });
    },
    removeOnlineLink: (link) => {
      if (
        confirm(
          t("onlineLinks.removeConfirm", { link: link.label ?? link.url }),
        )
      )
        removeOnlineLink.mutate({ bookId, linkId: link.id });
    },
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
    error: firstError(
      status.error,
      privacy.error,
      addTag.error,
      // Surfaced where the create's was not: it used to be swallowed by the
      // chain that followed it, and the one refusal this door has is the tag
      // ceiling, which is about this book and worth saying.
      createTag.error,
      removeTag.error,
      removeIdentifier.error,
      removeOnlineLink.error,
      deleteTag.error,
      cover.error,
      ownership.error,
      collection.error,
      createCollection.error,
      rating.error,
      discuss.error,
      details.error,
      remove.error,
    ),
  };
}

/**
 * The first of `errors` that is set, in the order given, which is the order of
 * precedence on the page; the last one when none is, as a chain of `??` gives.
 */
function firstError(...errors: [unknown, ...unknown[]]): unknown {
  return errors.reduce((found, error) => found ?? error);
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
  const edit = useRowWrite(
    getEditNoteMutationOptions,
    "noteId",
    mutation.onSuccess,
  );
  const remove = useRowWrite(
    getDeleteNoteMutationOptions,
    "noteId",
    mutation.onSuccess,
  );

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

/**
 * What one write reports back, so the editor can stay open on a refusal.
 *
 * `mutate` with per-call callbacks rather than `mutateAsync`: the house rule
 * against the latter is that it rejects and leaves an unhandled rejection on
 * every failure, and these are handled by react-query rather than by a caller
 * remembering to catch.
 */
export interface SaveCallbacks {
  onSuccess: () => void;
  onError: () => void;
}

export interface UseBookCustomFieldsResult {
  /** Every field the library has defined, filled in on this book or not. */
  definitions: CustomFieldOut[];
  /** Only the ones this book has something in. */
  values: CustomFieldValueOut[];
  save: (fieldId: number, value: string, callbacks: SaveCallbacks) => void;
  isSaving: boolean;
  error: unknown;
}

/**
 * The library's own facts about this book.
 *
 * **Two requests, not one.** The definitions are library wide and are the same
 * on every book, so they are their own cache entry and a second book page
 * costs nothing for them. The values are per book and are served by their own
 * route rather than on `BookOut`, for the reason recorded in
 * `routers/books.py`: a page of 25 book cards has nowhere to render them, and
 * putting them on the listing payload would cost every listing in the app a
 * query for something nothing displays.
 *
 * An empty value is a clear, so there is one write and no delete: see
 * `CustomFieldValueUpdate`.
 *
 * `save` reports per call, because the server refuses a url field that does not
 * hold a URL with a 400 and the panel has to keep what was typed when it does.
 */
export function useBookCustomFields(bookId: number): UseBookCustomFieldsResult {
  const queryClient = useQueryClient();
  const definitions = useListCustomFields();
  const values = useGetCustomFields(bookId);

  const save = useSetCustomField({
    mutation: {
      onSuccess: () => {
        void queryClient.invalidateQueries({
          queryKey: getGetCustomFieldsQueryKey(bookId),
        });
        // And the definitions, because a write can change which of them this
        // member is told about. Clearing the last value they can see on a
        // field whose other carriers are books they cannot see takes the row
        // off their list; filling one in on a book nobody had used it on
        // leaves it. `backend/fields.py` holds the arms.
        void queryClient.invalidateQueries({
          queryKey: getListCustomFieldsQueryKey(),
        });
      },
    },
  });

  return {
    definitions: definitions.data ?? [],
    values: values.data ?? [],
    save: (fieldId, value, callbacks) =>
      save.mutate({ bookId, fieldId, data: { value } }, callbacks),
    isSaving: save.isPending,
    error: definitions.error ?? values.error ?? save.error,
  };
}

export interface UseBookQuotesResult {
  quotes: QuoteOut[];
  add: (quote: QuoteCreate) => void;
  edit: (quoteId: number, quote: QuoteCreate) => void;
  remove: (quoteId: number) => void;
  isAdding: boolean;
  error: unknown;
}

/**
 * The passages saved from this book.
 *
 * The cross-book list at `/quotes` reads the same rows through a different
 * endpoint, so every write here drops that cache too. Without it, saving a
 * quote and then opening the quotes page shows a list that is missing the one
 * just added, which reads as a lost write rather than as a stale cache.
 */
export function useBookQuotes(bookId: number): UseBookQuotesResult {
  const queryClient = useQueryClient();
  const quotes = useGetQuotes(bookId);

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getGetQuotesQueryKey(bookId),
      });
      // `invalidateQueries` matches a key by prefix, so the bare getter also
      // selects the pages whose keys carry paging parameters.
      void queryClient.invalidateQueries({
        queryKey: getListQuotesQueryKey(),
      });
    },
  };

  const add = useAddQuote({ mutation });
  const edit = useRowWrite(
    getEditQuoteMutationOptions,
    "quoteId",
    mutation.onSuccess,
  );
  const remove = useRowWrite(
    getDeleteQuoteMutationOptions,
    "quoteId",
    mutation.onSuccess,
  );

  return {
    quotes: quotes.data ?? [],
    add: (quote) => add.mutate({ bookId, data: quote }),
    edit: (quoteId, quote) => edit.mutate({ bookId, quoteId, data: quote }),
    remove: (quoteId) => remove.mutate({ bookId, quoteId }),
    isAdding: add.isPending,
    error: quotes.error ?? add.error ?? edit.error ?? remove.error,
  };
}

export interface UseBookHighlightsResult {
  highlights: HighlightOut[];
  /** Share one of the caller's own highlights, or withdraw it. */
  setShared: (highlightId: number, isShared: boolean) => void;
  /** Delete one of the caller's own highlights, for good: no import brings it back. */
  remove: (highlightId: number) => void;
  /** Every highlight with a sharing change or a delete out. */
  pendingIds: ReadonlySet<number>;
  error: unknown;
}

/**
 * The highlights on this book the caller may read: their own, private or
 * shared, and those other members shared. Written by an import on the library
 * settings page; the writes here are sharing and deleting the caller's own.
 */
export function useBookHighlights(bookId: number): UseBookHighlightsResult {
  const queryClient = useQueryClient();
  const highlights = useGetHighlights(bookId);
  const refresh = () =>
    void queryClient.invalidateQueries({
      queryKey: getGetHighlightsQueryKey(bookId),
    });
  const sharing = useRowWrite(
    getSetHighlightSharingMutationOptions,
    "highlightId",
    refresh,
  );
  const removal = useRowWrite(
    getDeleteHighlightMutationOptions,
    "highlightId",
    refresh,
  );

  return {
    highlights: highlights.data ?? [],
    setShared: (highlightId, isShared) =>
      sharing.mutate({ bookId, highlightId, data: { is_shared: isShared } }),
    remove: (highlightId) => removal.mutate({ bookId, highlightId }),
    pendingIds: new Set([...sharing.pendingRows, ...removal.pendingRows]),
    error: highlights.error ?? sharing.error ?? removal.error,
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
  const invalidate = useInvalidate();
  const mutation = { onSuccess: () => invalidate.book(bookId) };

  const create = useCreateLoan({ mutation });
  const complete = useReturnLoan({ mutation });

  return {
    // Exactly one of the three borrower fields, which is what the API accepts
    // and what the CHECK constraint behind it enforces. The union is what
    // stops a request naming two, or none, being expressible at all.
    lend: (borrower, dueAt, acknowledgeNotLendable = false) =>
      create.mutate({
        data: {
          book_id: bookId,
          loaned_to_user_id:
            borrower.kind === "member" ? borrower.userId : null,
          loaned_to_name: borrower.kind === "external" ? borrower.name : null,
          loaned_to_patron_id:
            borrower.kind === "patron" ? borrower.patronId : null,
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

export interface UseBookAccessResult {
  /** Whether this copy is asked for rather than lent (`isRequestedNotLent`). */
  isRequested: boolean;
  /** The requests on this copy the viewer holds or made, oldest first. Empty
   * for a copy that is lent. */
  requests: AccessRequestOut[];
  request: () => void;
  decide: (requestId: number, granted: boolean) => void;
  isBusy: boolean;
  error: unknown;
}

/**
 * Asking the holder of a digital copy for access, and the holder's answer.
 *
 * An audiobook's references are read to tell a file from a disc; nothing is
 * read for any other format, and the request list is read only for a copy
 * that is asked for.
 */
export function useBookAccess(
  bookId: number,
  format: BookFormat | null | undefined,
): UseBookAccessResult {
  const queryClient = useQueryClient();
  const references = useListDigitalReferences(bookId, {
    query: { enabled: format === BookFormat.audiobook },
  });
  const isRequested = isRequestedNotLent(
    format,
    (references.data ?? []).length > 0,
  );
  const requests = useListAccessRequests(bookId, {
    query: { enabled: isRequested },
  });
  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getListAccessRequestsQueryKey(bookId),
      });
    },
  };
  const ask = useRequestAccess({ mutation });
  const answer = useDecideAccess({ mutation });

  return {
    isRequested,
    requests: requests.data ?? [],
    request: () => ask.mutate({ bookId }),
    decide: (requestId, granted) =>
      answer.mutate({ bookId, requestId, data: { granted } }),
    isBusy: ask.isPending || answer.isPending,
    error: requests.error ?? ask.error ?? answer.error,
  };
}

export interface UseBookPendingHeadingsResult {
  /** The headings a harvest suggested and nobody has settled. Empty for a member. */
  headings: ClassificationOut[];
  /** Write the whole set as this book's headings. */
  confirm: () => void;
  /** Drop the whole set, after asking: the server remembers a discard. */
  discard: () => void;
  isBusy: boolean;
  error: unknown;
}

/**
 * A harvest's suggested headings on this book, which an admin settles.
 *
 * **Read only for an admin**, since the route answers anybody else 403 and a
 * member is shown nothing. The whole set at once, as the server takes it.
 *
 * Confirming writes classifications, so it drops the catalogue: the book's own
 * record and the classification facets both move. Discarding writes nothing a
 * reader sees, so it drops this list alone.
 */
export function useBookPendingHeadings(
  bookId: number,
  isAdmin: boolean,
): UseBookPendingHeadingsResult {
  const { t } = useTranslation();
  const invalidate = useInvalidate();
  const queryClient = useQueryClient();
  const pending = useListPendingHeadings(bookId, {
    query: { enabled: isAdmin },
  });
  // **Emptied before it is read again**, because the server's list is empty
  // once either write lands. Invalidating alone leaves the settled set on screen
  // for the refetch's round trip, with both buttons live again over headings
  // already written or discarded.
  const dropPending = () => {
    const queryKey = getListPendingHeadingsQueryKey(bookId);
    queryClient.setQueryData(queryKey, []);
    void queryClient.invalidateQueries({ queryKey });
  };
  const accept = useConfirmPendingHeadings({
    mutation: {
      onSuccess: () => {
        dropPending();
        invalidate.catalogue();
      },
    },
  });
  const reject = useDiscardPendingHeadings({
    mutation: { onSuccess: dropPending },
  });

  const headings = pending.data ?? [];

  return {
    headings,
    confirm: () => accept.mutate({ bookId }),
    discard: () => {
      const question =
        headings.length === 1
          ? t("pendingHeadings.discardConfirmOne")
          : t("pendingHeadings.discardConfirm");
      if (window.confirm(question)) reject.mutate({ bookId });
    },
    isBusy: accept.isPending || reject.isPending,
    error: pending.error ?? accept.error ?? reject.error,
  };
}

/**
 * The fewest characters the heading field asks about: the server's
 * `vocabulary_copy.SUGGEST_MIN`, which answers 422 below it.
 */
export const HEADING_QUERY_FLOOR = 2;

/**
 * How long typing must pause before the heading field asks. Shorter than the
 * library search's `DEBOUNCE_MS`, because this reads a local copy rather than
 * the catalogue and a dropdown that lags a word behind is not offering anything.
 */
export const HEADING_SUGGEST_DEBOUNCE_MS = 300;

export interface UseBookHeadingFieldResult {
  /** The vocabularies offered from. Empty draws no field: the setting is off,
   * library mode is off, or no copy is loaded. */
  vocabularies: SuggestingVocabularyOut[];
  /** The vocabulary asked, the first offered until one is chosen. */
  scheme: string;
  chooseScheme: (scheme: string) => void;
  typed: string;
  type: (text: string) => void;
  /** The headings offered for what was typed, after the pause. */
  suggestions: ClassificationOut[];
  /** Write the picked heading onto the book, and clear the field. */
  pick: (heading: ClassificationOut) => void;
  isPicking: boolean;
  error: unknown;
}

/**
 * The heading field: headings offered from a local vocabulary copy as the
 * cataloguer types, and the one picked written onto the book.
 *
 * **Asks once typing pauses**, `HEADING_SUGGEST_DEBOUNCE_MS`, and not below
 * `HEADING_QUERY_FLOOR` characters, so a word typed is one request rather than
 * one per letter. Always for a subject, since that is what this field adds.
 */
export function useBookHeadingField(bookId: number): UseBookHeadingFieldResult {
  const invalidate = useInvalidate();
  // A household never has the field, so it never asks: the server would
  // answer an empty list anyway.
  const libraryMode = useLibraryMode();
  const vocabularies = useListSuggestingVocabularies(bookId, {
    query: { enabled: libraryMode },
  });
  const offered = vocabularies.data ?? [];
  const [chosen, chooseScheme] = useState<string | undefined>(undefined);
  const scheme = schemeAsked(chosen, offered);
  const [typed, type] = useState("");
  const [asked, setAsked] = useDebouncedText(typed);
  const suggestions = useHeadingSuggestions(bookId, scheme, asked);
  const add = useAddHeading({
    mutation: {
      onSuccess: () => {
        type("");
        setAsked("");
        invalidate.catalogue();
      },
    },
  });

  return {
    vocabularies: offered,
    scheme,
    chooseScheme,
    typed,
    type,
    suggestions: suggestions.headings,
    // The suggestion is already the row an import writes, so it is posted
    // back as it came: the server, not this hook, owns that form.
    pick: (heading) =>
      add.mutate({
        bookId,
        data: {
          scheme: heading.scheme,
          number: heading.number,
          label: heading.label,
        },
      }),
    isPicking: add.isPending,
    error: firstError(vocabularies.error, suggestions.error, add.error),
  };
}

/** The vocabulary asked: the one chosen, else the first offered. */
function schemeAsked(
  chosen: string | undefined,
  offered: SuggestingVocabularyOut[],
): string {
  return chosen ?? offered[0]?.scheme ?? "";
}

/** `typed` once it has stood for `HEADING_SUGGEST_DEBOUNCE_MS`, trimmed. */
function useDebouncedText(typed: string): [string, (text: string) => void] {
  const [settled, setSettled] = useState("");
  useEffect(() => {
    const timer = setTimeout(
      () => setSettled(typed.trim()),
      HEADING_SUGGEST_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [typed]);
  return [settled, setSettled];
}

/** The headings offered for `asked`, and nothing below the floor. */
function useHeadingSuggestions(
  bookId: number,
  scheme: string,
  asked: string,
): { headings: ClassificationOut[]; error: unknown } {
  const ready = scheme !== "" && asked.length >= HEADING_QUERY_FLOOR;
  const suggestions = useSuggestHeadings(
    bookId,
    { scheme, q: asked, use: HeadingUse.subject },
    { query: { enabled: ready } },
  );
  return {
    // Only for what is asked now: a stale answer under a cleared field would
    // offer headings for a word nobody is typing.
    headings: ready ? (suggestions.data ?? []) : [],
    error: suggestions.error,
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
 * page that already makes nine. Counted 2026-08-27 with both feature flags
 * off, which is the fewest this page ever makes.
 */
export function useBookCopies(bookId: number): UseBookCopiesResult {
  const invalidate = useInvalidate();
  const copies = useListCopies(bookId);

  const add = useAddCopy({
    mutation: {
      onSuccess: () => {
        // A new copy is a new book, so the shelf list, the counts and the
        // statistics move with it, not only `copy_count` on this one.
        invalidate.catalogue();
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

export interface UseBookFilesResult {
  /** Where this book's files were reported to be, oldest report first. */
  references: DigitalReferenceOut[];
  /** Forget one location, after confirming. `shownAs` is the path as drawn. */
  forget: (reference: DigitalReferenceOut, shownAs: string) => void;
  /** The references being forgotten right now, by id. */
  forgetting: ReadonlySet<number>;
  /** Why the list could not be read, apart from why a forget failed: the
   * first would otherwise be a panel quietly claiming there are no files. */
  listError: unknown;
  error: unknown;
}

/**
 * Where this book's files have been said to be.
 *
 * **Read only through the per book route**, so a reference reaches this page
 * exactly when its book does: the route answers 404 for a book the reader
 * cannot see, and the privacy rule is the book query's rather than anything
 * here. Its own request rather than a field on `BookOut`, for the reason the
 * route's docstring gives.
 *
 * Forget is the only write. Reporting a location is the scan page's folder
 * pick, and flagging one missing is for a re-check that does not exist yet.
 */
export function useBookFiles(bookId: number): UseBookFilesResult {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const references = useListDigitalReferences(bookId);

  const forget = useRowWrite(
    getForgetDigitalReferenceMutationOptions,
    "referenceId",
    () => {
      void queryClient.invalidateQueries({
        queryKey: getListDigitalReferencesQueryKey(bookId),
      });
    },
  );

  return {
    references: references.data ?? [],
    forget: (reference, shownAs) => {
      // Asked, where removing a tag is not: the way back is picking that
      // folder again on the scan page, which is nowhere near this button.
      if (confirm(t("files.forgetConfirm", { path: shownAs })))
        forget.mutate({ bookId, referenceId: reference.id });
    },
    forgetting: forget.pendingRows,
    listError: references.error,
    error: forget.error,
  };
}

export interface UseBookCoverImagesResult {
  /** The further images kept of this book, oldest first. */
  images: CoverImageOut[];
  /** Keep one more image. */
  upload: (file: File) => void;
  isUploading: boolean;
  /** Let one image go, after confirming. */
  remove: (image: CoverImageOut) => void;
  /** Make one image the shelf cover; the old cover takes its place. */
  shelve: (image: CoverImageOut) => void;
  /** The images being removed or shelved right now, by id. */
  busy: ReadonlySet<number>;
  /** Why the list could not be read, apart from why a write failed. */
  listError: unknown;
  error: unknown;
}

/**
 * A back cover, a spine, a dust jacket: images kept beside the shelf cover.
 *
 * **Read only through the per book route**, as the file references are, so an
 * image reaches this page exactly when its book does. Shelving one rewrites
 * the book's `cover_url`, so it drops the book as well as this list; the other
 * two writes touch nothing a listing shows.
 */
export function useBookCoverImages(bookId: number): UseBookCoverImagesResult {
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const { t } = useTranslation();
  const images = useListCoverImages(bookId);
  const dropList = () =>
    void queryClient.invalidateQueries({
      queryKey: getListCoverImagesQueryKey(bookId),
    });

  const upload = useUploadCoverImage({ mutation: { onSuccess: dropList } });
  const remove = useRowWrite(
    getDeleteCoverImageMutationOptions,
    "imageId",
    dropList,
  );
  const shelve = useRowWrite(
    getShelveCoverImageMutationOptions,
    "imageId",
    () => {
      dropList();
      invalidate.book(bookId);
    },
  );

  return {
    images: images.data ?? [],
    upload: (file) => upload.mutate({ bookId, data: { file } }),
    isUploading: upload.isPending,
    remove: (image) => {
      // Asked, because nothing brings an uploaded image back.
      if (confirm(t("coverImages.removeConfirm")))
        remove.mutate({ bookId, imageId: image.id });
    },
    shelve: (image) => shelve.mutate({ bookId, imageId: image.id }),
    busy: new Set([...remove.pendingRows, ...shelve.pendingRows]),
    listError: images.error,
    error: upload.error ?? remove.error ?? shelve.error,
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
  // The catalogue rather than the book: applying an edition writes the title,
  // the author, the publisher and the year, so the author and series indexes
  // move with it.
  const invalidate = useInvalidate();
  const isConfigured = useGoogleBooksReady();
  const [isPickerOpen, setIsPickerOpen] = useState(false);

  const candidates = useEnrichmentCandidates(bookId, {
    query: {
      // Only once the picker is open. Fetching on mount would put eight
      // catalogue requests behind every book anybody looks at.
      enabled: isPickerOpen,
      retry: false,
      staleTime: 5 * 60_000,
    },
  });

  const apply = useApplyEnrichment({
    mutation: {
      onSuccess: () => {
        invalidate.catalogue();
        setIsPickerOpen(false);
      },
    },
  });

  return {
    // No key is required any more: Open Library and the national catalogues
    // answer without one. The flag now only decides the note about what a key
    // would add.
    isEnabled: true,
    isConfigured,

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

export interface UseBookKosyncResult {
  /** The member's KOReader documents linked to this book. */
  linked: KosyncDocumentOut[];
  /** Their documents no book is linked to yet. */
  waiting: KosyncDocumentOut[];
  link: (document: string) => void;
  unlink: (document: string) => void;
  isSaving: boolean;
  error: unknown;
}

/**
 * The member's KOReader documents, as this book sees them.
 *
 * **The inbox is linked from here rather than from a picker in Settings**,
 * because here the book is already chosen: linking is one press, where a
 * picker would be a search across the whole catalogue. Both lists are only
 * ever the caller's own.
 *
 * A link writes the reading log and may mark the book read, so it refreshes
 * the book and its log along with the two lists.
 */
export function useBookKosync(bookId: number): UseBookKosyncResult {
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const linked = useListKosyncDocuments(bookId);
  const waiting = useListKosyncInbox();

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getListKosyncDocumentsQueryKey(bookId),
      });
      void queryClient.invalidateQueries({
        queryKey: getListKosyncInboxQueryKey(),
      });
      void queryClient.invalidateQueries({
        queryKey: getListProgressQueryKey(bookId),
      });
      invalidate.book(bookId);
    },
  };
  const link = useLinkKosyncDocument({ mutation });
  const unlink = useUnlinkKosyncDocument({ mutation });

  return {
    linked: linked.data ?? [],
    waiting: waiting.data ?? [],
    // `mutate`, not `mutateAsync`: nothing awaits these.
    link: (document) => link.mutate({ bookId, document }),
    unlink: (document) => unlink.mutate({ bookId, document }),
    isSaving: link.isPending || unlink.isPending,
    error: link.error ?? unlink.error,
  };
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
  const invalidate = useInvalidate();
  const entries = useListProgress(bookId);

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getListProgressQueryKey(bookId),
      });
      // Recording a position moves `my_progress_*` on the book, and the first
      // one moves `my_status` with it.
      invalidate.book(bookId);
    },
  };

  const record = useAddProgress({ mutation });
  const remove = useRowWrite(
    getDeleteProgressMutationOptions,
    "progressId",
    mutation.onSuccess,
  );

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

/**
 * This page's own localStorage entry.
 *
 * Named here rather than inside `sectionState`, because the settings page also
 * has a section called `about`: one shared key would let a reader close the
 * blurb on a book and find the app's about card closed too.
 */
const STORE = "bookDetailSections";

/**
 * The collapsible groups, in the order they are drawn.
 *
 * The ids are what reaches storage, so renaming one forgets what readers said
 * about it. `sectionState` keeps the orphaned entry rather than choking on it.
 */
export const BOOK_SECTIONS = [
  "reading",
  "filing",
  "copies",
  "lending",
  "writing",
  "about",
] as const;

export type BookSection = (typeof BOOK_SECTIONS)[number];

export interface UseBookSectionsResult {
  isOpen: (section: BookSection) => boolean;
  toggle: (section: BookSection) => void;
}

/**
 * Which sections a book opens with, before anybody has said otherwise.
 *
 * Every condition here is answered by the book the page already holds, so a
 * section decides its own default at first paint instead of flickering open
 * when a second request lands. That constraint is what picked the conditions:
 *
 * | Section | Default | Why |
 * |---|---|---|
 * | reading | open | What a reader came to the page for. |
 * | filing | open | The same, and the controls a library edits most. |
 * | copies | `copy_count > 1` | One copy needs no list of copies. |
 * | lending | the book is out | A book somebody has does not hide who. |
 * | writing | closed | See below. |
 * | about | open | It is drawn only when there is something in it. |
 *
 * **Writing is the one fixed default with data behind it, and it is fixed
 * because the data is not here.** `BookOut` carries no note or quote count:
 * the counts arrive from `/notes` and `/quotes`, which are separate requests,
 * so a conditional default could only open the section after they land, which
 * is the flicker. Closed is also the honest guess, because notes and quotes
 * are empty on most books in a library catalogue. Put a count on `BookOut`
 * and this becomes conditional like the rest.
 *
 * `about` is fixed for the opposite reason: `hasAbout()` decides whether it is
 * drawn at all, so by the time this answers, there is a blurb or a category to
 * show. It still collapses, because a blurb is long and somebody who never
 * reads them should be able to fold it away once and for good.
 */
export function sectionDefaults(book: BookOut): Record<BookSection, boolean> {
  return {
    reading: true,
    filing: true,
    copies: (book.copy_count ?? 1) > 1,
    lending: book.active_loan != null,
    writing: false,
    about: true,
  };
}

/**
 * Whether the `about` section has anything to draw.
 *
 * A handle that opens onto nothing is worse than no handle. The lending
 * section keeps its handle on a book nobody borrowed because it still offers
 * the act of lending; `about` offers no action at all, it is what the
 * catalogue happens to know, so on a hand typed book it is not drawn.
 */
export function hasAbout(book: BookOut): boolean {
  return (
    Boolean(book.description) ||
    (book.categories != null && book.categories.length > 0)
  );
}

/**
 * Open or closed, per section, remembered per device.
 *
 * The only hook here that talks to storage rather than the API. Takes the
 * defaults the *book* implies and lets a stored choice override them, which is
 * the three state rule `resolveOpen()` holds: a section nobody has touched
 * follows the book, and a section somebody has touched follows them.
 *
 * `null` means the book has not arrived. A `Record` over every section rather
 * than a partial, so adding a section without deciding its default is a
 * compile error rather than a silently closed panel.
 */
export function useBookSections(
  bookId: number,
  defaults: Record<BookSection, boolean> | null,
): UseBookSectionsResult {
  // Read once, on mount: storage is a starting point, and re-reading it on
  // every render would fight the state this component already holds.
  //
  // **This is the one place a second copy of a stored value is correct, and it
  // was deliberately left alone when the preference door was written.** Every
  // other reader of a preference subscribes to storage and holds nothing, which
  // is what removed a counter from the library page. Here the copy is what
  // delivers a promise `lib/sectionState.ts` makes: when storage refuses the
  // write, the section still folds for this visit, which is the part the reader
  // can see. Subscribing instead would mean a tap on a section header doing
  // nothing at all in a private window, and unlike the view's three labelled
  // buttons a header that does not fold reads as broken rather than as refused.
  const [choices, setChoices] = useState<SectionChoices>(() =>
    readSectionChoices(STORE),
  );

  // Frozen per book, because the defaults describe the book *on arrival*. Left
  // live, marking a loan returned would flip the lending default to closed and
  // fold the section away under the hand that just used it.
  //
  // Keyed on the book id, not on the ref being empty. `routes.tsx` renders
  // this route with no `key`, so walking from one book to another (the copies
  // section links straight to a sibling copy) reuses the component instance:
  // a ref that only ever arms once would hand the second book the first one's
  // loan, its copy count and its blurb.
  const arrival = useRef<Arrival | null>(null);
  const onArrival = arrivalDefaults(arrival, bookId, defaults);

  const isOpen = (section: BookSection) =>
    resolveOpen(choices[section], onArrival?.[section] ?? false);

  return {
    isOpen,
    toggle: (section: BookSection) => {
      const next = !isOpen(section);
      writeSectionChoice(STORE, section, next);
      setChoices((current) => ({
        ...current,
        [section]: next ? "open" : "closed",
      }));
    },
  };
}

/** The defaults one book arrived with, frozen for as long as it is on screen. */
interface Arrival {
  bookId: number;
  defaults: Record<BookSection, boolean>;
}

/**
 * Arm `arrival` with `defaults` the first render they exist for `bookId`, and
 * read back what it holds. `useBookSections` says why it is keyed on the id.
 */
function arrivalDefaults(
  arrival: { current: Arrival | null },
  bookId: number,
  defaults: Record<BookSection, boolean> | null,
): Record<BookSection, boolean> | undefined {
  if (defaults !== null && arrival.current?.bookId !== bookId)
    arrival.current = { bookId, defaults };
  return arrival.current?.defaults;
}
