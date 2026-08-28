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
import { useState } from "react";

import {
  getListCustomFieldsQueryKey,
  useBackfillCovers,
  useDefineCustomField,
  useDeleteCustomField,
  useListCustomFields,
  useRenameCustomField,
} from "../../../api/generated/endpoints/books/books";
import {
  useImportCsv,
  usePreviewImport,
} from "../../../api/generated/endpoints/imports/imports";
import type {
  CoverBackfillOut,
  CustomFieldKind,
  CustomFieldOut,
  ImportPreviewOut,
  ImportResultOut,
} from "../../../api/generated/model";
import { useInvalidate } from "../../../api/invalidate";

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
