import { useRef, useState } from "react";

import type {
  ImportResultOut,
  ImportPreviewOut,
} from "../../../api/generated/model";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";
import ImportPreview from "./ImportPreview";

interface LibraryImportProps {
  isPreviewing: boolean;
  isImporting: boolean;
  /** What the file turned out to be. Shown before anything is written. */
  preview: ImportPreviewOut | null;
  result: ImportResultOut | null;
  /** Whatever the upload rejected with, rendered through the shared reader. */
  error: unknown;
  onChoose: (file: File) => void;
  onConfirm: (options: { createMissing: boolean; applyTags: boolean }) => void;
  onCancel: () => void;
  /** Offered after an import that added books, which arrive unconfirmed. */
  onReviewUnconfirmed: () => void;
}

/**
 * Bringing a library across from another service.
 *
 * Two steps, and the first is the point: a column guessed wrong is invisible
 * until after the import, and after the import the fix is finding and deleting
 * a few hundred books. So the file is read and reported on first, and nothing
 * is written until somebody has looked at it.
 *
 * Dumb: it owns the file input and the two checkboxes. The mutations, the
 * cache invalidation and the results live in the page's hooks.
 */
export default function LibraryImport({
  isPreviewing,
  isImporting,
  preview,
  result,
  error,
  onChoose,
  onConfirm,
  onCancel,
  onReviewUnconfirmed,
}: LibraryImportProps) {
  const { t } = useTranslation();
  const [createMissing, setCreateMissing] = useState(true);
  const [applyTags, setApplyTags] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("import.explain")}
      </p>

      <input
        ref={fileInput}
        type="file"
        accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values"
        // Visually hidden but still in the tree, so it stays reachable by
        // keyboard and announced by name rather than as an unlabelled input.
        aria-label={t("import.chooseFile")}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onChoose(file);
          // Reset, so choosing the same file twice fires change again.
          event.target.value = "";
        }}
      />
      {!preview && (
        <button
          type="button"
          disabled={isPreviewing}
          onClick={() => fileInput.current?.click()}
          className="w-full py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 transition-colors dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
        >
          {isPreviewing ? t("import.reading") : t("import.chooseFile")}
        </button>
      )}

      {preview && (
        <>
          <ImportPreview preview={preview} />

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={createMissing}
              onChange={(event) => setCreateMissing(event.target.checked)}
              className="rounded border-paper-300 text-accent-700 dark:text-accent-400"
            />
            <span className="text-sm text-paper-700 dark:text-paper-200">
              {t("import.createMissing")}
            </span>
          </label>
          {createMissing && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
              {t("import.createMissingHint")}
            </p>
          )}

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={applyTags}
              onChange={(event) => setApplyTags(event.target.checked)}
              className="rounded border-paper-300 text-accent-700 dark:text-accent-400"
            />
            <span className="text-sm text-paper-700 dark:text-paper-200">
              {t("import.applyTags")}
            </span>
          </label>
          {/* Off by default and warned about: a Goodreads export's tag column
              is its shelves, which for most people is a few hundred one-off
              names that would bury the curated list. */}
          {applyTags && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
              {t("import.applyTagsHint", {
                count: preview.distinct_tags ?? 0,
              })}
            </p>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={onCancel}
              disabled={isImporting}
              className="flex-1 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              disabled={isImporting || preview.total_rows === 0}
              onClick={() => onConfirm({ createMissing, applyTags })}
              className="flex-1 py-2.5 rounded-xl bg-accent-fill text-sm font-semibold text-on-accent hover:bg-accent-fill-hover disabled:bg-accent-300"
            >
              {isImporting
                ? t("import.importing")
                : t("import.confirm", { count: preview.total_rows })}
            </button>
          </div>
        </>
      )}

      {error != null && (
        <p
          role="alert"
          className="text-sm text-danger-600 dark:text-danger-300"
        >
          {errorText(error, t("common.somethingWentWrong"), t)}
        </p>
      )}

      {result && (
        <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-2 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
          <p>
            {t("import.result", {
              rowsRead: result.rows_read,
              matched: result.matched,
              created: result.created,
              statusesUpdated: result.statuses_updated,
            })}
          </p>
          {result.skipped > 0 && (
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("import.skipped", { count: result.skipped })}
            </p>
          )}
          {result.unmatched_titles && result.unmatched_titles.length > 0 && (
            <div className="text-xs text-paper-600 dark:text-paper-400">
              <p className="font-medium">{t("import.unmatched")}</p>
              <ul className="list-disc list-inside mt-1 space-y-0.5">
                {result.unmatched_titles.map((title) => (
                  <li key={title}>{title}</li>
                ))}
              </ul>
            </div>
          )}
          {result.created > 0 && (
            <button
              type="button"
              onClick={onReviewUnconfirmed}
              className="text-sm font-medium text-accent-700 hover:text-accent-800 dark:text-accent-400 dark:hover:text-accent-300"
            >
              {t("ownership.reviewThem")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
