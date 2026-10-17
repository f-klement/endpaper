/**
 * The scan → lookup → confirm flow.
 *
 * ScanPage's whole contact with the API. The page and its components take
 * plain values and callbacks.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { classifyError } from "../../components/ErrorState";
import type { RequestFailure } from "../../components/ErrorState";
import { useInvalidate } from "../../api/invalidate";
import { ApiError } from "../../api/mutator";

import {
  findFileHolders,
  getLookupIsbnQueryKey,
  getSearchBooksQueryKey,
  listCopies,
  lookupIsbn,
  searchBooks,
  useAddBookTag,
  useAddCopy,
  useAddBookTagByName,
  useListLocations,
  useListTags,
  useLookupIsbn,
  useReportDigitalReference,
  useScanAdd,
  useSearchBooks,
  useUploadCover,
} from "../../api/generated/endpoints/books/books";
import { BookFormat } from "../../api/generated/model";
import { useGoogleBooksReady } from "../../app/hooks";
import type {
  AskedFileIn,
  BookMatch,
  BookSearchOut,
  CatalogueSource,
  DigitalReferenceIn,
  HoldersOut,
  LocationOut,
  TagOut,
} from "../../api/generated/model";
import { QUERY_FLOOR } from "../../lib/bookBounds";
import { writeOneAtATime, type BulkProgress } from "../../lib/bulkWrite";
import { referenceFor } from "../../lib/digitalReference";
import {
  libraryIndexIn,
  readCalibreLibrary,
  type CalibreBook,
} from "../../lib/calibre";
import { useTranslation } from "../../i18n";
import type { AudioTags } from "../../lib/audiobook";
import type { AudioFileNaming } from "../../lib/audiobookGroups";
import {
  FORMAT_FOR_EXTENSION,
  plainName,
  supportedExtension,
  type SupportedExtension,
} from "../../lib/fileName";
import {
  normaliseLocation,
  readLastLocation,
  rememberLastLocation,
} from "../../lib/lastLocation";
import {
  askWhoHolds,
  countLandings,
  HeldUnnamed,
  land,
  recordOnCopy,
  type HolderQuestion,
  type Landing,
} from "../../lib/fileLanding";
import { locate } from "../hooks";
import {
  FALLBACK_INTERVAL_MS,
  canBeAskedAgain,
  figuresOf,
  groupKey,
  isReading,
  isReady,
  libraryRows,
  needsALookup,
  notYetQueued,
  queueAfter,
  scannedKey,
  type Picked,
  type QueueEvent,
  type QueueFigures,
  type ScanReason,
  type ScannedEntry,
} from "./queue";
import {
  blankDraft,
  blankPending,
  draftFromFile,
  draftFromMatch,
  draftFromLookup,
  toCopyRequest,
  toScanRequest,
  type BookDraft,
  type PendingBook,
} from "./types";

/** Below this, a search is noise rather than a query. Matches the API bound. */
const MIN_QUERY_LENGTH = QUERY_FLOOR;

/**
 * How many candidates one file is offered.
 *
 * Five rather than the ten a typed search shows, because these are rendered
 * one row per file down a queue that may hold hundreds: the ranking already
 * puts the answer first, and the rest are there to be disagreed with.
 */
const FALLBACK_MATCH_LIMIT = 5;

/**
 * A pause the paced run can be cut short.
 *
 * **The resolver is handed back rather than the wait being polled.** The gap
 * between two calls is the whole of the pace, so a stop that only lands when the
 * gap ends is a button that does nothing for two seconds, which is longer than a
 * member waits before pressing it again. `stopLookingUp` ends the wait itself.
 */
function delay(
  ms: number,
  hold: { current: (() => void) | null },
): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      hold.current = null;
      resolve();
    };
    const timer = setTimeout(finish, ms);
    hold.current = finish;
  });
}

/**
 * Whether an ISBN lookup's throw is an answer: nobody knowing the ISBN.
 *
 * **A 404 is an answer and everything else is a failure to ask**, which
 * `_lookup_failure` in the books router separates deliberately: 404 is no
 * catalogue having a record, 503 is no source having been reachable. Every
 * ISBN lookup on this page reads its throw through this, because collapsing
 * the two offers the retry that buys nothing and withholds the one that does.
 */
function nobodyKnows(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

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
  /**
   * Why the lookup could not be answered, where no catalogue was reached; null
   * otherwise. A 404 is not this: it is an answer, and becomes a blank draft.
   */
  lookupError: unknown;
  /** Ask the catalogues about the same ISBN again. */
  retryLookup: () => void;
  /** Give up on the catalogues for this ISBN and fill the book in by hand. */
  enterByHand: () => void;
  /**
   * The blank draft on screen came from `enterByHand`, so no catalogue
   * answered for it. The confirm card reads this to keep from saying that
   * none of them knew the ISBN, which is what a 404's blank draft says.
   */
  enteredByHand: boolean;

  /** Prefill the confirm step from a chosen search result. */
  chooseMatch: (match: BookMatch) => void;

  /**
   * Add or remove one tag. Not a patch: a caller passing one would have to
   * compute the next list itself at every call site.
   */
  toggleTag: (tagId: number) => void;
  /**
   * Hold a typed tag name for this book. **Nothing reaches the server**: the
   * book does not exist until confirm, so the name joins `pending.tagNames`
   * and is applied with the rest, and a cancelled scan leaves the library
   * exactly as it found it.
   */
  createTag: (name: string) => void;
  /** Drop one of those names again, before the book is saved. */
  forgetTagName: (name: string) => void;

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
  // Beside the draft rather than on it: a `BookDraft` field is a `WHO_WINS`
  // row and a field `toScanRequest` has to strip, for a fact only the confirm
  // card's sentence reads. Cleared by every door that replaces the draft.
  const [enteredByHand, setEnteredByHand] = useState(false);

  const update = useCallback(
    (patch: Partial<PendingBook>) =>
      setPending((current) => ({ ...current, ...patch })),
    [],
  );

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
    } else if (lookupQuery.error && nobodyKnows(lookupQuery.error)) {
      // Neither source knew it: offer manual entry rather than a dead end.
      update({ draft: blankDraft(isbn), tagIds: [] });
    }
  }

  // **Every other throw is no catalogue having answered**, so no draft: a
  // blank form would say nobody knows the book when nobody was asked. Null
  // while a retry is in flight, which keeps the old error and must not keep
  // the offer to retry beside the spinner.
  const unanswered =
    isbn !== null &&
    pending.draft === null &&
    !lookupQuery.isFetching &&
    lookupQuery.error != null &&
    !nobodyKnows(lookupQuery.error)
      ? lookupQuery.error
      : null;

  const scanAdd = useScanAdd();
  const addAnotherCopy = useAddCopy();
  const uploadCover = useUploadCover();
  const addTag = useAddBookTag();
  const addTagByName = useAddBookTagByName();

  function reset() {
    setIsbn(null);
    setAddError(null);
    setEnteredByHand(false);
    // Everything except the shelf. It is the one field that is the same for
    // the next book far more often than not, and clearing it here would undo
    // the carry-over on every cancel.
    //
    // **The typed names go with it and nothing survives in the library**,
    // which is what this form used to leave behind. It asked the server to
    // invent a tag the moment somebody typed one, and that row was committed:
    // a cancelled scan left a tag carried by no book, absent from the
    // vocabulary listing, holding its globally unique name for good and
    // attachable by any member. Nothing here commits until confirm now.
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
      await Promise.all([
        ...pending.tagIds.map((tagId) =>
          addTag.mutateAsync({ bookId: book.id, tagId }).catch(() => undefined),
        ),
        // The names typed on this form, applied now that there is a book to
        // apply them to. One request each, the same one `BookDetail` sends,
        // and the server invents the tag if the library has none.
        ...pending.tagNames.map((name) =>
          addTagByName
            .mutateAsync({ bookId: book.id, data: { name } })
            .catch(() => undefined),
        ),
      ]);

      // The catalogue, not the whole cache. A keyless invalidate here also
      // refetched `/api/settings/features` and, worse, `/api/books/search`,
      // which is a billed Google Books call the query's own `staleTime` exists
      // to avoid re-spending. Measured: 4 requests, of which 2 were about a
      // book having been added.
      //
      // **A typed name can still be left off, and it is quieter than it was
      // rather than closed.** The attaches above are best effort by design,
      // so a network failure leaves the book saved without that tag; and the
      // by name door answers 200 with the book either way, so a name the
      // server will not hand this member is dropped there too. What went is
      // the 404 the old create then attach pair produced when the typed name
      // collided with a tag the member cannot see: the create handed back
      // that row and the attach by id then refused it.
      // `backend/tests/routers/test_books_tags.py::TestANameTypedAgainstAHiddenTagIsNotAttached`
      // holds why the refusal is silent and what it does not close. The
      // member lands on the saved book, where its tags are what they are.
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
    setEnteredByHand(false);
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
      setEnteredByHand(false);
      setIsbn(nextIsbn);
    },
    isLookingUp: isbn !== null && pending.draft === null && unanswered === null,
    lookupError: unanswered,
    // A refetch rather than `lookup` again: the ISBN is the same, so the key
    // does not change and the failed answer would simply be read back.
    retryLookup: () => void lookupQuery.refetch(),
    enterByHand: () => {
      if (isbn === null) return;
      setEnteredByHand(true);
      update({ draft: blankDraft(isbn), tagIds: [] });
    },
    enteredByHand,

    createTag: (name) =>
      setPending((current) =>
        // Folded rather than appended, so pressing the button twice does not
        // send the same name twice. The comparison is the client's own and is
        // deliberately not the server's fold: what it prevents is a duplicate
        // chip, and what decides which names are one tag is `tags.folded`, on
        // the server, where the whole vocabulary is visible.
        current.tagNames.includes(name)
          ? current
          : { ...current, tagNames: [...current.tagNames, name] },
      ),
    forgetTagName: (name) =>
      setPending((current) => ({
        ...current,
        tagNames: current.tagNames.filter((held) => held !== name),
      })),
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

  const isConfigured = useGoogleBooksReady();

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
    isConfigured,
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

/**
 * The reason a refused request leaves on the row it was refused for.
 *
 * **A mapping and not a second classification**, which is the whole of why
 * `classifyError` is where it is: the branches that tell a transport failure
 * from a server's own words are one copy, and this turns that answer into a
 * name the queue can keep. Written out here, the two copies would diverge on
 * the first branch added to either, with nothing red.
 *
 * **The split is why this is not `errorText` itself.** That answers a sentence
 * now, in the locale now; a queued row is drawn later and possibly in the other
 * language, so the half this page has words for becomes a name and the half it
 * does not keeps the words.
 *
 * Nothing at all where the throw carried no message, which is what
 * `errorText(error, "", t)` answered `""` for: a row with an empty reason and a
 * row with none already rendered alike.
 */
function reasonForError(error: unknown): ScanReason | undefined {
  const failure = classifyError(error);
  if (failure === undefined) return undefined;
  return reasonFor(failure.kind, failure);
}

/**
 * What each kind of failed request becomes on a row.
 *
 * **A total `Record` keyed on the union rather than a ternary**, which is
 * `OFFERED_AGAIN`'s rule one union over: a third `RequestFailure` does not
 * compile until it appears here. The ternary this replaced refused only the
 * third kind that carries no words of its own, because the else branch reads
 * `message`; a third kind that happened to carry one would have been reported
 * to the member as the server's own sentence, which is the one thing on this
 * page nothing can translate and nothing can take back.
 *
 * Each arm is handed the failure its own key stands for, so the arm that has
 * words reads them and the arm that has none cannot.
 */
const REASON_FOR_FAILURE: {
  [Kind in RequestFailure["kind"]]: (
    failure: Extract<RequestFailure, { kind: Kind }>,
  ) => ScanReason;
} = {
  unreachable: () => ({ kind: "unreachable" }),
  said: (failure) => ({ kind: "server-said", message: failure.message }),
};

/**
 * The arm for one failure, applied to that failure.
 *
 * **Separate from `reasonForError` because the key has to be generic**, which
 * is the whole reason this function exists and is what stops somebody folding
 * it back in. Indexing the table with a union typed `failure.kind` yields a
 * union of arms, and calling that asks for the intersection of their
 * parameters, which is `never`: measured, `TS2345` on the call. Written with
 * the key as a type parameter, the table and the argument stay correlated and
 * no cast is needed anywhere.
 */
function reasonFor<Kind extends RequestFailure["kind"]>(
  kind: Kind,
  failure: Extract<RequestFailure, { kind: Kind }>,
): ScanReason {
  return REASON_FOR_FAILURE[kind](failure);
}

/**
 * Whether a file of this extension is one part of an audiobook.
 *
 * **The format map decides which route a file takes**, so an extension filed as
 * an audiobook is one the grouping rule owns and one filed as an ebook is one
 * the ordinary per file path owns.
 *
 * **`lib/audiobook.ts` holds a second list, `AUDIO_EXTENSIONS`, and the two are
 * asserted equal rather than said to agree.** That module has to answer a
 * question this one cannot, which is whether one file of a kind is a whole book
 * or one track of one, and the answer is a property of the container rather
 * than of the walk. `tests/lib/fileName.test.ts` compares the two sets in both
 * directions, because an extension in this map and not in that one would be
 * routed here and read by nothing.
 */
function isAudio(extension: SupportedExtension): boolean {
  return FORMAT_FOR_EXTENSION[extension] === BookFormat.audiobook;
}

/**
 * What a library folder's pick could not do the way it meant to, said beside
 * the picker as `skipped` is.
 *
 * `index-unread`: the folder held a Calibre index this could not read, so its
 * files were read one by one and a book with several formats may be a row
 * per file. `unindexed`: book files the index names for no book, left out.
 */
export type LibraryNotice =
  | { readonly kind: "index-unread" }
  | { readonly kind: "unindexed"; readonly count: number };

/** The holder lookup, in the shape `lib/fileLanding.askWhoHolds` takes. */
function whoHolds(files: AskedFileIn[]): Promise<HoldersOut[]> {
  return findFileHolders({ files });
}

/** Every file a row says where it is, its own reference first. */
function filesOf(entry: ScannedEntry): DigitalReferenceIn[] {
  return entry.reference === undefined
    ? []
    : [entry.reference, ...(entry.moreReferences ?? [])];
}

/**
 * The queue key for a picked file.
 *
 * Name, size and modification time rather than the name alone: two different
 * books can be `book.epub` in two folders, and picking the same file twice is
 * the case that should be ignored.
 */
function pickedKey(file: File): string {
  return `file:${file.name}:${file.size}:${file.lastModified}`;
}

/**
 * The folders above a picked file, outermost first.
 *
 * **What `webkitRelativePath` is, and what its first segment means, is stated
 * once in `lib/digitalReference.ts`** and not again here: these are two
 * decompositions of one string, this one dropping the file's own name and that
 * one splitting the picked root off the front, and the fact they share is the
 * one that goes stale twice if it is written twice. A file picked one at a time
 * carries no path at all, which is the ordinary case and reads as no folders.
 *
 * Outermost first is what `readName` wants: in a library on disk the author is
 * the folder **above** the book, and the folder immediately over a file is
 * usually named for the book itself.
 */
function foldersOf(file: File): string[] {
  return file.webkitRelativePath
    ? file.webkitRelativePath.split("/").slice(0, -1).filter(Boolean)
    : [];
}

/**
 * The books a library's index holds, or `null` for an index this cannot
 * read, whatever the reason: `readLibrary` treats every one alike.
 */
async function booksIn(index: File): Promise<readonly CalibreBook[] | null> {
  try {
    const { openSqliteFile } = await import("../../lib/sqlite");
    const opened = await openSqliteFile(index);
    if (!opened.ok) return null;
    try {
      const reading = readCalibreLibrary(opened.database);
      return reading.ok ? reading.books : null;
    } finally {
      opened.database.close();
    }
  } catch {
    return null;
  }
}

/**
 * A library's books checked against the folder beside them, with the pairing
 * of books to files, or `null` where either step failed.
 *
 * **The folder reader is a chunk of its own, and a chunk can fail to load**
 * (a deploy since the page was opened, a dropped connection). Caught here
 * with the index's own failures, so it leaves the folder read file by file:
 * uncaught, the library's pending row stood over nothing for ever.
 */
async function readIndexed(index: File, files: readonly File[]) {
  const books = await booksIn(index);
  if (books === null) return null;
  try {
    const { crossCheckFolder, filesOfEachBook } =
      await import("../../lib/calibreFolder");
    const { books: checked } = await crossCheckFolder(books, files);
    return { checked, filesOfEachBook };
  } catch {
    return null;
  }
}

/**
 * Thrown by one row of `addAll` when `land` answers `other-format`, so the
 * failure mapping can offer the copy rather than state the 409.
 *
 * **A thrown value rather than a flag beside the row**, because the shared
 * loop in `lib/bulkWrite.ts` records a row as failed by its throw and by
 * nothing else, and this row is not in the catalogue as itself.
 */
class HeldInAnotherFormat extends Error {
  constructor(readonly holderId: number) {
    super("Held in another format");
    this.name = "HeldInAnotherFormat";
  }
}

/**
 * Whether this row's ISBN is good enough to write a location onto somebody
 * else's book.
 *
 * **A duplicate 409 names a book this member did not add, and the location
 * follows the ISBN.** So the question is not whether the ISBN is well formed,
 * which the parser already answered, but where it came from.
 *
 * **A name is the one provenance that invents one.** `fileName.isbnIn` takes a
 * ten digit candidate only as a whole token, and its own docstring carries the
 * reason: a random ten digit run passes modulus 11 about one time in eleven. A
 * false positive there used to cost a failed row and nothing else. Following it
 * would write a member's own folder names onto a stranger's book, spend one of
 * that book's sixteen references, and leave the row on screen saying failed
 * with nothing saying a write had happened.
 *
 * **The first draft read `state === "found"` and did not refuse that case at
 * all.** `lookUpTheName` promotes a row to `found` on a successful ISBN lookup,
 * and every row standing under its own name reaches that call, so the
 * one provenance this refuses was the one being promoted past it. A state that
 * two paths deliberately collapse cannot answer a question about which path it
 * came from. `ScannedEntry.isbnFromTheName` carries it from the site that
 * knows.
 *
 * **What the refusal costs, and it is larger than the first draft of this
 * paragraph said.** A genuine ISBN in a file name is common, and a re import of
 * such a file loses its location: the book is already in the catalogue, the
 * create 409s, and nothing is recorded.
 *
 * **There is no press that gets it back**, which is the half worth stating,
 * because this is the paragraph somebody will read to judge whether the gate is
 * too strict. A flagged row has a non empty `isbn`, so `lookUpTheName` returns
 * from the ISBN branch before the search, and the search branch is the only
 * producer of `choosing`. No records are ever offered for such a row, so there
 * is no record to take, and `OFFERED_AGAIN` is false for both answers it can
 * end on. The location is not recoverable inside a rapid run. Both critic seats
 * reached that independently, 2026-09-10.
 */
function theIsbnWasRead(entry: ScannedEntry): boolean {
  return entry.isbnFromTheName !== true;
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
  /**
   * Read picked files and queue what they say.
   *
   * The same queue as the scanner fills, deliberately: a folder is a third way
   * of choosing *which* book and it answers the same question, so it gets the
   * same review and the same one commit at the end rather than a second bulk
   * path beside this one.
   */
  pickFiles: (files: readonly File[]) => void;
  /** True while any picked file is still being read. */
  isReading: boolean;
  /**
   * How many picked files the walk passed over, because Endpaper reads no
   * format of theirs.
   *
   * **Counted rather than ignored**, which is the whole of the interface here: a
   * member who points at a folder of CBR or DJVU files and sees nothing appear
   * deserves to know why. Deduplicated by the queue's own key, so pointing at
   * the same folder twice does not count it twice.
   */
  skipped: number;
  /** What the last pick said about a Calibre library in it, or `null`. */
  libraryNotice: LibraryNotice | null;
  /** What the queue adds up to, for every control that quotes a figure. */
  figures: QueueFigures;
  /**
   * Ask the catalogue about every file that has only its name, about every
   * ISBN a file stated, and about every barcode no catalogue answered.
   *
   * **Offered, never automatic**, and it is one press for the queue as it stood
   * when it was pressed. Two reasons, and the second is the one that decides it:
   * several hundred files is several hundred fan outs, which is not something a
   * page may spend somebody's rate limit on because they picked a folder; and no
   * name a member did not choose to look up ever leaves the browser.
   */
  lookUpTheNames: () => void;
  /**
   * Ask the catalogues again about every name kept in bulk.
   *
   * The same paced run as `lookUpTheNames` over a different set, rather than a
   * second mechanism: one pace, one stop, and one call per file whichever press
   * started it.
   */
  lookUpTheKeptNames: () => void;
  /** Stop the paced run after the call in flight. */
  stopLookingUp: () => void;
  isLookingUp: boolean;
  /**
   * File one audiobook candidate's parts as a book each.
   *
   * **The one way back out of the grouping rule**, and it is one way rather
   * than two on purpose: the rule exists to refuse thirty rows from one
   * audiobook, so the mistake it can make is putting together files that are
   * not one book, and this undoes exactly that. There is no merge, because
   * merging would be a member asserting something their files deny.
   *
   * Does nothing for anything that is not a group of several.
   */
  splitApart: (key: string) => void;
  /**
   * Take one subject off one queued book before anything is written.
   *
   * **The only control in this app that removes a subject, and this is the
   * last moment it is offered.** `BookDetailsUpdate` takes `categories`, and an
   * empty list clears them, but no page sends that field: once `addAll` has
   * run, the remedy is a request to the API by hand. A file states a subject a
   * stranger wrote, a folder pick is several hundred files behind one press,
   * and this is the row where that is still one press to undo.
   *
   * **Here rather than on the confirm card, which was where the design round
   * put it and is a surface a file never reaches**: measured while building
   * this, `pickFiles` settles every picked file into this queue and
   * `LookupResult` is fed only by the barcode, the manual ISBN and the search
   * box, none of which carries a subject. A block on that card would have
   * been consent nobody was ever shown.
   *
   * Does nothing for a row with no draft or no such subject.
   */
  dropSubject: (key: string, subject: string) => void;
  /** Take one of the records the catalogue offered for a file. */
  chooseFor: (key: string, match: BookMatch) => void;
  /** Reject all of them and keep what the name said. */
  keepTheName: (key: string) => void;
  /** Take the record held on a `stated` row whose title differed. */
  takeTheRecord: (key: string) => void;
  /** Refuse that record and keep what the file described. */
  keepTheFile: (key: string) => void;
  /**
   * Clear every row still being decided, keeping the names **for now**.
   *
   * **Not the same state as keeping one name, and that is the whole control.**
   * Keeping one name is a member's answer about that book and stays answered.
   * This is a member clearing a queue of three hundred, so every row it touches
   * is offered a lookup again and the records it takes off the screen can be
   * asked for a second time. Owner's decision, 2026-09-10, taken over a
   * confirmation naming the count, which announces a discard rather than
   * undoing one.
   *
   * **The set is `isBeingDecided`, which is the set `addAll` excludes.** A
   * second predicate spelled the same way would let the control clear rows the
   * batch would have added, or leave rows the batch still refuses.
   */
  keepEveryNameForNow: () => void;
  remove: (key: string) => void;
  clear: () => void;

  addAll: () => void;
  isAdding: boolean;
  /**
   * Add a row held in another format as its own copy of the book its ISBN
   * already belongs to. Does nothing for a row not offering that.
   */
  addAsCopy: (key: string) => void;
  isAddingCopy: boolean;
  /**
   * Stop the batch after the book in flight.
   *
   * **The same stop the camera and the paced lookup each already had**, and the
   * one this page shipped without: a three hundred row queue is up to six
   * hundred sequential requests, because a row carrying a location is a book
   * and then a sighting. Read between books rather than inside one, so the book
   * being written is finished and recorded rather than abandoned half made.
   *
   * Every row the run did not reach stays in the queue exactly as it was, which
   * is what a member pressing this is asking for.
   */
  stopAdding: () => void;
  /**
   * How far the batch has got, or `null` when none is running.
   *
   * A stop with no figure beside it is a button a member presses blind. The
   * import cards on the settings page have said `{done} of {total}` since they
   * had a stop, and this is the same value from the same loop.
   */
  addProgress: BulkProgress | null;
  /**
   * What the batch did, once it has run.
   *
   * `unreferenced` is books that were added and whose location was not
   * recorded, which is a different sentence from `failed`: the book is in the
   * catalogue and only the answer to "where is the file" was lost. Zero for a
   * pick that offered no location at all, so the screen says nothing about a
   * batch of barcodes.
   *
   * **A row that never had a location to send is not counted here**, and the
   * two are different sentences too: a refusal is worth re picking the folder
   * for, since the sighting is idempotent on the pair and a second pick costs
   * nothing, and an audiobook has nothing a second pick would change.
   * `file.explain` scopes what it promises to a book that is one file for that
   * reason.
   *
   * `already` is rows whose file a Book the member can see already held, so
   * nothing was added for them and their sighting was refreshed there. Not in
   * `added`, which would otherwise claim books the batch did not make.
   *
   * `atCeiling` is such rows where that Book refused a file for holding as
   * many as a Book may. They leave the queue too (owner's ruling, 2026-10-17):
   * the book is in the library, and a retry is refused the same way.
   *
   * `filesLeft` is files of the rows added or already held, or of a copy
   * press, that another Book
   * the member can see already holds the location of, so they were left
   * there and not recorded on the row's Book.
   *
   * `stopped` says the run ended because the member ended it, so a count far
   * short of the queue is not read as damage. The rows it never reached are
   * still in the queue, which is the other half of the same sentence.
   */
  result: {
    added: number;
    failed: number;
    unreferenced: number;
    already: number;
    atCeiling: number;
    filesLeft: number;
    stopped: boolean;
  } | null;
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
  const [isLookingUp, setIsLookingUp] = useState(false);
  // **What the last pick passed over, rather than a running total.** A total
  // has no way down: the notice sits beside the picker rather than the queue,
  // precisely so it can be shown when nothing was queued at all, and a member
  // who picks a folder of comics and nothing else would carry the number for the
  // rest of the session. A count of the last pick is also the one a member can
  // act on, since it is the pick they just made.
  const [skipped, setSkipped] = useState(0);
  // What the last pick said about a Calibre library in it, for the same
  // reason and with the same lifetime as `skipped`.
  const [libraryNotice, setLibraryNotice] = useState<LibraryNotice | null>(
    null,
  );
  // A ref rather than state: the paced run reads it between calls, and a state
  // read inside a running loop is the value it started with.
  const stopRequested = useRef(false);
  // The queue as last rendered, for the paced run, which otherwise reads the
  // render it started in. Written after each commit, never during a render.
  const liveEntries = useRef<ScannedEntry[]>([]);
  useEffect(() => {
    liveEntries.current = entries;
  });
  // The batch's own stop, for the same reason and not the same flag: the paced
  // lookup and the write are two runs with two buttons, and one flag would let
  // stopping either halt the other.
  const stopAddingRequested = useRef(false);
  const [addProgress, setAddProgress] = useState<BulkProgress | null>(null);
  // How to end the wait between two calls early. Null whenever the run is not
  // waiting, which is every moment a stop has nothing to interrupt.
  const endTheWait = useRef<(() => void) | null>(null);
  const [location, setLocation] = useState(readLastLocation);
  const [result, setResult] = useState<{
    added: number;
    failed: number;
    unreferenced: number;
    already: number;
    atCeiling: number;
    filesLeft: number;
    stopped: boolean;
  } | null>(null);

  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const scanAdd = useScanAdd();
  const reportReference = useReportDigitalReference();
  const addAnotherCopy = useAddCopy();
  // **The whole of `addAsCopy`, not the copy request's own pending flag.** That
  // flag drops when the copy exists, and a batch started during the reference
  // request after it would re-walk the row and overwrite the copy's verdict.
  const [isAddingCopy, setIsAddingCopy] = useState(false);
  const locations = useKnownLocations();
  // **The locale, and nothing else this hook says to a member.** Every reason a
  // row carries is a name now, and the last `t` went with them; this is for the
  // paced lookup, which breaks ties towards the reader's own printing exactly
  // as the search box does.
  const { locale } = useTranslation();

  /**
   * What happened, applied to the queue as it stands when React gets to it
   * rather than as this render saw it: a subject dropped while a lookup was in
   * flight stays dropped.
   */
  function apply(event: QueueEvent) {
    setEntries((current) => queueAfter(current, event));
  }

  function capture(isbn: string) {
    setEntries((current) => {
      const queued = queueAfter(current, { kind: "captured", isbn });
      // A repeat comes back as the same queue, and is not looked up again.
      if (queued !== current) void lookUp(isbn);
      return queued;
    });
  }

  async function lookUp(isbn: string) {
    const key = scannedKey(isbn);
    try {
      const lookup = await queryClient.fetchQuery({
        queryKey: getLookupIsbnQueryKey({ isbn }),
        queryFn: () => lookupIsbn({ isbn }),
        staleTime: 60_000,
      });
      apply({ kind: "isbn-answered", key, lookup });
    } catch (error) {
      // Kept in the queue either way rather than dropped, so a book on the
      // shelf does not silently vanish between the shelf and the catalogue.
      apply({
        kind: "not-answered",
        key,
        asked: "looking-up",
        unknown: nobodyKnows(error),
      });
    }
  }

  /**
   * Read picked files, one entry each.
   *
   * **The reader is imported inside this call rather than at the top of the
   * module**, so a session that never picks a file never downloads a zip walk
   * and an XML reader. It is resolved once for the batch: the module graph is
   * cached after the first await, and asking per file would serialise every
   * read behind something already in memory.
   *
   * **A file the walk does not read is counted, never dropped in silence.** The
   * formats epic settled which extensions are in and which are out, so a folder
   * of CBR or DJVU produces a count and an explanation rather than an empty
   * queue that reads as a broken picker.
   *
   * **A file that cannot be read is no longer the end of it.** Its name is still
   * a signal, so it becomes a candidate carrying what the name said, with a note
   * of what the file itself could not say. Only a name that reduces to nothing
   * is a failure now.
   *
   * **Audio takes a different route and the docstring above says why it must.**
   * One file is one book for every format here except an audiobook, which is
   * usually a folder of chapter files, so its rows cannot be made until every
   * file in the pick has been read and grouped. `readAudio` is that route.
   *
   * The queue is asked what it already holds (`notYetQueued`) inside the
   * updater, and the reads start from there, which is the shape `capture` uses
   * and for the same reason: the
   * queue is the only record of what has been picked, so asking anything else
   * would be a second one to keep in step. The skipped count is taken **before**
   * it, because an updater that counts is an updater run twice under a strict
   * render counting twice.
   */
  function pickFiles(files: readonly File[]) {
    // **A Calibre library is read through its index, not file by file**, the
    // way the Settings import reads it: one row a book, with every format
    // file on it, rather than a row per file the index already describes.
    const index = libraryIndexIn(files);
    if (index !== undefined) {
      pickLibrary(files, index);
      return;
    }
    walkFiles(files);
  }

  /** The ordinary walk: one row per file, or per audiobook. */
  function walkFiles(files: readonly File[]) {
    const walked = files.map((file) => ({
      file,
      extension: supportedExtension(file.name),
    }));
    setSkipped(walked.filter((walk) => walk.extension === null).length);
    setLibraryNotice(null);

    const supported = walked.filter(
      (walk): walk is { file: File; extension: SupportedExtension } =>
        walk.extension !== null,
    );

    setEntries((current) => {
      const unqueued = notYetQueued(current, supported, (walk) =>
        pickedKey(walk.file),
      );
      // **The audio half gets one row for the whole pick, not one each.** Which
      // files are one book is decided by what they say, so nothing can be
      // grouped until every one of them has been read. The row claims them
      // meanwhile, which is what keeps a second pick of the same folder from
      // queueing them again, and `readAudio` replaces it with the books.
      const audio = unqueued.filter((walk) => isAudio(walk.extension));
      const fresh = unqueued.filter((walk) => !isAudio(walk.extension));
      const pending = audio.length > 0 ? pendingAudio(audio) : null;
      if (pending) void readAudio(audio, pending.key);
      if (fresh.length > 0) void readFiles(fresh.map((walk) => walk.file));
      return queueAfter(current, {
        kind: "picked",
        rows: [
          ...(pending ? [pending] : []),
          ...fresh.map((walk) => ({
            key: pickedKey(walk.file),
            // Taken while the `File` is still in hand. After the read the
            // queue holds a key and a label and could not derive this if it
            // wanted to.
            reference: referenceFor(walk.file) ?? undefined,
            // Cleaned for the reason every derived value is: a name is
            // somebody else's text, and this one is printed beside a title
            // that was.
            label: plainName(walk.file.name),
            // The extension answers this, and it is the same kind of evidence
            // a zip container is rather than the guess `format` is nullable to
            // refuse.
            format: FORMAT_FOR_EXTENSION[walk.extension],
          })),
        ],
      });
    });
  }

  /**
   * Queue a Calibre library folder: one row while its index is read, then a
   * row for each of its books.
   *
   * Keyed by the folder's name, so picking the same library again while it
   * is read queues nothing, and its books by their Calibre id under it, so a
   * second pick afterwards queues only books not already in the queue.
   */
  function pickLibrary(files: readonly File[], index: File) {
    setSkipped(0);
    setLibraryNotice(null);
    const root = index.webkitRelativePath.split("/")[0]!;
    const key = `calibre:${root}`;
    setEntries((current) => {
      const queued = queueAfter(current, {
        kind: "picked",
        rows: [{ key, label: plainName(root), format: "" }],
      });
      // A library still being read comes back as the same queue, and is not
      // read again.
      if (queued !== current) void readLibrary(files, index, key);
      return queued;
    });
  }

  /**
   * Read a library folder through its index and queue its books.
   *
   * **Read only, by construction**: the index is a `File` the browser read
   * into memory, and `lib/sqlite.ts` refuses a copy torn structurally, which
   * a live library caught mid write can be; a copy whose pages agree but
   * whose rows are mid transaction is read as it stands. **An index this
   * cannot read leaves an ordinary folder**, so its files are read one by one
   * as any folder's are, and `libraryNotice` says so: one row per file is
   * what this door exists to replace, so the member is told why it is back.
   *
   * **A book file the index names for no book is left out and counted**, the
   * walk's own rule for what it passes over.
   *
   * Each book is `draftFromCalibre`'s, checked against the `metadata.opf`
   * beside it, and carries a reference for each of its files the folder holds,
   * with the fingerprint read now, while the files are in hand. Then the
   * holder lookup, once, as `readFiles` asks it.
   */
  async function readLibrary(
    files: readonly File[],
    index: File,
    pendingKey: string,
  ) {
    const read = await readIndexed(index, files);
    if (read === null) {
      apply({ kind: "removed", key: pendingKey });
      walkFiles(files.filter((file) => file !== index));
      setLibraryNotice({ kind: "index-unread" });
      return;
    }

    const { checked, filesOfEachBook } = read;
    const paired = filesOfEachBook(checked, files);
    const indexed = new Set([...paired.values()].flat());
    // Not under a folder whose name starts with a dot at the library's root:
    // Calibre keeps deleted books' files in `.caltrash`, and inviting the
    // member to add them back would be the wrong sentence.
    const unindexed = files.filter(
      (file) =>
        supportedExtension(file.name) !== null &&
        !indexed.has(file) &&
        !file.webkitRelativePath.split("/")[1]?.startsWith("."),
    ).length;
    if (unindexed > 0)
      setLibraryNotice({ kind: "unindexed", count: unindexed });
    const located = new Map(
      await Promise.all(
        [...paired].map(
          async ([id, held]) =>
            [
              id,
              (await Promise.all(held.map(locate))).filter(
                (one) => one !== undefined,
              ),
            ] as const,
        ),
      ),
    );

    const rows = libraryRows(
      pendingKey,
      checked.map((book) => ({ book, files: located.get(book.id) ?? [] })),
    );
    // Every file of each row that has one, as `readFiles` asks for its own.
    const questions = rows.flatMap((row) =>
      row.reference === undefined
        ? []
        : [{ key: row.key, references: filesOf(row), format: row.format }],
    );
    apply({ kind: "library-read", pendingKey, rows });
    await recordHolders(questions);
  }

  /**
   * The one row a pick of audio files stands as while they are being read.
   *
   * **A row rather than a flag beside the queue.** A pick of forty chapter
   * files has nothing to show until it has been grouped, and a picker
   * that shows nothing reads as one that is broken. It also carries the claim
   * on those files, so nothing else has to remember them.
   *
   * Named after the folder they came from where there is one, which is what a
   * person named after the book, and after the first file where there is not.
   */
  function pendingAudio(
    picked: readonly { file: File; extension: SupportedExtension }[],
  ): Picked {
    const first = picked[0]!.file;
    const folders = foldersOf(first);
    const keys = picked.map((walk) => pickedKey(walk.file));
    return {
      key: groupKey(keys),
      label: plainName(folders.at(-1) ?? first.name),
      format: BookFormat.audiobook,
      claims: keys,
    };
  }

  /** Mark each asked row with the Book holding its file, or with none. */
  async function recordHolders(questions: readonly HolderQuestion[]) {
    if (questions.length === 0) return;
    apply({
      kind: "holders-answered",
      held: await askWhoHolds(questions, whoHolds),
    });
  }

  async function readFiles(files: readonly File[]) {
    const { readerFor } = await import("../../lib/fileReaders");
    const questions: HolderQuestion[] = [];
    // Every fingerprint first, together: twelve small slices a file, so a
    // pick of hundreds holds a few megabytes at most, and the read loop below
    // stays the one sequential step.
    const located = await Promise.all(files.map(locate));
    for (const [position, file] of files.entries()) {
      const key = pickedKey(file);
      const reference = located[position];
      if (reference) {
        const extension = supportedExtension(file.name);
        questions.push({
          key,
          references: [reference],
          format: extension ? FORMAT_FOR_EXTENSION[extension] : "",
        });
      }
      let said: BookDraft | undefined;
      let note: ScanReason | undefined;
      try {
        // **Which reader opens this is `lib/fileReaders.ts`'s question, not
        // this loop's.** An extension with no reader falls through to its name,
        // which is this path's whole point: for a PDF an unusable metadata
        // block is the common case rather than the exception.
        const reader = await readerFor(file.name);
        const reading = reader ? await reader(file) : null;
        if (reading && !reading.ok) {
          note = { kind: "file", failure: reading.failure };
        } else if (reading) {
          said = draftFromFile(reading.metadata);
        }
      } catch {
        // A bug in the reader rather than anything the file did. Still one
        // entry, and the name is still a signal.
        note = { kind: "unreadable" };
      }
      apply({
        kind: "file-read",
        key,
        naming: { name: file.name, folders: foldersOf(file) },
        reference,
        said,
        note,
      });
    }
    // **Once for the pick, after every file is read**, so a re-picked folder
    // says which of its rows are already in the library before anybody
    // presses add, at one request per `FILES_PER_LOOKUP` files.
    await recordHolders(questions);
  }

  /**
   * Read the picked audio files, then queue the **books** they are.
   *
   * **Every file first, rows afterwards**, which is the inversion this format
   * brings: which files are one book is decided by what they say, so nothing
   * can be shown until the whole pick has been read. That is affordable only
   * because the reader seeks to the tags rather than reading the file:
   * `lib/audiobook.ts` carries the measurement.
   *
   * **One file's failure is a note on the candidate, never the end of it.** A
   * folder of untagged chapter MP3s is still one book, named after the folder,
   * which is the ordinary case for anything a person ripped themselves.
   */
  async function readAudio(
    picked: readonly { file: File; extension: SupportedExtension }[],
    pendingKey: string,
  ) {
    const [audiobook, groups] = await Promise.all([
      import("../../lib/audiobook"),
      import("../../lib/audiobookGroups"),
    ]);

    const read: AudioFileNaming[] = [];
    // **Beside the namings rather than in them**, because what a member is told
    // is not a fact about the grouping: see `ScannedEntry.fileReasons`, which is
    // where these end up so a split can still say what each file said.
    const reasons = new Map<string, ScanReason>();
    for (const { file, extension } of picked) {
      // **Nothing is dropped here, and the loop used to drop it.** A file the
      // reader has no arm for is still a file the member picked and still has a
      // name, and skipping it took it out of the pick with no row and no count:
      // a pick made entirely of them replaced its own reading row with nothing.
      const audio = audiobook.isAudioExtension(extension) ? extension : null;
      let tags: AudioTags | null = null;
      // `file.unsupported`, not an audio reason: a file routed here that this
      // has no arm for is not an audio file that said nothing. Spelled as the
      // `FileFailure` it is, which is the name the picked file path gives it.
      let note: ScanReason | undefined = audio
        ? undefined
        : { kind: "file", failure: "unsupported" };
      if (audio) {
        try {
          const reading = await audiobook.readAudioTags(file, audio);
          if (reading.ok) tags = reading.tags;
          else note = { kind: "audio", failure: reading.failure };
        } catch {
          // A bug in the reader rather than anything the file did. The file is
          // still one part of a book and its name still says something.
          note = { kind: "unreadable" };
        }
      }
      const key = pickedKey(file);
      if (note) reasons.set(key, note);
      read.push({
        key,
        name: file.name,
        folders: foldersOf(file),
        tags,
        // **`true` for a file the reader has no arm for**, so it is a
        // candidate on its own rather than a member of whatever untagged book
        // shares its folder: `entryForGroup` shows a note only for a group of
        // one, so the other way round computes a reason nobody sees and adds a
        // file to a book's count that is not part of the book. Unreachable
        // while `tests/lib/fileName.test.ts` holds the two extension sets
        // equal, which is what makes this a defence rather than a path.
        whole: audio === null || audiobook.AUDIO_EXTENSIONS[audio] === "book",
      });
    }

    apply({
      kind: "audio-grouped",
      pendingKey,
      groups: groups.groupAudiobooks(read),
      reasons,
    });
  }

  /**
   * File one candidate's parts as a book each.
   *
   * **The group is replaced in place rather than removed and re-picked**, so
   * the member does not lose the shelf, the queue position or anything the
   * catalogue has already answered for the rows around it.
   *
   * Nothing happens for a row that is not a group of several, which is what a
   * button pressed twice does.
   */
  async function splitTheGroup(key: string) {
    const groups = await import("../../lib/audiobookGroups");
    apply({ kind: "split", key, apart: groups.splitApart });
  }

  /**
   * Ask the catalogue about one file, and never twice about the same one.
   *
   * **One call per file, which is what makes the pace's arithmetic true.** A
   * name carrying an ISBN, and a file stating one, take the route a barcode
   * takes, because an ISBN is an identifier rather than a guess; anything else
   * is a title search. The record found is filled from the row's own draft
   * where it left a field blank, `types.enrichedDraft`. Neither
   * falls back to the other on a miss, since a second call per file would double
   * a budget that was priced on one.
   *
   * **A miss leaves a book rather than an error.** The entry keeps the draft its
   * name produced and says the catalogues did not have it, which for a title
   * that exists only as a file is the ordinary outcome: six of the eight sources
   * a title search fans out to refuse a record that says it is electronic.
   */
  async function lookUpTheName(entry: ScannedEntry) {
    try {
      if (entry.isbn) {
        const lookup = await queryClient.fetchQuery({
          queryKey: getLookupIsbnQueryKey({ isbn: entry.isbn }),
          queryFn: () => lookupIsbn({ isbn: entry.isbn }),
          staleTime: 60_000,
        });
        apply({ kind: "isbn-answered", key: entry.key, lookup });
        return;
      }
      if (!entry.query) return;
      const params = {
        q: entry.query,
        limit: FALLBACK_MATCH_LIMIT,
        lang: locale,
      };
      const answer = await queryClient.fetchQuery({
        queryKey: getSearchBooksQueryKey(params),
        queryFn: () => searchBooks(params),
        // The same five minutes the search box holds, and for the same reason:
        // a member who stops a run and starts it again should not re-spend a
        // quota to be told what it was just told.
        staleTime: 5 * 60_000,
      });
      apply({
        kind: "search-answered",
        key: entry.key,
        matches: answer.matches,
      });
    } catch (error) {
      // `entry` is the row as the run found it, before it was asked, which
      // is the state where it goes back to.
      apply({
        kind: "not-answered",
        key: entry.key,
        asked: entry.state,
        unknown: nobodyKnows(error),
      });
    }
  }

  /**
   * The paced run, over whichever set the press that started it named.
   *
   * **Sequential, with a floor of `FALLBACK_INTERVAL_MS` between starts.** The
   * floor is measured from the start of the previous call rather than its end,
   * so a slow catalogue spends the wait instead of adding to it, and the last
   * file does not wait for a file that is not there.
   *
   * **Over the queue as it stood when the press happened**, which is what makes
   * the figure on the button true. A file picked during a run joins the next
   * one.
   *
   * **One loop for both presses, taking the predicate rather than the list.**
   * The pace is priced against a limiter the whole page shares, so a second
   * mechanism beside this one would be a second run able to start while this is
   * going: `isLookingUp` is what refuses that, and it refuses it once here
   * rather than once per caller. The predicate is passed rather than the
   * filtered array so the run reads the entries it starts from, which is what
   * makes the count on the button and the list the loop walks the same set.
   */
  async function runTheLookups(over: (entry: ScannedEntry) => boolean) {
    // **The rendered state, and a ref was tried here and taken back out.** A
    // press is a discrete event, which React flushes before it delivers the
    // next, so a second press cannot see this as it was, and there are two
    // presses: one per set. Two calls inside one tick would both pass, and a
    // ref refused the second.
    //
    // **What that would now cost is no longer nothing.** While there was one
    // entry point the two loops walked the same list and asked the same query
    // keys, so React Query answered the second out of the first's flight. The
    // two sets here are disjoint by construction, so two runs would ask
    // different rows: 30 starts a minute each is the whole of `METADATA_LIMIT`,
    // which is the one outcome `FALLBACK_STARTS_PER_MINUTE` is priced to
    // refuse. What holds is that nothing calls both in one tick. **Anything
    // that ever does needs the ref back**, and it is this paragraph rather than
    // a test that says so, because a guard nothing can watch go wrong is a
    // guard nothing can watch go missing.
    if (isLookingUp) return;
    const walking = entries.filter(over);
    if (walking.length === 0) return;

    stopRequested.current = false;
    setIsLookingUp(true);
    try {
      for (const [index, entry] of walking.entries()) {
        if (stopRequested.current) break;
        // **A row removed since the press is not asked about.** The run walks
        // the queue as it stood, so without this a removed row, or a whole
        // discarded queue, still spends one metered lookup each.
        if (!liveEntries.current.some((one) => one.key === entry.key)) continue;
        apply({ kind: "asked", key: entry.key });
        const startedAt = Date.now();
        await lookUpTheName(entry);
        if (index === walking.length - 1) break;
        const remaining = FALLBACK_INTERVAL_MS - (Date.now() - startedAt);
        if (remaining > 0) await delay(remaining, endTheWait);
      }
    } finally {
      setIsLookingUp(false);
    }
  }

  /**
   * Write the whole queue, one book at a time, until a member stops it.
   *
   * **The loop is `lib/bulkWrite.ts`**, which the two import cards on the
   * settings page walk too: the concurrency rule, the stop between books, the
   * progress report and the short count that is not damage are one set of rules
   * with one home. What stays here is what a scanned row is, which is a book
   * and possibly a sighting.
   */
  async function addAll() {
    const ready = entries.filter(isReady);
    if (ready.length === 0) return;

    stopAddingRequested.current = false;
    setIsAdding(true);
    // **The previous run's verdict goes when this one starts.** A stop leaves
    // rows in the queue precisely so they can be added, so a second press is
    // the ordinary path now, and the banner saying what the last run did not
    // reach would stand over those rows while they are being written.
    setResult(null);
    const shelf = normaliseLocation(location);

    // **Asked again for every row nobody has asked about yet**, which is a
    // row whose pick lookup failed or had not answered when this was pressed.
    // This is the guarantee that a re-picked folder adds nothing twice; the
    // lookup at the pick is what lets the queue say so beforehand.
    const unasked = ready.flatMap((entry) =>
      entry.reference !== undefined && entry.heldBy === undefined
        ? [{ key: entry.key, references: filesOf(entry), format: entry.format }]
        : [],
    );
    const heldNow = await askWhoHolds(unasked, whoHolds);
    const landings: Landing[] = [];

    /**
     * One row, landed by `lib/fileLanding.land`, and what that makes of it
     * here.
     *
     * **Only a throw makes the row a failure**, because the shared loop
     * records one by nothing else. So a row whose book was made, or which is
     * on its holder already, returns; at the ceiling it returns too, which
     * takes it out of the queue as a counted row. A book of another format
     * throws `HeldInAnotherFormat`, which is the copy offer, and a tie throws
     * `HeldUnnamed`, which is its own reason.
     */
    async function addOne(entry: ScannedEntry) {
      const landing = await land(
        {
          // The same request builder as the one-book flow, so a field added
          // there cannot quietly go missing from a rapid run. Everything a
          // rapid run does not offer takes its blank value: no cover, no
          // tags, not private. `format` is the exception and is carried off
          // the entry, because a picked file answers it and a barcode does
          // not.
          body: toScanRequest({
            ...blankPending(shelf),
            format: entry.format,
            draft: entry.draft!,
          }),
          references: filesOf(entry),
          format: entry.format,
          held: heldNow.get(entry.key) ?? entry.heldBy,
          identifierWasRead: theIsbnWasRead(entry),
        },
        {
          create: (data) => scanAdd.mutateAsync({ data }),
          report: (bookId, data) =>
            reportReference.mutateAsync({ bookId, data }),
          copiesOf: listCopies,
        },
      );
      landings.push(landing);
      switch (landing.kind) {
        case "added":
        case "added-unreferenced":
        case "on-holder":
        case "at-ceiling":
          return;
        case "other-format":
          throw new HeldInAnotherFormat(landing.holderId);
        case "tie":
          throw new HeldUnnamed();
        case "failed":
          // Rethrown rather than reported here: the row is the loop's to
          // record, and swallowing it would count a book that is not in the
          // catalogue.
          throw landing.thrown;
        default:
          landing satisfies never;
      }
    }

    const outcome = await writeOneAtATime(ready, {
      post: addOne,
      onProgress: setAddProgress,
      stopped: () => stopAddingRequested.current,
    });

    // **On any book at all, including a run the member stopped.** The shelf is
    // where those books physically went, so the next run should offer it; a
    // member who stopped because the shelf was wrong changes one field, and one
    // who stopped for any other reason would otherwise type it again.
    if (outcome.added > 0) rememberLastLocation(shelf);
    // Once for the batch rather than once per book, and the catalogue rather
    // than everything: a rapid run leaves the scanner open, so a keyless
    // invalidate re-spent the search quota in the middle of a shelf.
    invalidate.catalogue();
    apply({
      kind: "batch-ran",
      walked: outcome.attempted.map((entry) => entry.key),
      failures: outcome.failures.map(({ item, thrown }) =>
        thrown instanceof HeldInAnotherFormat
          ? { row: item, heldInAnotherFormat: thrown.holderId }
          : {
              row: item,
              reason:
                thrown instanceof HeldUnnamed
                  ? { kind: "held-unnamed" }
                  : reasonForError(thrown),
            },
      ),
    });
    setIsAdding(false);
    setAddProgress(null);
    const counts = countLandings(landings);
    setResult({
      // From the landings rather than the shared loop, which counts every
      // row that did not throw, a row already in the library among them.
      added: counts.added,
      failed: outcome.failures.length,
      unreferenced: counts.unreferenced,
      already: counts.already,
      atCeiling: counts.atCeiling,
      filesLeft: counts.filesLeft,
      stopped: outcome.stopped,
    });
  }

  /**
   * File one row as its own copy of the book its ISBN belongs to, and say
   * where the file is on that copy.
   *
   * **The press `lib/fileLanding.whereItLands` refuses to make for the member.** The copy
   * route is the one the single book flow's "add as another copy" uses, with
   * the same body builder, so a copy made here inherits the work, the tags and
   * the privacy of the holder exactly as one made there does. The format is
   * the file's, which is the whole point of the copy.
   *
   * The row leaves the queue once the copy exists, whatever the reference
   * does, for the reason `addOne` gives: a created book put back as a failure
   * is added again into a duplicate. The verdict above the queue moves by one
   * row, so it keeps describing what is left beneath it. The files go through
   * `lib/fileLanding.recordOnCopy`, so a location another Book holds is left
   * there as it is on the holder path.
   */
  async function addAsCopy(key: string) {
    const entry = entries.find((one) => one.key === key);
    if (entry?.copyOf === undefined || entry.reference === undefined) return;
    setIsAddingCopy(true);
    try {
      await copyTheRow(key, entry.copyOf, entry);
    } finally {
      setIsAddingCopy(false);
    }
  }

  /** `addAsCopy`'s requests, between the hold being taken and released. */
  async function copyTheRow(
    key: string,
    holderId: number,
    entry: ScannedEntry,
  ) {
    const format = entry.format;
    let copyId: number;
    try {
      const copy = await addAnotherCopy.mutateAsync({
        bookId: holderId,
        data: toCopyRequest({
          ...blankPending(normaliseLocation(location)),
          format,
        }),
      });
      copyId = copy.id;
      // The offer goes the moment the copy exists, so a second press while
      // the reference is in flight cannot post a second copy.
      apply({ kind: "copy-made", key });
    } catch (error) {
      // The offer stays, so the press can be made again; the reason says why
      // this one did not take.
      apply({ kind: "copy-refused", key, reason: reasonForError(error) });
      return;
    }
    const { left, recorded } = await recordOnCopy(
      copyId,
      filesOf(entry),
      (bookId, data) => reportReference.mutateAsync({ bookId, data }),
    );
    // A copy is a new book, the reason `useScanFlow.addCopy` gives.
    invalidate.catalogue();
    apply({ kind: "removed", key });
    setResult((last) => ({
      added: (last?.added ?? 0) + 1,
      failed: Math.max(0, (last?.failed ?? 0) - 1),
      unreferenced: (last?.unreferenced ?? 0) + (recorded ? 0 : 1),
      already: last?.already ?? 0,
      atCeiling: last?.atCeiling ?? 0,
      filesLeft: (last?.filesLeft ?? 0) + left,
      stopped: last?.stopped ?? false,
    }));
  }

  // One reading of the queue for every control that quotes a figure.
  const figures = figuresOf(entries);

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
    pickFiles,
    isReading: isReading(entries),
    skipped,
    figures,
    lookUpTheNames: () => void runTheLookups(needsALookup),
    lookUpTheKeptNames: () => void runTheLookups(canBeAskedAgain),
    stopLookingUp: () => {
      stopRequested.current = true;
      // The run may be between two calls rather than inside one, and the loop
      // reads the flag only at its top. Without this the button is inert for up
      // to a whole interval.
      endTheWait.current?.();
    },
    isLookingUp,
    chooseFor: (key, match) => apply({ kind: "chosen", key, match }),
    takeTheRecord: (key) => apply({ kind: "record-taken", key }),
    keepTheFile: (key) => apply({ kind: "kept-the-file", key }),
    keepTheName: (key) => apply({ kind: "kept-the-name", key }),
    keepEveryNameForNow: () => apply({ kind: "kept-every-name-for-now" }),
    remove: (key) => apply({ kind: "removed", key }),
    splitApart: (key) => void splitTheGroup(key),
    dropSubject: (key, subject) =>
      apply({ kind: "subject-dropped", key, subject }),
    clear: () => {
      apply({ kind: "cleared" });
      // The count goes with the queue it described. Leaving it would tell
      // somebody starting again what happened to a pick they discarded.
      setSkipped(0);
      setLibraryNotice(null);
    },
    libraryNotice,
    addAll: () => void addAll(),
    isAdding,
    addAsCopy: (key) => void addAsCopy(key),
    isAddingCopy,
    stopAdding: () => {
      // No wait to interrupt, unlike the paced lookup: the write has no floor
      // between books, so the next check is one request away.
      stopAddingRequested.current = true;
    },
    addProgress,
    result,
  };
}
