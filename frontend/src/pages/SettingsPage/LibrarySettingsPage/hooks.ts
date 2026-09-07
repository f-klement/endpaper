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
import { useRef, useState } from "react";

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
import { toBookCreate } from "./types";

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

/** How far through a step that walks nine hundred things this one is. */
export interface CalibreProgress {
  readonly done: number;
  readonly total: number;
}

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

/** What one book that could not be added was, and what the server answered. */
export interface CalibreFailureRow {
  readonly title: string;
  /** The HTTP status, or `null` when the request never got one. */
  readonly status: number | null;
}

export interface CalibreResult {
  readonly added: number;
  readonly failures: readonly CalibreFailureRow[];
  /** True when the member stopped it, so a short count is not read as damage. */
  readonly stopped: boolean;
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

  /**
   * Write them, one request each.
   *
   * **Sequential rather than `Promise.all`**, for the reason the rapid queue
   * states: nine hundred concurrent requests against one SQLite writer is not a
   * faster import, and a duplicate ISBN answering 409 has to be attributable to
   * a book.
   *
   * **A failure is kept with its reason rather than counted.** "Sixty could not
   * be added" after a nine hundred book import is unrecoverable: nothing says
   * which sixty.
   */
  async function confirm() {
    if (books === null || isImporting) return;
    stopped.current = false;
    setIsImporting(true);
    setResult(null);
    const failures: CalibreFailureRow[] = [];
    let added = 0;

    const wanted = books
      .map((book) => ({ book, body: toBookCreate(book) }))
      .filter(
        (
          one,
        ): one is { book: CalibreBook; body: NonNullable<typeof one.body> } =>
          one.body !== null,
      );

    setProgress({ done: 0, total: wanted.length });
    for (const [position, one] of wanted.entries()) {
      if (stopped.current) break;
      try {
        await scanAdd.mutateAsync({ data: one.body });
        added += 1;
      } catch (thrown) {
        failures.push({ title: one.body.title, status: statusOf(thrown) });
      }
      setProgress({ done: position + 1, total: wanted.length });
    }

    // Once for the batch rather than once a book: nine hundred invalidations
    // would refetch every catalogue view nine hundred times.
    invalidate.catalogue();
    setProgress(null);
    setIsImporting(false);
    setResult({ added, failures, stopped: stopped.current });
    if (!stopped.current) {
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
 * What the server answered for one book, or `null` when it never answered.
 *
 * The status rather than the sentence, and the sentence is built where the
 * catalogue is: a duplicate ISBN is the ordinary outcome of importing the same
 * library twice and is worth its own words, where everything else is one line
 * saying which book did not arrive.
 */
function statusOf(thrown: unknown): number | null {
  const status = (thrown as { status?: unknown } | null)?.status;
  return typeof status === "number" ? status : null;
}
