/**
 * The scan → lookup → confirm flow.
 *
 * ScanPage's whole contact with the API. The page and its components take
 * plain values and callbacks.
 */

import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import {
  getLookupIsbnQueryKey,
  lookupIsbn,
  useAddBookTag,
  useListTags,
  useLookupIsbn,
  useScanAdd,
  useSearchGoogleBooks,
  useUploadCover,
} from "../../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../../api/generated/endpoints/settings/settings";
import type { GoogleBooksMatch, TagOut } from "../../api/generated/model";
import {
  blankDraft,
  draftFromGoogleMatch,
  draftFromLookup,
  type BookDraft,
} from "./types";

/** Below this, a search is noise rather than a query. Matches the API bound. */
const MIN_QUERY_LENGTH = 2;

export interface UseScanFlowResult {
  isbn: string | null;
  draft: BookDraft | null;
  setDraft: (draft: BookDraft) => void;
  tags: TagOut[];

  lookup: (isbn: string) => void;
  isLookingUp: boolean;

  /** Prefill the confirm step from a chosen search result. */
  chooseMatch: (match: GoogleBooksMatch) => void;

  selectedTagIds: number[];
  toggleTag: (tagId: number) => void;

  coverFile: File | null;
  setCoverFile: (file: File | null) => void;
  isPrivate: boolean;
  setIsPrivate: (isPrivate: boolean) => void;

  confirm: () => void;
  isAdding: boolean;
  error: unknown;
  reset: () => void;
}

export function useScanFlow(
  onAdded: (bookId: number) => void,
): UseScanFlowResult {
  const [isbn, setIsbn] = useState<string | null>(null);
  const [draft, setDraft] = useState<BookDraft | null>(null);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [isPrivate, setIsPrivate] = useState(false);
  const [addError, setAddError] = useState<unknown>(null);

  const queryClient = useQueryClient();
  const tags = useListTags();

  // Only runs once an ISBN has been scanned or typed.
  const lookupQuery = useLookupIsbn(
    { isbn: isbn ?? "" },
    {
      query: {
        enabled: isbn !== null,
        retry: false,
        // A 404 here is an ordinary outcome: the ISBN is unknown to both
        // sources, so it is handled below rather than surfaced as an error.
      },
    },
  );

  // Fold the query result into the editable draft exactly once per lookup.
  if (isbn !== null && draft === null && !lookupQuery.isPending) {
    if (lookupQuery.data) {
      const next = draftFromLookup(lookupQuery.data);
      setDraft(next);
      setSelectedTagIds(next.suggested_tag_ids ?? []);
    } else if (lookupQuery.error) {
      // Neither source knew it: offer manual entry rather than a dead end.
      setDraft(blankDraft(isbn));
      setSelectedTagIds([]);
    }
  }

  const scanAdd = useScanAdd();
  const uploadCover = useUploadCover();
  const addTag = useAddBookTag();

  function reset() {
    setIsbn(null);
    setDraft(null);
    setSelectedTagIds([]);
    setCoverFile(null);
    setIsPrivate(false);
    setAddError(null);
  }

  async function confirm() {
    if (!draft) return;
    setAddError(null);

    // Strip the client-only fields: neither is a column.
    const {
      notFound: _notFound,
      suggested_tag_ids: _suggested,
      ...fields
    } = draft;

    try {
      const book = await scanAdd.mutateAsync({
        data: { ...fields, is_private: isPrivate },
      });

      // The book exists by now. A failed cover or tag is not worth discarding
      // it and making the member scan again, so these are best-effort.
      if (coverFile) {
        await uploadCover
          .mutateAsync({ bookId: book.id, data: { file: coverFile } })
          .catch(() => undefined);
      }
      await Promise.all(
        selectedTagIds.map((tagId) =>
          addTag.mutateAsync({ bookId: book.id, tagId }).catch(() => undefined),
        ),
      );

      void queryClient.invalidateQueries();
      onAdded(book.id);
    } catch (error) {
      setAddError(error);
    }
  }

  function chooseMatch(match: GoogleBooksMatch) {
    const next = draftFromGoogleMatch(match);
    setAddError(null);
    // Setting the ISBN would restart the lookup query and overwrite the draft
    // with whatever Open Library says. The record is already chosen, so the
    // scan flow stays parked at null and the draft carries the ISBN instead.
    setIsbn(null);
    setDraft(next);
    setSelectedTagIds(next.suggested_tag_ids ?? []);
  }

  return {
    isbn,
    draft,
    setDraft,
    tags: tags.data ?? [],

    chooseMatch,

    lookup: (nextIsbn) => {
      setDraft(null);
      setAddError(null);
      setIsbn(nextIsbn);
    },
    isLookingUp: isbn !== null && draft === null,

    selectedTagIds,
    toggleTag: (tagId) =>
      setSelectedTagIds((current) =>
        current.includes(tagId)
          ? current.filter((id) => id !== tagId)
          : [...current, tagId],
      ),

    coverFile,
    setCoverFile,
    isPrivate,
    setIsPrivate,

    confirm: () => void confirm(),
    isAdding: scanAdd.isPending,
    error: addError,
    reset,
  };
}

export interface UseGoogleSearchResult {
  /** Whether to show the search box at all. Follows the admin's toggle. */
  isEnabled: boolean;
  /** Whether it will actually work: the toggle is on AND a key is stored. */
  isConfigured: boolean;
  query: string;
  setQuery: (query: string) => void;
  /** Runs only once submitted: nobody wants a request per keystroke here. */
  submit: () => void;
  clear: () => void;
  matches: GoogleBooksMatch[];
  isSearching: boolean;
  /** True once a search has run and come back with nothing. */
  isEmpty: boolean;
  error: unknown;
}

/**
 * Finding a book by title when there is no barcode to scan.
 *
 * The query is submitted explicitly rather than debounced. Each search is a
 * billed call against somebody's Google Books quota, and typing "the hobbit"
 * would spend ten of them to answer one question.
 */
export function useGoogleSearch(): UseGoogleSearchResult {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });

  const search = useSearchGoogleBooks(
    { q: submitted, limit: 10 },
    {
      query: {
        enabled: submitted.length >= MIN_QUERY_LENGTH,
        retry: false,
        // Results for a given phrase do not change minute to minute, and
        // going back to edit a draft should not re-spend the quota.
        staleTime: 5 * 60_000,
      },
    },
  );

  return {
    isEnabled: flags.data?.google_books_enabled ?? false,
    isConfigured: flags.data?.google_books_ready ?? false,
    query,
    setQuery,
    submit: () => setSubmitted(query.trim()),
    clear: () => {
      setQuery("");
      setSubmitted("");
    },
    matches: search.data ?? [],
    isSearching: search.isFetching,
    isEmpty:
      submitted.length >= MIN_QUERY_LENGTH &&
      !search.isFetching &&
      search.data?.length === 0,
    error: search.error,
  };
}

/** One book caught by the rapid scanner, and how its lookup went. */
export interface ScannedEntry {
  isbn: string;
  state: "looking-up" | "found" | "not-found";
  draft: BookDraft | null;
}

export interface UseRapidIntakeResult {
  isActive: boolean;
  start: () => void;
  stop: () => void;
  entries: ScannedEntry[];
  /** Feed a scanned barcode in. Repeats are ignored rather than queued twice. */
  capture: (isbn: string) => void;
  remove: (isbn: string) => void;
  clear: () => void;

  addAll: () => void;
  isAdding: boolean;
  result: { added: number; failed: number } | null;
}

/**
 * Scanning a shelf rather than a book.
 *
 * The ordinary flow is scan, look up, confirm, repeat, which is right for one
 * book and unusable for three hundred. Cataloguing an existing shelf is the
 * moment most people abandon a library app, so this mode keeps the camera
 * running, looks each hit up in the background, and asks for one confirmation
 * at the end.
 *
 * Nothing is written until `addAll`. A scanner that wrote as it went would
 * turn a misread barcode into a row somebody has to find and delete later.
 */
export function useRapidIntake(): UseRapidIntakeResult {
  const [isActive, setIsActive] = useState(false);
  const [entries, setEntries] = useState<ScannedEntry[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [result, setResult] = useState<{
    added: number;
    failed: number;
  } | null>(null);

  const queryClient = useQueryClient();
  const scanAdd = useScanAdd();

  function capture(isbn: string) {
    setEntries((current) => {
      // The camera fires continuously while a barcode is in frame, so the same
      // book arrives many times a second. Without this the queue fills with
      // one book.
      if (current.some((entry) => entry.isbn === isbn)) return current;
      void lookUp(isbn);
      return [...current, { isbn, state: "looking-up", draft: null }];
    });
  }

  async function lookUp(isbn: string) {
    try {
      const lookup = await queryClient.fetchQuery({
        queryKey: getLookupIsbnQueryKey({ isbn }),
        queryFn: () => lookupIsbn({ isbn }),
        staleTime: 60_000,
      });
      setEntries((current) =>
        current.map((entry) =>
          entry.isbn === isbn
            ? { ...entry, state: "found", draft: draftFromLookup(lookup) }
            : entry,
        ),
      );
    } catch {
      // Neither source knew it. Kept in the queue as a blank draft rather than
      // dropped, so it can still be added by hand instead of silently vanishing
      // between the shelf and the catalogue.
      setEntries((current) =>
        current.map((entry) =>
          entry.isbn === isbn
            ? { ...entry, state: "not-found", draft: blankDraft(isbn) }
            : entry,
        ),
      );
    }
  }

  async function addAll() {
    const ready = entries.filter((entry) => entry.draft !== null);
    if (ready.length === 0) return;

    setIsAdding(true);
    let added = 0;
    let failed = 0;

    for (const entry of ready) {
      const draft = entry.draft!;
      const {
        notFound: _notFound,
        suggested_tag_ids: _suggested,
        ...fields
      } = draft;
      try {
        // Sequential rather than Promise.all: a 300-book batch would otherwise
        // open 300 concurrent requests against one SQLite writer, and a
        // duplicate ISBN 409 needs to be attributed to a specific book.
        await scanAdd.mutateAsync({ data: { ...fields, is_private: false } });
        added += 1;
      } catch {
        failed += 1;
      }
    }

    void queryClient.invalidateQueries();
    setEntries([]);
    setIsAdding(false);
    setResult({ added, failed });
  }

  return {
    isActive,
    start: () => {
      setResult(null);
      setIsActive(true);
    },
    stop: () => setIsActive(false),
    entries,
    capture,
    remove: (isbn) =>
      setEntries((current) => current.filter((entry) => entry.isbn !== isbn)),
    clear: () => setEntries([]),
    addAll: () => void addAll(),
    isAdding,
    result,
  };
}
