/**
 * Data access for the Your library route.
 *
 * Bringing books in, repairing the covers they arrived without, and the field
 * definitions this household adds on top. Nothing outside this file imports
 * from `api/generated`, so regenerating the client cannot ripple into the
 * components.
 *
 * Its own file rather than a shared one, and that is what this route split was
 * for: the settings page used to hold every hook on the screen in one 554 line
 * module, so two unrelated changes to two unrelated sections collided in it.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";

import {
  getListCustomFieldsQueryKey,
  useBackfillCovers,
  useDefineCustomField,
  useDeleteCustomField,
  useListCustomFields,
  useRenameCustomField,
  useScanAdd,
} from "../../../api/generated/endpoints/books/books";
import {
  useImportCsv,
  useImportMarc,
  usePreviewImport,
  usePreviewMarc,
} from "../../../api/generated/endpoints/imports/imports";
import type {
  CoverBackfillOut,
  CustomFieldKind,
  CustomFieldOut,
  ImportPreviewOut,
  ImportResultOut,
  MarcPreviewOut,
} from "../../../api/generated/model";
import { useInvalidate } from "../../../api/invalidate";
import type { CalibreBook, CalibreFailure } from "../../../lib/calibre";
import type { SqliteFailure } from "../../../lib/sqlite";
import {
  STORE_IDS,
  STORES,
  type StoreFailure,
  type StoreId,
  type StoreLibrary,
} from "../../../lib/stores";
import {
  writeBooks,
  type ImportFailureRow,
  type ImportOutcome,
  type ImportProgress,
} from "./importing";
import {
  storeToBookCreate,
  toBookCreate,
  type StoreBookFromSource,
} from "./types";

/**
 * Bringing a library across from another service.
 *
 * Two steps rather than one, and the first is the point: a column guessed
 * wrong is invisible until after the import, and after the import the fix is
 * finding and deleting a few hundred books. So the file is read and reported
 * on before anything is written.
 */
export function useLibraryImport() {
  const invalidate = useInvalidate();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewOut | null>(null);
  const [result, setResult] = useState<ImportResultOut | null>(null);

  const previewing = usePreviewImport({
    mutation: { onSuccess: (data: ImportPreviewOut) => setPreview(data) },
  });

  const importing = useImportCsv({
    mutation: {
      onSuccess: (data: ImportResultOut) => {
        setResult(data);
        setPreview(null);
        setFile(null);
        // An import creates books, tags, authors and shelves, so every
        // catalogue view is now stale. Not the accounts or the settings: a
        // CSV import writes neither.
        invalidate.catalogue();
      },
    },
  });

  return {
    file,
    preview,
    result,

    // `mutate` for the same reason as above: the failure is surfaced through
    // `error`, not by rejecting a promise nobody is holding.
    choose: (chosen: File) => {
      setFile(chosen);
      setResult(null);
      importing.reset();
      previewing.mutate({ data: { file: chosen } });
    },

    confirm: (options: { createMissing: boolean; applyTags: boolean }) => {
      if (!file) return;
      importing.mutate({
        data: { file },
        params: {
          create_missing: options.createMissing,
          apply_tags: options.applyTags,
        },
      });
    },

    isPreviewing: previewing.isPending,
    isImporting: importing.isPending,
    error: previewing.error ?? importing.error,

    reset: () => {
      setFile(null);
      setPreview(null);
      setResult(null);
      previewing.reset();
      importing.reset();
    },
  };
}

/**
 * Fetching the covers of books that have none.
 *
 * This is the repair for a library that already exists. Storing covers as
 * books are added only ever helps books added afterwards, and the ones that
 * need it most arrived through a CSV import, which never resolved a cover.
 *
 * The run is bounded server side, so the result says how many are left and the
 * reader presses again. Deliberately not looped here: an automatic retry would
 * hammer two free public image services from a button nobody is watching.
 *
 * **The cursor is what lets pressing again make progress.** The server picks
 * its batch by book id, and a book it could not fix is still a candidate next
 * time, so without carrying `next_after_id` back the same unfixable hundred
 * would be retried for ever and the counter would never move. It comes back as
 * 0 at the end of the library, which starts the next press over and re-tries
 * the failures, since a service that was down may not be.
 */
export function useCoverBackfill() {
  const invalidate = useInvalidate();
  const [result, setResult] = useState<CoverBackfillOut | null>(null);
  const [cursor, setCursor] = useState(0);

  const backfill = useBackfillCovers({
    mutation: {
      onSuccess: (data: CoverBackfillOut) => {
        setResult(data);
        setCursor(data.next_after_id);
        // A run rewrites `cover_url` on up to a hundred books at once, and
        // every list and detail view renders it. Covers themselves are `<img>`
        // elements rather than queries, so what goes stale is the catalogue.
        invalidate.catalogue();
      },
    },
  });

  return {
    result,
    // `mutate`, not `mutateAsync`: the failure is reported through `error`.
    run: () => backfill.mutate({ params: { after_id: cursor } }),
    isRunning: backfill.isPending,
    error: backfill.error,
  };
}
export interface UseCustomFieldsResult {
  fields: CustomFieldOut[];
  define: (name: string, kind: CustomFieldKind) => void;
  rename: (fieldId: number, name: string) => void;
  remove: (fieldId: number) => void;
  isBusy: boolean;
  error: unknown;
}

/**
 * The path of one book's custom field values, as a pattern.
 *
 * A pattern rather than a key because the book id is **inside the path**, so
 * there is no prefix a key filter could match and no id to hand here anyway: a
 * rename changes the label every book draws and a delete removes rows from
 * every book. Same shape and same reason as `BOOK_RECORD` in
 * `api/invalidate.ts`.
 *
 * Deliberately not part of the `catalogue()` vocabulary there: these rows are
 * not derived from the books table, they change only when written, and
 * `tests/api/invalidate.test.ts` is where that classification is recorded.
 */
const BOOK_CUSTOM_FIELDS = /^\/api\/books\/\d+\/custom-fields$/;

/**
 * The library's own field definitions.
 *
 * Every write drops the list and every book's values with it: a renamed field
 * is the label a book draws, and a deleted one takes its values off every
 * book, so leaving those cached would show a name nobody uses any more.
 */
export function useCustomFields(): UseCustomFieldsResult {
  const queryClient = useQueryClient();
  const fields = useListCustomFields();

  const mutation = {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: getListCustomFieldsQueryKey(),
      });
      void queryClient.invalidateQueries({
        predicate: (query) => {
          const path = query.queryKey[0];
          return typeof path === "string" && BOOK_CUSTOM_FIELDS.test(path);
        },
      });
    },
  };

  const define = useDefineCustomField({ mutation });
  const rename = useRenameCustomField({ mutation });
  const remove = useDeleteCustomField({ mutation });

  return {
    fields: fields.data ?? [],
    define: (name, kind) => define.mutate({ data: { name, kind } }),
    rename: (fieldId, name) => rename.mutate({ fieldId, data: { name } }),
    remove: (fieldId) => remove.mutate({ fieldId }),
    isBusy: define.isPending || rename.isPending || remove.isPending,
    error: fields.error ?? define.error ?? rename.error ?? remove.error,
  };
}

/**
 * Taking a catalogue across from another library.
 *
 * The same two steps as `useLibraryImport` and for a sharper reason. A CSV
 * preview exists so a column guessed wrong can be corrected; MARC has no
 * columns to guess, so what the preview answers instead is "will this double
 * my catalogue". `already_held` is that answer, and it has to be visible
 * before the write rather than in the result afterwards.
 *
 * A separate hook rather than a mode on the one above, because the two write
 * different things: a CSV import writes the member's reading record and a MARC
 * import writes none at all. Sharing the state would mean one `result` object
 * whose `statuses_updated` means something on one path and nothing on the
 * other.
 */
export function useMarcImport() {
  const invalidate = useInvalidate();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<MarcPreviewOut | null>(null);
  const [result, setResult] = useState<ImportResultOut | null>(null);

  const previewing = usePreviewMarc({
    mutation: { onSuccess: (data: MarcPreviewOut) => setPreview(data) },
  });

  const importing = useImportMarc({
    mutation: {
      onSuccess: (data: ImportResultOut) => {
        setResult(data);
        setPreview(null);
        setFile(null);
        // Books, authors and classifications, so every catalogue view is
        // stale. Not the accounts or the settings: a MARC import writes
        // neither, and it writes no reading record either.
        invalidate.catalogue();
      },
    },
  });

  return {
    file,
    preview,
    result,

    // `mutate`, not `mutateAsync`: the failure is surfaced through `error`
    // rather than by rejecting a promise nobody is holding.
    choose: (chosen: File) => {
      setFile(chosen);
      setResult(null);
      importing.reset();
      previewing.mutate({ data: { file: chosen } });
    },

    confirm: (options: { createMissing: boolean }) => {
      if (!file) return;
      importing.mutate({
        data: { file },
        params: { create_missing: options.createMissing },
      });
    },

    isPreviewing: previewing.isPending,
    isImporting: importing.isPending,
    error: previewing.error ?? importing.error,

    reset: () => {
      setFile(null);
      setPreview(null);
      setResult(null);
      previewing.reset();
      importing.reset();
    },
  };
}

/**
 * The three names the Calibre card spells, over the shared shapes.
 *
 * Aliases rather than a rename: what the loop does is one thing for every
 * import on this page, and what this card calls it is the card's own
 * vocabulary. `./importing` is the one home of the behaviour.
 */
export type CalibreProgress = ImportProgress;
export type CalibreFailureRow = ImportFailureRow;
export type CalibreResult = ImportOutcome;

/** One row of the sample the preview shows, so a wrong reading is visible. */
export interface CalibrePreviewRow {
  readonly title: string;
  readonly author: string | null;
  readonly isbn: string | null;
}

/**
 * What the library turned out to hold, before anything is written.
 *
 * **The counts are the reason this screen exists.** A Calibre import is the
 * expensive route and it was chosen for the identifiers, so the number of books
 * carrying one is the fact that says whether it paid: a library reporting zero
 * ISBNs is a library that should have arrived through the feed.
 */
export interface CalibrePreview {
  readonly total: number;
  /** Books with a title, which is the one field the API requires. */
  readonly importable: number;
  readonly withIsbn: number;
  readonly withSeries: number;
  readonly withFile: number;
  /** Books that had a `metadata.opf` beside them and were checked against it. */
  readonly crossChecked: number;
  /** Fields the files supplied where the database had none. */
  readonly filled: number;
  /** Fields both carried, differently. The database kept its own. */
  readonly disagreed: number;
  readonly rows: readonly CalibrePreviewRow[];
}

/** Every way the pick can fail before there is a library to look at. */
export type CalibreIntakeFailure = CalibreFailure | SqliteFailure;

/** How many rows the preview samples. The same five the CSV preview shows. */
const PREVIEW_ROWS = 5;

/**
 * Bringing a Calibre library across, by the route that holds no lock on it.
 *
 * **The safety rule is the shape of this hook.** The household's library has
 * exactly one writer by design, and the member hands over a file the browser
 * cannot write back to: nothing here opens a library, takes a lock, or knows
 * where one is. `lib/sqlite.ts` carries the full statement at the site that
 * would have to break it.
 *
 * Two picks and the second is optional. The database is the primary route and
 * carries the identifiers this route was chosen for; the per book `metadata.opf`
 * is a cross check that fills what the database left empty. **They are two picks
 * rather than one folder** because a directory picker hands the browser every
 * book file as well, which on this library is nine hundred prompts worth of
 * dialog for a step that most imports do not need. Whoever wants the cross check
 * asks for it.
 *
 * Nothing is written until `confirm`, for `useLibraryImport`'s reason: a library
 * read wrong is invisible until afterwards, and afterwards the fix is finding
 * and deleting nine hundred books.
 */
export function useCalibreImport() {
  const invalidate = useInvalidate();
  const scanAdd = useScanAdd();

  const [books, setBooks] = useState<readonly CalibreBook[] | null>(null);
  const [preview, setPreview] = useState<CalibrePreview | null>(null);
  const [failure, setFailure] = useState<CalibreIntakeFailure | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [progress, setProgress] = useState<CalibreProgress | null>(null);
  const [isReading, setIsReading] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [result, setResult] = useState<CalibreResult | null>(null);
  // A ref rather than state: the loop below reads it between requests, and a
  // state value captured when the loop started would say `false` for ever.
  const stopped = useRef(false);

  function summarise(
    read: readonly CalibreBook[],
    crossChecked: number,
    filled: number,
    disagreed: number,
  ): CalibrePreview {
    return {
      total: read.length,
      importable: read.filter((book) => toBookCreate(book) !== null).length,
      withIsbn: read.filter((book) => book.isbn !== null).length,
      withSeries: read.filter((book) => book.seriesName !== null).length,
      withFile: read.filter((book) => book.formats.length > 0).length,
      crossChecked,
      filled,
      disagreed,
      rows: read.slice(0, PREVIEW_ROWS).map((book) => ({
        title: book.title ?? "",
        author: book.authors[0] ?? null,
        isbn: book.isbn,
      })),
    };
  }

  /**
   * Read the index, and report what it turned out to be.
   *
   * **The engine is imported here rather than at the top of the module**, so a
   * session that never opens this card never downloads a third of a megabyte of
   * WebAssembly. It is resolved once per pick; the module graph is cached after
   * the first await.
   */
  async function read(file: File) {
    setIsReading(true);
    setFailure(null);
    setError(null);
    setResult(null);
    setBooks(null);
    setPreview(null);
    try {
      const [{ openSqliteFile }, { readCalibreLibrary }] = await Promise.all([
        import("../../../lib/sqlite"),
        import("../../../lib/calibre"),
      ]);
      const opened = await openSqliteFile(file);
      if (!opened.ok) {
        setFailure(opened.failure);
        return;
      }
      try {
        const reading = readCalibreLibrary(opened.database);
        if (!reading.ok) {
          setFailure(reading.failure);
          return;
        }
        setBooks(reading.books);
        setPreview(summarise(reading.books, 0, 0, 0));
      } finally {
        // Always, including on the failure paths above: the engine holds the
        // whole file in WebAssembly memory until it is told not to.
        opened.database.close();
      }
    } catch (thrown) {
      setError(thrown);
    } finally {
      setIsReading(false);
    }
  }

  /**
   * Check what was read against the `metadata.opf` beside each book.
   *
   * **One file's failure is never the library's.** A file that is not a package
   * document, or that is larger than this will read, leaves that book with what
   * the database said, which is what the database being the primary route
   * means.
   */
  async function check(files: readonly File[]) {
    if (books === null) return;
    setIsReading(true);
    setError(null);
    try {
      const [{ indexOpfFiles, crossCheck, MAX_OPF_BYTES }, { readOpf }] =
        await Promise.all([
          import("../../../lib/calibre"),
          import("../../../lib/opf"),
        ]);
      const index = indexOpfFiles(files);

      /**
       * The package document beside one book, or `null` for every way there is
       * not one.
       *
       * **Its own `try`, because one file's failure is never the library's.**
       * The read can reject on its own: a file removed between the pick and the
       * pass, or a share that went away. Without this the throw reaches the
       * caller's catch and the whole cross check is lost, on a screen that then
       * says every book was left with what the index held.
       */
      async function readBeside(file: File | undefined) {
        if (file === undefined || file.size > MAX_OPF_BYTES) return null;
        try {
          return readOpf(await file.text());
        } catch {
          return null;
        }
      }

      const checked: CalibreBook[] = [];
      let crossChecked = 0;
      let filled = 0;
      let disagreed = 0;

      setProgress({ done: 0, total: books.length });
      for (const [position, book] of books.entries()) {
        const file = index.get(book.path.normalize("NFC"));
        const opf = await readBeside(file);
        if (opf === null) {
          checked.push(book);
        } else {
          const merged = crossCheck(book, opf);
          crossChecked += 1;
          filled += merged.filled;
          disagreed += merged.disagreed;
          checked.push(merged.book);
        }
        // Every fifty rather than every book: a set on each of nine hundred
        // iterations is nine hundred renders of a screen showing one number.
        if (position % 50 === 0) {
          setProgress({ done: position, total: books.length });
        }
      }

      setBooks(checked);
      setPreview(summarise(checked, crossChecked, filled, disagreed));
    } catch (thrown) {
      setError(thrown);
    } finally {
      setProgress(null);
      setIsReading(false);
    }
  }

  /** Write them, through the loop every import on this page shares. */
  async function confirm() {
    if (books === null || isImporting) return;
    stopped.current = false;
    setIsImporting(true);
    setResult(null);

    const bodies = books
      .map((book) => toBookCreate(book))
      .filter((body): body is NonNullable<typeof body> => body !== null);

    const outcome = await writeBooks(bodies, {
      post: (body) => scanAdd.mutateAsync({ data: body }),
      onProgress: setProgress,
      stopped: () => stopped.current,
    });

    // Once for the batch rather than once a book: nine hundred invalidations
    // would refetch every catalogue view nine hundred times.
    invalidate.catalogue();
    setProgress(null);
    setIsImporting(false);
    setResult(outcome);
    if (!outcome.stopped) {
      setBooks(null);
      setPreview(null);
    }
  }

  return {
    preview,
    result,
    failure,
    error,
    progress,
    isReading,
    isImporting,
    choose: (file: File) => void read(file),
    crossCheck: (files: readonly File[]) => void check(files),
    confirm: () => void confirm(),
    stop: () => {
      stopped.current = true;
    },
    reset: () => {
      stopped.current = false;
      setBooks(null);
      setPreview(null);
      setResult(null);
      setFailure(null);
      setError(null);
      setProgress(null);
    },
  };
}

/**
 * What one picked source is doing, or turned out to be.
 *
 * **Four states and not three**, and the fourth is the one this rule is for. A
 * reader answers a `StoreFailure` for everything a file can contain, so `error`
 * is a bug in a reader rather than a bad file; without it such a bug would have
 * to reject out of the read and take every other source with it, which is
 * exactly the failure "one skipped source, never a broken import" names.
 */
export type StoreSource =
  | { readonly status: "reading"; readonly fileName: string }
  | {
      readonly status: "read";
      readonly fileName: string;
      readonly library: StoreLibrary;
    }
  | {
      readonly status: "failed";
      readonly fileName: string;
      readonly failure: StoreFailure;
    }
  | {
      readonly status: "error";
      readonly fileName: string;
      readonly error: unknown;
    };

/**
 * The sources this member has picked, by store.
 *
 * `Partial` because most stores are not picked, `fileReaders.READERS`'s reason:
 * a total map would need an entry per store meaning "not chosen", which reads
 * as though the absent ones were an oversight.
 */
export type StoreSources = Partial<Record<StoreId, StoreSource>>;

/**
 * What the picked sources hold together, before anything is written.
 *
 * **Two numbers, and they are the two the confirm button asks for**: how many
 * books arrived and how many of them can be written. What each source held on
 * its own, including what it skipped and what it refused, is on that source's
 * own row, which is where a member reads which device a number came from. An
 * aggregate of those here would be a second home for a fact with no screen.
 */
export interface StorePreview {
  readonly total: number;
  /** Books with a title, which is the one field the API requires. */
  readonly importable: number;
}

/**
 * Importing from the stores a member's own devices and exports carry.
 *
 * **Several sources in one pass, and that is the shape of the rule.** A member
 * with a Kobo and a Play Books export picks both, and a file that has moved or
 * that a firmware update changed costs that one source: the others are read,
 * the totals are theirs, and the row that failed says which store it was and
 * why. `lib/stores.ts` carries the same statement at the seam it is enforced
 * at.
 *
 * Nothing is written until `confirm`, `useLibraryImport`'s reason: a library
 * read wrong is invisible until afterwards, and afterwards the fix is finding
 * and deleting the books it made.
 *
 * **Nothing is uploaded.** Every read happens in the browser, and the reader
 * modules that hold a member's bytes cannot reach the network at all.
 */
export function useStoreImport() {
  const invalidate = useInvalidate();
  const scanAdd = useScanAdd();

  const [sources, setSources] = useState<StoreSources>({});
  const [progress, setProgress] = useState<ImportProgress | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [result, setResult] = useState<ImportOutcome | null>(null);
  // A ref rather than state, `useCalibreImport`'s reason: the loop reads it
  // between requests, and a state value captured when it started says `false`
  // for ever.
  const stopped = useRef(false);
  /**
   * The pick each store's answer is owed to.
   *
   * **A read writes its answer only where the pick it came from is still the
   * current one.** Two picks for one store, or a pick and then a cancel, leave
   * a read running whose file the member has already replaced: without this it
   * lands whenever it finishes, so a slow first read overwrites the pick that
   * replaced it, and a read still running when an import finishes puts a
   * preview and an Import button back on a card that has just reported its
   * result. Identity rather than a counter, so nothing has to be reset.
   */
  const picks = useRef(new Map<StoreId, object>());

  /** Let go of every read in flight, so none of them writes after this. */
  function abandonReads() {
    picks.current.clear();
  }

  /**
   * Read one picked file, and report what it turned out to be.
   *
   * **Every update is functional**, because two sources can be reading at once:
   * a member picks a Kobo and an export in either order without waiting, and a
   * write built from a snapshot taken when this read started would drop the
   * other one's answer.
   */
  async function read(id: StoreId, file: File) {
    const pick = {};
    picks.current.set(id, pick);
    setResult(null);
    setSources((current) => ({
      ...current,
      [id]: { status: "reading", fileName: file.name },
    }));

    let answer: StoreSource;
    try {
      const reading = await STORES[id].open(file);
      answer = reading.ok
        ? { status: "read", fileName: file.name, library: reading.library }
        : { status: "failed", fileName: file.name, failure: reading.failure };
    } catch (thrown) {
      // A reader answers rather than throws, so reaching here is a bug in one.
      // It still costs one source: see `StoreSource`.
      answer = { status: "error", fileName: file.name, error: thrown };
    }

    // **What the read found is decided first and written once**, so that the
    // check below is one site rather than one per outcome. Written per outcome
    // it was two arms of an open set, and only the arm somebody thought to
    // test was tested: a reader that throws is the case least likely to be
    // noticed in the wild and was the one arm no test reached.
    if (picks.current.get(id) !== pick) return;
    setSources((current) => ({ ...current, [id]: answer }));
  }

  /** Every book that read, in the order the stores are offered. */
  function readBooks(): readonly StoreBookFromSource[] {
    return STORE_IDS.flatMap((id) => {
      const source = sources[id];
      if (source?.status !== "read") return [];
      // **Paired with its source's ownership claim rather than flattened away.**
      // Whether a store established ownership is a fact about the read, and this
      // is the one place several reads become one list: dropping it here is what
      // made every store import write `owned`, a library loan included.
      const { ownershipStated } = source.library;
      return source.library.books.map((book) => ({ book, ownershipStated }));
    });
  }

  /**
   * What the sources that read hold together.
   *
   * **Memoised on `sources`, and it is not a micro optimisation.**
   * `importable` is counted by building a `BookCreate` per book, so on a device
   * holding nine hundred of them this is nine hundred objects. Recomputed every
   * render it would run again on each of the progress updates the write loop
   * makes, which is where a member is least able to afford it.
   */
  const preview = useMemo<StorePreview | null>(() => {
    const read = STORE_IDS.map((id) => sources[id]).filter(
      (source): source is Extract<StoreSource, { status: "read" }> =>
        source?.status === "read",
    );
    if (read.length === 0) return null;
    const books = read.flatMap((source) => [...source.library.books]);
    return {
      total: books.length,
      // The ownership flag does not change whether a book is importable, which
      // turns on a title, so the cheaper call is right here.
      importable: books.filter((book) => storeToBookCreate(book, true) !== null)
        .length,
    };
  }, [sources]);

  /** Write them, through the loop every import on this page shares. */
  async function confirm() {
    if (isImporting) return;
    stopped.current = false;
    setIsImporting(true);
    setResult(null);

    const bodies = readBooks()
      .map(({ book, ownershipStated }) =>
        storeToBookCreate(book, ownershipStated),
      )
      .filter((body): body is NonNullable<typeof body> => body !== null);

    const outcome = await writeBooks(bodies, {
      post: (body) => scanAdd.mutateAsync({ data: body }),
      onProgress: setProgress,
      stopped: () => stopped.current,
    });

    // Once for the batch rather than once a book.
    invalidate.catalogue();
    setProgress(null);
    setIsImporting(false);
    setResult(outcome);
    // **The sources are kept when the member stopped, and pressing Import again
    // starts over rather than carrying on.** Every book is sent a second time
    // and the ones already in answer 409, which the result names as duplicates;
    // resuming where it stopped is a different ticket. They are kept so that
    // pressing again does not mean picking the file a second time.
    if (!outcome.stopped) {
      abandonReads();
      setSources({});
    }
  }

  return {
    sources,
    preview,
    progress,
    result,
    isReading: STORE_IDS.some((id) => sources[id]?.status === "reading"),
    isImporting,
    choose: (id: StoreId, file: File) => void read(id, file),
    confirm: () => void confirm(),
    stop: () => {
      stopped.current = true;
    },
    reset: () => {
      stopped.current = false;
      abandonReads();
      setSources({});
      setResult(null);
      setProgress(null);
    },
  };
}
