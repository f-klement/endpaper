/**
 * The scan → lookup → confirm flow.
 *
 * ScanPage's whole contact with the API. The page and its components take
 * plain values and callbacks.
 */

import { useCallback, useRef, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { errorText } from "../../components/ErrorState";
import { useInvalidate } from "../../api/invalidate";
import { ApiError } from "../../api/mutator";

import {
  getLookupIsbnQueryKey,
  getSearchBooksQueryKey,
  lookupIsbn,
  searchBooks,
  getListTagsQueryKey,
  useAddBookTag,
  useAddCopy,
  useCreateTag,
  useListLocations,
  useListTags,
  useLookupIsbn,
  useReportDigitalReference,
  useScanAdd,
  useSearchBooks,
  useUploadCover,
} from "../../api/generated/endpoints/books/books";
import { useGetFeatureFlags } from "../../api/generated/endpoints/settings/settings";
import { BookFormat } from "../../api/generated/model";
import type {
  BookMatch,
  BookSearchOut,
  CatalogueSource,
  DigitalReferenceIn,
  LocationOut,
  TagOut,
} from "../../api/generated/model";
import { QUERY_FLOOR } from "../../lib/bookBounds";
import { referenceFor } from "../../lib/digitalReference";
import { useTranslation, type MessageKey } from "../../i18n";
import type { FileFailure } from "../../lib/fileReaders";
import type { AudioFailure, AudioTags } from "../../lib/audiobook";
import type {
  AudiobookGroup,
  AudioFileNaming,
} from "../../lib/audiobookGroups";
import {
  FORMAT_FOR_EXTENSION,
  plainName,
  queryFor,
  readName,
  supportedExtension,
  type FileNaming,
  type SupportedExtension,
} from "../../lib/fileName";
import {
  normaliseLocation,
  readLastLocation,
  rememberLastLocation,
} from "../../lib/lastLocation";
import {
  blankDraft,
  blankPending,
  draftFromAudiobook,
  draftFromFile,
  draftFromName,
  draftFromMatch,
  draftFromLookup,
  toCopyRequest,
  toScanRequest,
  type BookDraft,
  type PendingBook,
} from "./types";

/**
 * What a member is told about a file that yielded nothing.
 *
 * A total mapping of `FileFailure` rather than a switch, so a reason added to
 * that closed union is a compile error here instead of a file reported with
 * whatever the last arm said.
 */
const FILE_FAILURES: Record<FileFailure, MessageKey> = {
  "not-an-epub": "file.notAnEpub",
  "not-a-mobi": "file.notAMobi",
  "not-an-fb2": "file.notAnFb2",
  "not-a-comic": "file.notAComic",
  "not-a-pdf": "file.notAPdf",
  damaged: "file.damaged",
  protected: "file.protected",
  "too-large": "file.tooLarge",
  unsupported: "file.unsupported",
  "no-inflate": "file.noInflate",
};

/**
 * What a member is told about an audio file that said nothing about itself.
 *
 * Its own total mapping rather than an arm of `FILE_FAILURES`, because the two
 * unions are closed separately: an audio file that carries no tags is an
 * ordinary file rather than a broken one, and it still becomes a candidate
 * under whatever its folder is called.
 */
const AUDIO_FAILURES: Record<AudioFailure, MessageKey> = {
  "no-tags": "audio.noTags",
  unreadable: "audio.unreadable",
};

/** Below this, a search is noise rather than a query. Matches the API bound. */
const MIN_QUERY_LENGTH = QUERY_FLOOR;

/**
 * How many catalogue calls a minute the filename fallback may start.
 *
 * **Priced against the limiter the same member is already spending, not against
 * the deadline.** `backend/ratelimit.py`'s `METADATA_LIMIT` allows 60 metadata
 * calls a minute per member, and it is the limiter on the ISBN lookup behind
 * every scanned barcode and on the title search box as well as on this. So the
 * fallback takes half of it and leaves the other half to the page it runs on:
 * a folder of three hundred files must not be able to answer 429 to the barcode
 * somebody scans in the middle of it.
 *
 * **Half is chosen rather than measured**, and what it is chosen against is
 * stated so the next reader can move it: the other paths on this page.
 *
 * The wall clock it buys, for 300 files: 10.0 minutes here, against 6.0 to 9.0
 * serialised at the 1.2s to 1.8s a healthy search measures by
 * `metadata.SEARCH_DEADLINE_SECONDS`' own figure, which is 33 to 50 starts a
 * minute and over this share. So the pace costs at most four minutes and the
 * interval is above the slowest healthy search, which is why one call in flight
 * is never what binds.
 *
 * `tests/pages/ScanPage/hooks.test.tsx` recomputes the interval from the
 * backend's own constant rather than restating it.
 */
export const FALLBACK_STARTS_PER_MINUTE = 30;

/** One start per this long, which is the whole of the pace. */
export const FALLBACK_INTERVAL_MS = 60_000 / FALLBACK_STARTS_PER_MINUTE;

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

/**
 * How a row came to be standing under its own file name.
 *
 * A closed set, and it is a named type rather than an inline union so that
 * `OFFERED_AGAIN` can be keyed on it: a fourth answer is then a compile error
 * until somebody has decided whether it may be looked up again.
 */
export type CatalogueAnswer = "nothing" | "records" | "records-for-now";

/** One book caught by the rapid scanner or picked as a file, and how it has gone so far. */
export interface ScannedEntry {
  /**
   * Identity in the queue, and what a removal names.
   *
   * **Not the ISBN, and that is the whole reason this field exists.** A file is
   * the second way into this queue and most files carry no ISBN at all:
   * measured over 79 real EPUBs, 4 did. Keying on one would collapse every
   * ISBN-less pick into a single entry.
   */
  key: string;
  /** What the queue shows and what a removal is announced by. */
  label: string;
  /** Empty when the entry came from a file that named none. */
  isbn: string;
  /**
   * What kind of object this copy is, where the way it arrived answers that.
   *
   * **A picked EPUB is an ebook and the container says so**, which is not the
   * guess `docs/decisions.md` refuses when it leaves `format` nullable: that
   * refuses a value written across every imported row on no evidence, and
   * `csv_import` already reads the literal string `epub` as this answer. A
   * barcode carries no such evidence and stays blank.
   */
  format: BookFormat | "";
  /**
   * Where this entry has got to.
   *
   * **`derived` is a book, not a failure, and that is the decision behind the
   * whole fallback path.** A file whose own metadata said nothing still has a
   * name, and a row carrying what the name said is added by `addAll` rather
   * than skipped. It is the same call the OPDS sync makes for a holding with no
   * description: reported as created, because it is.
   */
  state:
    | "looking-up"
    | "reading"
    | "derived"
    | "searching"
    | "choosing"
    | "found"
    | "not-found"
    | "failed";
  draft: BookDraft | null;
  /** Why it could not be read, or could not be added once the batch has run. */
  reason?: string;
  /**
   * What to ask the catalogue about this file, derived from its name.
   *
   * Absent for a barcode, which needs no such thing, and for a file whose name
   * reduced to nothing a catalogue could be asked about.
   */
  query?: string;
  /** What the catalogue offered for it, for the member to accept or reject. */
  matches?: BookMatch[];
  /**
   * What the catalogue answered, where the answer left the row under its own
   * name.
   *
   * **Values rather than one flag**, because the ways a row keeps its file name
   * are different sentences to the member. `"nothing"` is a catalogue with no
   * record, which for a title that exists only as a file is the ordinary
   * outcome and is what `fallback.aboutEbooks` explains. `"records"` is a
   * catalogue that had some and a member who preferred the name, and saying
   * anything about ebooks to them would describe something that did not happen.
   * `"records-for-now"` is the same records and a member who was clearing the
   * queue rather than answering about this book, so the row can be asked
   * again; `OFFERED_AGAIN` is where that difference is spent.
   *
   * **Absent means nothing has been asked**, which is what the run and the count
   * both read, and it is what a call that could not be made leaves behind: a
   * catalogue nobody reached has answered nothing and is worth asking again.
   */
  answered?: CatalogueAnswer;
  /**
   * The audio files this one candidate was made of, and the rule that said so.
   *
   * **Present only for an audiobook**, and it is the whole of the inversion
   * this format brings: every other row here is one file, and one audiobook is
   * usually a folder of chapter files. `lib/audiobookGroups.ts` holds the rule.
   *
   * Carried rather than counted, for two reasons that are the same reason: the
   * queue shows the member which files a candidate claims before anything is
   * added, and `splitApart` needs them back to undo a grouping the member
   * disagrees with. It is also what dedup is decided on, so picking the same
   * folder twice queues nothing twice.
   */
  group?: AudiobookGroup;
  /**
   * The picked files this row claims, where it came from files.
   *
   * **Set before the grouping is known and kept afterwards**, which is the one
   * job it has: an audiobook's rows cannot be made until every file in the pick
   * has been read, and in that window the queue still has to be able to say
   * that those files are spoken for. Picking the same folder twice queues
   * nothing twice because of this.
   *
   * **Only the reading row carries it.** Once the files are grouped, `group`
   * holds them and is where the claim is read from: setting both would be one
   * fact in two fields that agree by construction and by nothing else.
   */
  claims?: readonly string[];
  /**
   * Where the file this row was drafted from is, as the server takes it.
   *
   * **Derived at the pick and carried, because the `File` does not survive the
   * read.** Only the key and the label go into the queue, so by the time the
   * batch runs there is nothing left to ask. `lib/digitalReference.ts` decides
   * what this browser may honestly claim, and answers nothing for a file picked
   * one at a time.
   *
   * **Absent for an audiobook row**, and that is the format's own inversion
   * again rather than an omission: a row standing for forty chapter files has
   * no one file to point at, and a book holds sixteen references at the most.
   */
  reference?: DigitalReferenceIn;
  /**
   * Whether this row's ISBN was read out of the file's **name**.
   *
   * **Carried rather than read off the state, because the state deliberately
   * stops saying it.** `lookUpTheName` promotes a row to `found` whenever the
   * ISBN lookup answers, and every row reaching that line is one standing under
   * its own name, so after a successful lookup `found` covers a file that
   * stated its identifier and a name that happened to contain one. The comment
   * there says as much: a name carrying an ISBN takes the route a barcode
   * takes. That collapse is right for the lookup and wrong for anything asking
   * where the identifier came from.
   *
   * Set by `fromTheName` and cleared by `chooseFor`, which are the only two
   * places that know. `theIsbnWasRead` is the one reader.
   */
  isbnFromTheName?: true;
}

/**
 * Every picked file an entry claims.
 *
 * One entry is one file everywhere except an audiobook, where it is many. Read
 * off the entries rather than kept beside them, because a second record of what
 * has been queued is a second record to keep in step.
 */
function claimedKeys(entries: readonly ScannedEntry[]): Set<string> {
  const keys = new Set<string>();
  for (const entry of entries) {
    const claimed = entry.group?.files.map((file) => file.key) ??
      entry.claims ?? [entry.key];
    for (const key of claimed) keys.add(key);
  }
  return keys;
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

/** The queue key for a scanned barcode. One book, one ISBN, one entry. */
function scannedKey(isbn: string): string {
  return `isbn:${isbn}`;
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

/** An entry with records offered and neither taken nor refused. */
function isBeingDecided(entry: ScannedEntry): boolean {
  return entry.state === "choosing";
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
 * and every row reaching that call is one standing under its own name, so the
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

/**
 * Whether an answer leaves the row worth offering a second pass.
 *
 * **A map keyed on the union rather than a disjunction**, which is what makes
 * this self enforcing: a fourth answer does not compile until it appears here,
 * so nobody can add one and inherit an offer, or the absence of one, by
 * omission. The default is exactly what the author of a new answer would not
 * think to state.
 *
 * A member who refused the records answered about that book and is not asked
 * again. A member who kept the names in bulk was clearing a queue rather than
 * answering, and the whole of the owner's decision on 2026-09-10 is that those
 * can come back.
 */
const OFFERED_AGAIN: Record<CatalogueAnswer, boolean> = {
  nothing: false,
  records: false,
  "records-for-now": true,
};

/**
 * An entry the catalogue has not been asked about and could be.
 *
 * One predicate rather than a filter written twice, because the count on the
 * button and the list the run walks have to be the same set: a button offering
 * to look up twelve and a run that looks up nine is a screen reporting
 * something the page did not do.
 *
 * **An answered row is never in here, whatever the answer**, which is the
 * invariant the bulk keep was not allowed to cost: a member who picks ten more
 * files and presses this must look up ten, not the two hundred and fifty they
 * had just cleared off the screen. Those are `canBeAskedAgain`, which is a
 * second control saying so in its own words.
 */
function needsALookup(entry: ScannedEntry): boolean {
  return (
    entry.state === "derived" &&
    entry.answered === undefined &&
    (entry.isbn !== "" || entry.query !== undefined)
  );
}

/**
 * An entry the catalogue answered, whose answer the member left open.
 *
 * **Disjoint from `needsALookup` by construction**, on `answered` being set
 * against unset rather than on two lists that happen not to overlap: a row in
 * both would be looked up twice by two presses that each said it was the whole
 * of the work.
 */
function canBeAskedAgain(entry: ScannedEntry): boolean {
  return (
    entry.state === "derived" &&
    entry.answered !== undefined &&
    OFFERED_AGAIN[entry.answered] &&
    (entry.isbn !== "" || entry.query !== undefined)
  );
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
  /** Files whose name is all that is left to ask the catalogue about. */
  waiting: number;
  /**
   * Files with records offered and neither taken nor refused.
   *
   * **Derived from the predicate `addAll` excludes, not from a second one
   * spelled the same.** The screen says how many rows the batch is going to
   * leave where they are, so a predicate written twice is a screen that can
   * report something the page did not do. Same reason `needsALookup` is one
   * function rather than a filter at each site.
   */
  deciding: number;
  /**
   * Files kept under their names in bulk, which the catalogues may be asked
   * about again.
   *
   * **Not part of `waiting`, and that is the point of counting it separately.**
   * A member who clears a queue of two hundred and fifty and then picks ten more
   * files presses a button that says ten. These come back through a press of
   * their own, which names them.
   */
  keptForNow: number;
  /** Roughly how long looking all of them up would take, in minutes. */
  paceMinutes: number;
  /** The same figure for a second pass over the names kept in bulk. */
  keptPaceMinutes: number;
  /**
   * Ask the catalogue about every file that has only its name.
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
  /** Take one of the records the catalogue offered for a file. */
  chooseFor: (key: string, match: BookMatch) => void;
  /** Reject all of them and keep what the name said. */
  keepTheName: (key: string) => void;
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
   */
  result: { added: number; failed: number; unreferenced: number } | null;
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
  // A ref rather than state: the paced run reads it between calls, and a state
  // read inside a running loop is the value it started with.
  const stopRequested = useRef(false);
  // How to end the wait between two calls early. Null whenever the run is not
  // waiting, which is every moment a stop has nothing to interrupt.
  const endTheWait = useRef<(() => void) | null>(null);
  const [location, setLocation] = useState(readLastLocation);
  const [result, setResult] = useState<{
    added: number;
    failed: number;
    unreferenced: number;
  } | null>(null);

  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const scanAdd = useScanAdd();
  const reportReference = useReportDigitalReference();
  const locations = useKnownLocations();
  // For the per-row failure reason: a rejected fetch has no message worth
  // showing, so `errorText` needs the catalogue to supply one. The locale is
  // for the paced lookup, which breaks ties towards the reader's own printing
  // exactly as the search box does.
  const { t, locale } = useTranslation();

  /** Rewrite the one entry with this key, leaving every other alone. */
  function settle(key: string, patch: Partial<ScannedEntry>) {
    setEntries((current) =>
      current.map((entry) =>
        entry.key === key ? { ...entry, ...patch } : entry,
      ),
    );
  }

  function capture(isbn: string) {
    const key = scannedKey(isbn);
    setEntries((current) => {
      // The camera fires continuously while a barcode is in frame, so the same
      // book arrives many times a second. Without this the queue fills with
      // one book.
      if (current.some((entry) => entry.key === key)) return current;
      void lookUp(isbn);
      return [
        ...current,
        {
          key,
          label: isbn,
          isbn,
          format: "",
          state: "looking-up",
          draft: null,
        },
      ];
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
      settle(key, { state: "found", draft: draftFromLookup(lookup) });
    } catch {
      // Neither source knew it. Kept in the queue as a blank draft rather than
      // dropped, so it can still be added by hand instead of silently vanishing
      // between the shelf and the catalogue.
      settle(key, { state: "not-found", draft: blankDraft(isbn) });
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
   * The already-queued check happens inside the updater and starts the reads
   * from there, which is the shape `capture` uses and for the same reason: the
   * queue is the only record of what has been picked, so asking anything else
   * would be a second one to keep in step. The skipped count is taken **before**
   * it, because an updater that counts is an updater run twice under a strict
   * render counting twice.
   */
  function pickFiles(files: readonly File[]) {
    const walked = files.map((file) => ({
      file,
      extension: supportedExtension(file.name),
    }));
    setSkipped(walked.filter((walk) => walk.extension === null).length);

    const supported = walked.filter(
      (walk): walk is { file: File; extension: SupportedExtension } =>
        walk.extension !== null,
    );

    setEntries((current) => {
      const queued = claimedKeys(current);
      const unqueued = supported.filter(
        (walk) => !queued.has(pickedKey(walk.file)),
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
      if (fresh.length === 0) {
        return pending ? [...current, pending] : current;
      }
      void readFiles(fresh.map((walk) => walk.file));
      return [
        ...current,
        ...(pending ? [pending] : []),
        ...fresh.map((walk) => ({
          key: pickedKey(walk.file),
          // Taken while the `File` is still in hand. After the read the queue
          // holds a key and a label and could not derive this if it wanted to.
          reference: referenceFor(walk.file) ?? undefined,
          // Cleaned for the reason every derived value is: a name is somebody
          // else's text, and this one is printed beside a title that was.
          label: plainName(walk.file.name),
          isbn: "",
          // The extension answers this, and it is the same kind of evidence a
          // zip container is rather than the guess `format` is nullable to
          // refuse.
          format: FORMAT_FOR_EXTENSION[walk.extension],
          state: "reading" as const,
          draft: null,
        })),
      ];
    });
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
  ): ScannedEntry {
    const first = picked[0]!.file;
    const folders = foldersOf(first);
    const keys = picked.map((walk) => pickedKey(walk.file));
    return {
      key: `audio:${[...keys].sort()[0]}:${keys.length}`,
      label: plainName(folders.at(-1) ?? first.name),
      isbn: "",
      format: BookFormat.audiobook,
      state: "reading",
      draft: null,
      claims: keys,
    };
  }

  /**
   * The entry a file's own name makes, and the note saying why it came to that.
   *
   * A name reducing to nothing is the one way a picked file still fails: the API
   * requires a title, and saying so here is better than a 422 halfway through
   * somebody's batch.
   */
  function fromTheName(
    naming: FileNaming,
    note: string | undefined,
    // **The state is in the return type rather than merely in both arms.** A
    // caller spreading this over a row has to end with one, and a `Partial`
    // says it might not, which is a row with no state and no compiler to say so.
  ): Partial<ScannedEntry> & Pick<ScannedEntry, "state"> {
    const clues = readName(naming);
    const draft = draftFromName(clues);
    if (draft.title === "") {
      return { state: "failed", reason: note ?? t("file.noTitle") };
    }
    return {
      state: "derived",
      isbn: draft.isbn,
      draft,
      query: clues.query ?? undefined,
      reason: note,
      // The one site that knows, and it stays true through the lookup that
      // promotes this row to `found`: what the catalogue answered about an ISBN
      // does not change where the ISBN came from.
      isbnFromTheName: draft.isbn === "" ? undefined : true,
    };
  }

  async function readFiles(files: readonly File[]) {
    const { readerFor } = await import("../../lib/fileReaders");
    for (const file of files) {
      const key = pickedKey(file);
      let note: string | undefined;
      try {
        // **Which reader opens this is `lib/fileReaders.ts`'s question, not
        // this loop's.** An extension with no reader falls through to its name,
        // which is this path's whole point: for a PDF an unusable metadata
        // block is the common case rather than the exception.
        const reader = await readerFor(file.name);
        const reading = reader ? await reader(file) : null;
        if (reading && !reading.ok) {
          note = t(FILE_FAILURES[reading.failure]);
        } else if (reading) {
          const draft = draftFromFile(reading.metadata);
          if (draft.title !== "") {
            settle(key, { state: "found", isbn: draft.isbn, draft });
            continue;
          }
          // The file opened and named no title, so what is left is its name.
          note = t("file.noTitle");
        }
      } catch {
        // A bug in the reader rather than anything the file did. Still one
        // entry, and the name is still a signal.
        note = t("file.unreadable");
      }
      settle(
        key,
        fromTheName({ name: file.name, folders: foldersOf(file) }, note),
      );
    }
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
    for (const { file, extension } of picked) {
      // **Nothing is dropped here, and the loop used to drop it.** A file the
      // reader has no arm for is still a file the member picked and still has a
      // name, and skipping it took it out of the pick with no row and no count:
      // a pick made entirely of them replaced its own reading row with nothing.
      const audio = audiobook.isAudioExtension(extension) ? extension : null;
      let tags: AudioTags | null = null;
      // `file.unsupported`, not an audio reason: a file routed here that this
      // has no arm for is not an audio file that said nothing.
      let note: string | undefined = audio ? undefined : t("file.unsupported");
      if (audio) {
        try {
          const reading = await audiobook.readAudioTags(file, audio);
          if (reading.ok) tags = reading.tags;
          else note = t(AUDIO_FAILURES[reading.failure]);
        } catch {
          // A bug in the reader rather than anything the file did. The file is
          // still one part of a book and its name still says something.
          note = t("file.unreadable");
        }
      }
      read.push({
        key: pickedKey(file),
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
        note,
      });
    }

    const candidates = groups.groupAudiobooks(read).map(entryForGroup);
    // **In the pending row's place, and only if it is still there.** A member
    // who discarded the queue while this was reading gets an empty queue rather
    // than rows arriving into the one they just emptied, and nothing else has
    // to know that a discard happened.
    setEntries((current) =>
      current.flatMap((entry) =>
        entry.key === pendingKey ? candidates : [entry],
      ),
    );
  }

  /**
   * One candidate book, from the files the grouping rule put together.
   *
   * **The queue key is the group's smallest member key and its size**, not a
   * digest of them: the smallest key is claimed by exactly one entry, and the
   * size is what makes a split's rows different keys from the group they came
   * from.
   *
   * **What the files said is preferred to what they are called**, and only
   * where they said nothing does this fall to the folder name through the same
   * `fromTheName` every other picked file uses.
   */
  function entryForGroup(group: AudiobookGroup): ScannedEntry {
    const keys = group.files.map((file) => file.key);
    const base = {
      key: `audio:${[...keys].sort()[0]}:${keys.length}`,
      isbn: "",
      // Not read off an extension, because a group has several. `isAudio` is
      // the test every member file passed to get here, and it is exactly this
      // answer from `FORMAT_FOR_EXTENSION`.
      format: BookFormat.audiobook,
      group,
      draft: null,
    };
    // Only from a group of one. A note from one file of forty describes that
    // file and would read as though the whole book had failed.
    const note = group.files.length === 1 ? group.files[0]!.note : undefined;

    const draft = draftFromAudiobook(group);
    if (draft !== null) {
      return {
        ...base,
        label: draft.title,
        state: "derived",
        draft,
        // **Through `queryFor`, not through a second bounding written here.**
        // What the catalogue is asked is a title and an author, which is what
        // `q` takes, and the cleaning, the floor and the cut in code points all
        // live in one place already. Not through `readName`, which is a rule
        // about a **file name**: it would strip a trailing `.mp3` off an album
        // and hunt an ISBN through the author line.
        query:
          queryFor([draft.title, draft.author].filter(Boolean).join(" ")) ??
          undefined,
        reason: note,
      };
    }

    const naming = groupNaming(group);
    return {
      ...base,
      label: plainName(naming.name),
      ...fromTheName(naming, note),
    };
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
    setEntries((current) =>
      current.flatMap((entry) => {
        if (entry.key !== key || !entry.group) return [entry];
        if (entry.group.files.length < 2) return [entry];
        return groups.splitApart(entry.group).map(entryForGroup);
      }),
    );
  }

  /**
   * The name a group with no usable tags derives its book from.
   *
   * The folder for several files and the file itself for one, which is what a
   * person named after the book in each case: a chapter file is named after its
   * chapter, and the folder over it after the work.
   */
  function groupNaming(group: AudiobookGroup): FileNaming {
    const first = group.files[0]!;
    if (group.files.length === 1) {
      return { name: first.name, folders: first.folders };
    }
    const own = first.folders.at(-1);
    return own === undefined
      ? { name: first.name, folders: [] }
      : { name: own, folders: first.folders.slice(0, -1) };
  }

  /**
   * Ask the catalogue about one file, and never twice about the same one.
   *
   * **One call per file, which is what makes the pace's arithmetic true.** A
   * name carrying an ISBN takes the route a barcode takes, because an ISBN is an
   * identifier rather than a guess; anything else is a title search. Neither
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
        settle(entry.key, { state: "found", draft: draftFromLookup(lookup) });
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
      if (answer.matches.length === 0) {
        settle(entry.key, {
          state: "derived",
          answered: "nothing",
          reason: t("fallback.notInCatalogues"),
        });
        return;
      }
      settle(entry.key, { state: "choosing", matches: answer.matches });
    } catch (error) {
      // **A 404 is an answer and everything else is a failure to ask**, which
      // `_lookup_failure` in the books router separates deliberately: 404 is
      // nobody knowing the ISBN, 503 is no source having been reachable. The
      // barcode path in this file reads the same throw the same way. Collapsing
      // the two offered the retry that buys nothing and withheld the one that
      // does.
      const unknown = error instanceof ApiError && error.status === 404;
      settle(entry.key, {
        state: "derived",
        answered: unknown ? "nothing" : undefined,
        reason: t(
          unknown ? "fallback.notInCatalogues" : "fallback.lookupFailed",
        ),
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
        // **The note and the answer go with the state.** A row being asked
        // about has no answer and is not standing under its name for a reason
        // it can still state: leaving either behind renders a list of catalogue
        // records under the sentence saying the name was kept, and leaves the
        // row counted as kept while it is being decided again.
        settle(entry.key, {
          state: "searching",
          answered: undefined,
          reason: undefined,
        });
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

  async function addAll() {
    // **A row still being decided is not offered**, for the reason a row with no
    // draft is not: it is exactly what somebody still has to decide about, and
    // filing it under its file name would throw away every record the catalogue
    // found for it with nothing said on screen.
    const ready = entries.filter(
      (entry) => entry.draft !== null && !isBeingDecided(entry),
    );
    if (ready.length === 0) return;

    setIsAdding(true);
    const shelf = normaliseLocation(location);
    let added = 0;
    let unreferenced = 0;
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
        // private. `format` is the exception and is carried off the entry,
        // because a picked file answers it and a barcode does not.
        const book = await scanAdd.mutateAsync({
          data: toScanRequest({
            ...blankPending(shelf),
            format: entry.format,
            draft,
          }),
        });
        added += 1;
        if (entry.reference) {
          // **Its own `try`, outside the book's, and that placement is the
          // whole of it.** The book exists by the time this runs, so a throw
          // caught by the arm below would report a created book as failed and
          // a member would add it again into a duplicate. Same shape as the
          // cover and the tags in `useScanFlow.confirm`, for the same reason.
          //
          // **A second request per book, sequential with the first.** There is
          // no batched route: the contract is one sighting per location, and a
          // sighting is idempotent on the pair, so a folder imported twice
          // refreshes rows rather than doubling them. A three hundred book
          // pick is six hundred requests against one SQLite writer, which is
          // the reason this loop was already sequential.
          try {
            await reportReference.mutateAsync({
              bookId: book.id,
              data: entry.reference,
            });
          } catch {
            // Counted rather than swallowed. A member who pointed at a folder
            // so the library would know where their files are should not be
            // told three hundred were added and left to discover that none of
            // them says where it came from.
            //
            // **Not counted as refused**, which this arm also catches: a
            // dropped connection, a timeout and a browser that went offline all
            // land here and none of them is the server saying no.
            unreferenced += 1;
          }
        }
      } catch (error) {
        // **The book this row is a duplicate of is where its file is.** Re
        // importing a folder somebody imported last month is the case the
        // sighting was made idempotent for, and every book in it answers 409,
        // so a reference posted only after a successful create would be posted
        // on exactly the pick that needs it least. `bookId` is present only
        // where the holder is visible to this member, which is the same test
        // `addCopy` applies before offering to copy it.
        const holder = error instanceof ApiError ? error.bookId : undefined;
        if (holder !== undefined && entry.reference && theIsbnWasRead(entry)) {
          // The row is a failure whichever way this goes, and it carries its
          // reason on screen, so a refusal here is not counted a second time.
          await reportReference
            .mutateAsync({ bookId: holder, data: entry.reference })
            .catch(() => undefined);
        }
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
    // **Only the ones that landed leave the queue, and that means the ones that
    // were never offered stay too.** This used to keep the failures alone,
    // which silently dropped every entry with no draft: a barcode whose lookup
    // was still in flight when the button was pressed vanished between the
    // shelf and the catalogue, and a file that could not be read would vanish
    // the same way. Both are exactly what somebody still has to decide about.
    const offered = new Set(ready.map((entry) => entry.key));
    const failed = new Map(failures.map((entry) => [entry.key, entry]));
    setEntries((current) =>
      current
        .filter((entry) => !offered.has(entry.key) || failed.has(entry.key))
        .map((entry) => failed.get(entry.key) ?? entry),
    );
    setIsAdding(false);
    setResult({ added, failed: failures.length, unreferenced });
  }

  // One filter, read twice. Two would let the count on the button and the
  // figure beside it disagree the first time either is edited.
  const waiting = entries.filter(needsALookup).length;
  const deciding = entries.filter(isBeingDecided).length;
  const keptForNow = entries.filter(canBeAskedAgain).length;

  /**
   * Roughly how long a paced run over this many files takes, in minutes.
   *
   * One arithmetic for both presses. Two counts is two numbers and it is the
   * same pace: writing it twice is how the second control comes to quote a
   * figure the run it starts does not keep. A floor of one minute, because
   * "about 0 minutes" is not a wait anybody recognises.
   */
  function paceFor(count: number): number {
    return Math.max(1, Math.ceil((count * FALLBACK_INTERVAL_MS) / 60_000));
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
    pickFiles,
    // Derived rather than counted. A count is a second record of the same fact
    // and drifts the first time a read ends on a path that forgets to decrement
    // it; the queue already says which entries are still being read.
    isReading: entries.some((entry) => entry.state === "reading"),
    skipped,
    waiting,
    deciding,
    keptForNow,
    // Derived from the pace rather than carried beside it, so the figure on the
    // button cannot say one thing while the run does another.
    paceMinutes: paceFor(waiting),
    keptPaceMinutes: paceFor(keptForNow),
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
    chooseFor: (key, match) =>
      settle(key, {
        state: "found",
        isbn: match.isbn13 ?? "",
        draft: draftFromMatch(match),
        matches: undefined,
        // A member looked at this record and took it, so the identifier is the
        // catalogue's rather than the name's. `settle` spreads, so the explicit
        // `undefined` clears what `fromTheName` set.
        //
        // **It clears nothing today, and that is stated rather than left to be
        // reasoned from.** A flagged row has a non empty `isbn`, so
        // `lookUpTheName` returns from the ISBN branch and never produces the
        // `choosing` state this control is rendered under, so no flagged row
        // reaches here. Kept because it is correct and free, and because the
        // path that would produce one is exactly the remedy this refusal is
        // missing. Deleting it fails no test, which is the honest rung.
        isbnFromTheName: undefined,
      }),
    keepTheName: (key) =>
      settle(key, {
        state: "derived",
        answered: "records",
        matches: undefined,
        reason: t("fallback.keptTheName"),
      }),
    keepEveryNameForNow: () =>
      setEntries((current) =>
        current.map((entry) =>
          isBeingDecided(entry)
            ? {
                ...entry,
                state: "derived",
                answered: "records-for-now",
                // Dropped from the row rather than held for an undo: they are
                // what the catalogue answers again, and holding them would be a
                // second store of a record with no rule for how long it lives.
                matches: undefined,
                reason: t("fallback.keptForNow"),
              }
            : entry,
        ),
      ),
    remove: (key) =>
      setEntries((current) => current.filter((entry) => entry.key !== key)),
    splitApart: (key) => void splitTheGroup(key),
    clear: () => {
      setEntries([]);
      // The count goes with the queue it described. Leaving it would tell
      // somebody starting again what happened to a pick they discarded.
      setSkipped(0);
    },
    addAll: () => void addAll(),
    isAdding,
    result,
  };
}
