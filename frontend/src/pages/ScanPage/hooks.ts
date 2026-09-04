/**
 * The scan → lookup → confirm flow.
 *
 * ScanPage's whole contact with the API. The page and its components take
 * plain values and callbacks.
 */

import { useCallback, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { errorText } from "../../components/ErrorState";
import { useInvalidate } from "../../api/invalidate";
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
import type {
  BookMatch,
  BookSearchOut,
  CatalogueSource,
  LocationOut,
  TagOut,
} from "../../api/generated/model";
import { useTranslation } from "../../i18n";
import {
  normaliseLocation,
  readLastLocation,
  rememberLastLocation,
} from "../../lib/lastLocation";
import {
  blankDraft,
  blankPending,
  draftFromMatch,
  draftFromLookup,
  toCopyRequest,
  toScanRequest,
  type BookDraft,
  type PendingBook,
} from "./types";

/** Below this, a search is noise rather than a query. Matches the API bound. */
const MIN_QUERY_LENGTH = 2;

/**
 * The shelves already in use, for the location suggestions.
 *
 * Cached for five minutes: the set of shelves in a library changes about
 * once a month, and re-fetching it per scanned book would be a request per
 * barcode for a list that has not moved.
 */
function useKnownLocations(): LocationOut[] {
  const locations = useListLocations({ query: { staleTime: 5 * 60_000 } });
  return locations.data ?? [];
}

export interface UseScanFlowResult {
  isbn: string | null;
  /** The book being added. Null `draft` means no lookup has landed yet. */
  pending: PendingBook;
  /**
   * Change one field of it or several, leaving the rest alone.
   *
   * One door rather than a setter per field, for the reason `PendingBook`
   * gives and the reason `useLibrary.update` gives: the two are the same
   * pattern and are spelled the same way on purpose.
   */
  update: (patch: Partial<PendingBook>) => void;
  tags: TagOut[];

  lookup: (isbn: string) => void;
  isLookingUp: boolean;

  /** Prefill the confirm step from a chosen search result. */
  chooseMatch: (match: BookMatch) => void;

  /**
   * Add or remove one tag. Not a patch: a caller passing one would have to
   * compute the next list itself at every call site.
   */
  toggleTag: (tagId: number) => void;
  /**
   * Invent a tag and select it for this book. Nothing is attached yet: the
   * book does not exist until confirm, so the new tag joins `pending.tagIds`
   * and is applied with the rest.
   */
  createTag: (name: string) => void;
  isCreatingTag: boolean;

  /** Shelves already in use, for the suggestions. */
  locations: LocationOut[];

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
  // One state for the whole book being built. The shelf is read from storage
  // once, as the initial value, so the first scan of a session starts on the
  // shelf the last one ended on.
  const [pending, setPending] = useState<PendingBook>(() =>
    blankPending(readLastLocation()),
  );
  const [addError, setAddError] = useState<unknown>(null);

  const update = useCallback(
    (patch: Partial<PendingBook>) =>
      setPending((current) => ({ ...current, ...patch })),
    [],
  );

  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
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
  if (isbn !== null && pending.draft === null && !lookupQuery.isPending) {
    if (lookupQuery.data) {
      const next = draftFromLookup(lookupQuery.data);
      update({ draft: next, tagIds: next.suggested_tag_ids ?? [] });
    } else if (lookupQuery.error) {
      // Neither source knew it: offer manual entry rather than a dead end.
      update({ draft: blankDraft(isbn), tagIds: [] });
    }
  }

  const scanAdd = useScanAdd();
  const addAnotherCopy = useAddCopy();
  const uploadCover = useUploadCover();
  const addTag = useAddBookTag();

  const createTag = useCreateTag({
    mutation: {
      onSuccess: (tag) => {
        setPending((current) =>
          current.tagIds.includes(tag.id)
            ? current
            : { ...current, tagIds: [...current.tagIds, tag.id] },
        );
        void queryClient.invalidateQueries({ queryKey: getListTagsQueryKey() });
      },
    },
  });

  function reset() {
    setIsbn(null);
    setAddError(null);
    // Everything except the shelf. It is the one field that is the same for
    // the next book far more often than not, and clearing it here would undo
    // the carry-over on every cancel.
    setPending((current) => blankPending(current.location));
  }

  async function confirm() {
    const { draft } = pending;
    if (!draft) return;
    setAddError(null);

    const shelf = normaliseLocation(pending.location);

    try {
      const book = await scanAdd.mutateAsync({
        data: toScanRequest({ ...pending, draft }),
      });

      // Only after the write succeeded. Remembering a shelf for a book that
      // was rejected as a duplicate would carry a value nothing was filed at.
      rememberLastLocation(shelf);

      // The book exists by now. A failed cover or tag is not worth discarding
      // it and making the member scan again, so these are best-effort.
      if (pending.coverFile) {
        await uploadCover
          .mutateAsync({ bookId: book.id, data: { file: pending.coverFile } })
          .catch(() => undefined);
      }
      await Promise.all(
        pending.tagIds.map((tagId) =>
          addTag.mutateAsync({ bookId: book.id, tagId }).catch(() => undefined),
        ),
      );

      // The catalogue, not the whole cache. A keyless invalidate here also
      // refetched `/api/settings/features` and, worse, `/api/books/search`,
      // which is a billed Google Books call the query's own `staleTime` exists
      // to avoid re-spending. Measured: 4 requests, of which 2 were about a
      // book having been added.
      invalidate.catalogue();
      onAdded(book.id);
    } catch (error) {
      setAddError(error);
    }
  }

  /**
   * Add the scanned book as another copy of the one already in the catalogue.
   *
   * **The draft's tags, uploaded cover and privacy tick are not carried over**,
   * unlike `confirm()`, which applies the first two. Neither of those belongs
   * to the copy: the tags come from the book being copied, which already has
   * them, and a cover uploaded here would be a photo of the same edition. Both
   * are editable on the new copy's own page, and the UI says so before the
   * press.
   *
   * **The privacy tick is the one worth knowing about.** A copy inherits
   * `is_private` from the book it copies, because `CopyCreate` has no such
   * field, so ticking private and then pressing this makes a **public** copy if
   * the book being copied is public. The checkbox sits directly above this
   * button and is inert for this press. The backend refusing to take a privacy
   * flag here is deliberate: privacy follows the Book, and a copy is a
   * different Book only in the sense of being a different row.
   */
  async function addCopy() {
    const holder = addError instanceof ApiError ? addError.bookId : undefined;
    // Nothing to copy: either there was no conflict, or the book that holds
    // the ISBN is somebody else's private one and its id was withheld.
    if (holder === undefined) return;

    const shelf = normaliseLocation(pending.location);
    setAddError(null);
    try {
      const copy = await addAnotherCopy.mutateAsync({
        bookId: holder,
        // `toCopyRequest`, not a literal. See its docstring: this was the
        // second writer of a request body and the one the schema guard could
        // not see.
        data: toCopyRequest(pending),
      });
      rememberLastLocation(shelf);
      // A copy is a new book. Same group as `confirm`, same reason.
      invalidate.catalogue();
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
    update({ draft: next, tagIds: next.suggested_tag_ids ?? [] });
  }

  return {
    isbn,
    pending,
    update,
    tags: tags.data ?? [],

    chooseMatch,

    lookup: (nextIsbn) => {
      update({ draft: null });
      setAddError(null);
      setIsbn(nextIsbn);
    },
    isLookingUp: isbn !== null && pending.draft === null,

    createTag: (name) => createTag.mutate({ data: { name } }),
    isCreatingTag: createTag.isPending,
    toggleTag: (tagId) =>
      setPending((current) => ({
        ...current,
        tagIds: current.tagIds.includes(tagId)
          ? current.tagIds.filter((id) => id !== tagId)
          : [...current.tagIds, tagId],
      })),

    locations,

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

  /**
   * The catalogues the search just run did not reach, because they are too slow
   * for its deadline. Non empty is the whole trigger for offering a longer one.
   *
   * **Read off the answer, never inferred from what was sent.** A request
   * asking for the slow catalogues gets an ordinary search when this library has
   * none switched on, and when the one long fan out allowed at a time is already
   * running. Either way this is what actually happened.
   */
  unasked: CatalogueSource[];
  /**
   * True when a search ran and reached no catalogue at all.
   *
   * A different state from finding nothing, and the reason it is a separate
   * field: every catalogue this library has switched on is a slow one, so "no
   * matches, try fewer words" would be the screen reporting a fact it never
   * checked.
   */
  askedNothing: boolean;
  /** Ask again, including the catalogues `unasked` names. */
  searchHarder: () => void;
  /** True while that longer search is in flight, rather than the ordinary one. */
  isSearchingHarder: boolean;
  /** True once the longer search has answered for the query on screen. */
  hasSearchedHarder: boolean;
}

/**
 * Whether this answer reached no catalogue **because they are all slow**.
 *
 * **Both halves, and the second is what stops a lie.** A query that reduces to
 * no usable terms also reaches nothing, and "and" and "a b" both do at the two
 * character minimum this box enforces. The server distinguishes them by
 * reporting nothing left to ask for that case, and reading only `asked` here
 * would tell somebody who typed "and" that every catalogue their library runs is
 * a slow one, which is a claim about their settings made by something that never
 * looked at them.
 */
function askedNothing(answer: BookSearchOut): boolean {
  return answer.asked.length === 0 && answer.unasked.length > 0;
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
  // **Per submitted query, and reset by every path that changes it.** Asking
  // harder is an answer to the question on screen; a new question has not been
  // asked harder yet, whatever the last one was.
  const [harder, setHarder] = useState(false);
  const { locale } = useTranslation();

  const flags = useGetFeatureFlags({ query: { staleTime: 60_000 } });

  const search = useSearchBooks(
    // The reader's own language breaks ties towards the printing they are
    // most likely to be holding. It never outranks a title match, so an
    // English title searched from a German interface still comes back first.
    //
    // `harder` is part of the parameters and so part of the query key, which is
    // what holds both answers in the cache: going back to a phrase that was
    // already searched hard does not spend the longer wait again.
    { q: submitted, limit: 10, lang: locale, harder },
    {
      query: {
        enabled: submitted.length >= MIN_QUERY_LENGTH,
        retry: false,
        // Results for a given phrase do not change minute to minute, and
        // going back to edit a draft should not re-spend the quota.
        staleTime: 5 * 60_000,
        // **The rows stay on screen while the longer search runs.** Pressing
        // the button changes the key, so without this the list blanks for up to
        // the whole of the longer deadline and takes with it the candidate the
        // reader was about to click.
        //
        // **Only across that flip, and a bare `keepPreviousData` was wrong.**
        // It held the previous answer across every key change, so `clear()`
        // emptied the box and left the results underneath it, which a test
        // caught. `harder` is only ever true while the question on screen is
        // the one those rows answer: submitting and clearing both reset it, so
        // this keeps them for the one transition that wants them and drops them
        // for the two that do not.
        placeholderData: (previous) => (harder ? previous : undefined),
      },
    },
  );

  const answered = !search.isFetching && search.data !== undefined;

  return {
    isConfigured: flags.data?.google_books_ready ?? false,
    query,
    setQuery,
    submit: () => {
      setHarder(false);
      setSubmitted(query.trim());
    },
    clear: () => {
      setHarder(false);
      setQuery("");
      setSubmitted("");
    },
    matches: search.data?.matches ?? [],
    isSearching: search.isFetching,
    isEmpty:
      submitted.length >= MIN_QUERY_LENGTH &&
      answered &&
      search.data.matches.length === 0 &&
      // Nothing asked is not nothing found, and the panel says something else
      // for it. Both would otherwise be true at once.
      !askedNothing(search.data),
    error: search.error,
    // **Only once the answer is in.** While a search is in flight the data on
    // hand is the previous query's, and offering a longer search off it would
    // name catalogues that have nothing to do with what is being typed.
    unasked: answered ? search.data.unasked : [],
    askedNothing: answered && askedNothing(search.data),
    // **A refetch when it is already true, not just the state flip.** A harder
    // search can be refused its long slot and answered as an ordinary one, and
    // that answer is cached under `harder: true` with `unasked` still populated,
    // so the offer stays on screen. Pressing it then sets a state that is
    // already set, React bails out of the render, the key does not change and
    // `staleTime` suppresses the request: the button would do nothing at all
    // for five minutes. The refusal is the one path `_HARDER_AT_ONCE` exists to
    // create, so the retry has to work or the server's fallback is a dead end.
    searchHarder: () => {
      if (harder) {
        void search.refetch();
        return;
      }
      setHarder(true);
    },
    isSearchingHarder: harder && search.isFetching,
    hasSearchedHarder: harder && answered,
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
  const invalidate = useInvalidate();
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
      try {
        // Sequential rather than Promise.all: a 300-book batch would otherwise
        // open 300 concurrent requests against one SQLite writer, and a
        // duplicate ISBN 409 needs to be attributed to a specific book.
        //
        // The same request builder as the one-book flow, so a field added
        // there cannot quietly go missing from a rapid run. Everything a rapid
        // run does not offer takes its blank value: no cover, no tags, not
        // private, no format.
        await scanAdd.mutateAsync({
          data: toScanRequest({ ...blankPending(shelf), draft }),
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
    // Once for the batch rather than once per book, and the catalogue rather
    // than everything: a rapid run leaves the scanner open, so a keyless
    // invalidate re-spent the search quota in the middle of a shelf.
    invalidate.catalogue();
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
