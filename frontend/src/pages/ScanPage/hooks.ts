/**
 * The scan → lookup → confirm flow.
 *
 * ScanPage's whole contact with the API. The page and its components take
 * plain values and callbacks.
 */

import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { errorText } from "../../components/ErrorState";
import { ApiError } from "../../api/mutator";

import {
  getLookupIsbnQueryKey,
  lookupIsbn,
  getListTagsQueryKey,
  useAddBookTag,
  useAddCopy,
  useCreateTag,
  useListLocations,
  useListTags,
  useLookupIsbn,
  useScanAdd,
  useSearchBooks,
  useUploadCover,
} from "../../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../../api/generated/endpoints/settings/settings";
import { BookFormat } from "../../api/generated/model";
import type { BookMatch, LocationOut, TagOut } from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import {
  normaliseLocation,
  readLastLocation,
  rememberLastLocation,
} from "../../lib/lastLocation";
import {
  blankDraft,
  draftFromMatch,
  draftFromLookup,
  type BookDraft,
} from "./types";

/** Below this, a search is noise rather than a query. Matches the API bound. */
const MIN_QUERY_LENGTH = 2;

/**
 * The shelves already in use, for the location suggestions.
 *
 * Cached for five minutes: the set of shelves in a household changes about
 * once a month, and re-fetching it per scanned book would be a request per
 * barcode for a list that has not moved.
 */
function useKnownLocations(): LocationOut[] {
  const locations = useListLocations({ query: { staleTime: 5 * 60_000 } });
  return locations.data ?? [];
}

export interface UseScanFlowResult {
  isbn: string | null;
  draft: BookDraft | null;
  setDraft: (draft: BookDraft) => void;
  tags: TagOut[];

  lookup: (isbn: string) => void;
  isLookingUp: boolean;

  /** Prefill the confirm step from a chosen search result. */
  chooseMatch: (match: BookMatch) => void;

  selectedTagIds: number[];
  toggleTag: (tagId: number) => void;
  /**
   * Invent a tag and select it for this book. Nothing is attached yet: the
   * book does not exist until confirm, so the new tag joins `selectedTagIds`
   * and is applied with the rest.
   */
  createTag: (name: string) => void;
  isCreatingTag: boolean;

  coverFile: File | null;
  setCoverFile: (file: File | null) => void;
  isPrivate: boolean;
  setIsPrivate: (isPrivate: boolean) => void;
  /**
   * Where this copy goes. Carried over from the last book added rather than
   * cleared, because a shelf is catalogued in one sitting.
   */
  location: string;
  setLocation: (location: string) => void;
  /** Shelves already in use, for the suggestions. */
  locations: LocationOut[];
  /**
   * Hardback or paperback. Offered here because the person scanning is
   * holding the book, which is the one moment they can answer without going
   * to look.
   */
  format: BookFormat | "";
  setFormat: (format: BookFormat | "") => void;

  confirm: () => void;
  isAdding: boolean;
  error: unknown;
  reset: () => void;

  /**
   * Record the scanned book as a second copy of the one already here.
   *
   * Reads the id off the 409 itself rather than taking one, so there is one
   * place that knows which book the conflict was about. Does nothing when
   * there was no conflict, or when the holder is somebody else's private book
   * and its id was withheld.
   */
  addCopy: () => void;
  isAddingCopy: boolean;
}

export function useScanFlow(
  onAdded: (bookId: number) => void,
): UseScanFlowResult {
  const [isbn, setIsbn] = useState<string | null>(null);
  const [draft, setDraft] = useState<BookDraft | null>(null);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [isPrivate, setIsPrivate] = useState(false);
  const [location, setLocation] = useState(readLastLocation);
  const [format, setFormat] = useState<BookFormat | "">("");
  const [addError, setAddError] = useState<unknown>(null);

  const queryClient = useQueryClient();
  const tags = useListTags();
  const locations = useKnownLocations();

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
  const addAnotherCopy = useAddCopy();
  const uploadCover = useUploadCover();
  const addTag = useAddBookTag();

  const createTag = useCreateTag({
    mutation: {
      onSuccess: (tag) => {
        setSelectedTagIds((current) =>
          current.includes(tag.id) ? current : [...current, tag.id],
        );
        void queryClient.invalidateQueries({ queryKey: getListTagsQueryKey() });
      },
    },
  });

  function reset() {
    setIsbn(null);
    setDraft(null);
    setSelectedTagIds([]);
    setCoverFile(null);
    setIsPrivate(false);
    setFormat("");
    setAddError(null);
    // `location` is deliberately not reset. It is the one field that is the
    // same for the next book far more often than not, and clearing it here
    // would undo the carry-over on every cancel.
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

    const shelf = normaliseLocation(location);

    try {
      const book = await scanAdd.mutateAsync({
        data: {
          ...fields,
          is_private: isPrivate,
          location: shelf || null,
          format: format || null,
        },
      });

      // Only after the write succeeded. Remembering a shelf for a book that
      // was rejected as a duplicate would carry a value nothing was filed at.
      rememberLastLocation(shelf);

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

  /**
   * Add the scanned book as another copy of the one already in the catalogue.
   *
   * **The draft's tags and uploaded cover are not carried over**, unlike
   * `confirm()`, which applies both. Neither belongs to the copy: the tags come
   * from the book being copied, which already has them, and a cover uploaded
   * here would be a photo of the same edition. Both are editable on the new
   * copy's own page, and the UI says so before the press.
   */
  async function addCopy() {
    const holder = addError instanceof ApiError ? addError.bookId : undefined;
    // Nothing to copy: either there was no conflict, or the book that holds
    // the ISBN is somebody else's private one and its id was withheld.
    if (holder === undefined) return;

    const shelf = normaliseLocation(location);
    setAddError(null);
    try {
      // Only the per-copy fields. The work is taken from the book being
      // copied, which is what stops two rows claiming to be copies of each
      // other while naming different books.
      const copy = await addAnotherCopy.mutateAsync({
        bookId: holder,
        data: { location: shelf || null, format: format || null },
      });
      rememberLastLocation(shelf);
      void queryClient.invalidateQueries();
      onAdded(copy.id);
    } catch (error) {
      setAddError(error);
    }
  }

  function chooseMatch(match: BookMatch) {
    const next = draftFromMatch(match);
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
    createTag: (name) => createTag.mutate({ data: { name } }),
    isCreatingTag: createTag.isPending,
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
    location,
    setLocation,
    locations,
    format,
    setFormat,

    confirm: () => void confirm(),
    isAdding: scanAdd.isPending,
    error: addError,
    reset,

    addCopy: () => void addCopy(),
    isAddingCopy: addAnotherCopy.isPending,
  };
}

export interface UseBookSearchResult {
  /**
   * Whether Google Books is configured. Search works either way: this only
   * decides whether the panel mentions what a key would add.
   */
  isConfigured: boolean;
  query: string;
  setQuery: (query: string) => void;
  /** Runs only once submitted: nobody wants a request per keystroke here. */
  submit: () => void;
  clear: () => void;
  matches: BookMatch[];
  isSearching: boolean;
  /** True once a search has run and come back with nothing. */
  isEmpty: boolean;
  error: unknown;
}

/**
 * Finding a book by title when there is no barcode to scan.
 *
 * The query is submitted explicitly rather than debounced. A search may spend
 * a call against somebody's Google Books quota when one is configured, and
 * typing "the hobbit" would spend ten of them to answer one question. It is
 * also two public catalogues being asked on every keystroke, which is not a
 * polite thing to do to either of them.
 */
export function useBookSearch(): UseBookSearchResult {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const { locale } = useTranslation();

  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });

  const search = useSearchBooks(
    // The reader's own language breaks ties towards the printing they are
    // most likely to be holding. It never outranks a title match, so an
    // English title searched from a German interface still comes back first.
    { q: submitted, limit: 10, lang: locale },
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

/** One book caught by the rapid scanner, and how it has gone so far. */
export interface ScannedEntry {
  isbn: string;
  state: "looking-up" | "found" | "not-found" | "failed";
  draft: BookDraft | null;
  /** Why it could not be added, once the batch has run. */
  reason?: string;
}

export interface UseRapidIntakeResult {
  isActive: boolean;
  start: () => void;
  stop: () => void;
  entries: ScannedEntry[];
  /**
   * The shelf every book in this run is filed on.
   *
   * One value for the batch rather than one per book, because that is what a
   * rapid run physically is: somebody standing in front of one bookcase. It
   * is the single highest-value field here and the one most likely never to
   * be filled in if it has to be typed three hundred times afterwards.
   */
  location: string;
  setLocation: (location: string) => void;
  locations: LocationOut[];
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
  const [location, setLocation] = useState(readLastLocation);
  const [result, setResult] = useState<{
    added: number;
    failed: number;
  } | null>(null);

  const queryClient = useQueryClient();
  const scanAdd = useScanAdd();
  const locations = useKnownLocations();
  // For the per-row failure reason: a rejected fetch has no message worth
  // showing, so `errorText` needs the catalogue to supply one.
  const { t } = useTranslation();

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
    const shelf = normaliseLocation(location);
    let added = 0;
    const failures: ScannedEntry[] = [];

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
        await scanAdd.mutateAsync({
          data: { ...fields, is_private: false, location: shelf || null },
        });
        added += 1;
      } catch (error) {
        // Kept, with its reason, rather than counted. "6 could not be added"
        // after scanning a shelf of thirty is unrecoverable: nothing says
        // which six, and the queue that knew has just been cleared.
        failures.push({
          ...entry,
          state: "failed",
          reason: errorText(error, "", t),
        });
      }
    }

    if (added > 0) rememberLastLocation(shelf);
    void queryClient.invalidateQueries();
    // Only the ones that landed leave the queue. What is left is exactly what
    // still needs a decision.
    setEntries(failures);
    setIsAdding(false);
    setResult({ added, failed: failures.length });
  }

  return {
    isActive,
    start: () => {
      setResult(null);
      setIsActive(true);
    },
    stop: () => setIsActive(false),
    entries,
    location,
    setLocation,
    locations,
    capture,
    remove: (isbn) =>
      setEntries((current) => current.filter((entry) => entry.isbn !== isbn)),
    clear: () => setEntries([]),
    addAll: () => void addAll(),
    isAdding,
    result,
  };
}
