import { useState } from "react";

import type {
  ImportResultOut,
  ImportPreviewOut,
} from "../../../../api/generated/model";
import { useTranslation } from "../../../../i18n";
import {
  ConfirmRow,
  FilePicker,
  ImportError,
  ResultPanel,
  ReviewAdded,
} from "./ImportChrome";
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
 * Dumb: it owns the two checkboxes, and draws the picker, the row and the
 * panels from `./ImportChrome`. The mutations, the cache invalidation and the
 * results live in the page's hooks.
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

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("import.explain")}
      </p>

      <FilePicker
        accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values"
        label={t("import.chooseFile")}
        busy={isPreviewing}
        busyLabel={t("import.reading")}
        offered={!preview}
        onFile={onChoose}
      />

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

          <ConfirmRow
            isImporting={isImporting}
            withheld={preview.total_rows === 0}
            confirmLabel={t("import.confirm", { count: preview.total_rows })}
            importingLabel={t("import.importing")}
            onConfirm={() => onConfirm({ createMissing, applyTags })}
            onCancel={onCancel}
          />
        </>
      )}

      <ImportError error={error} />

      {result && (
        <ResultPanel>
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
          {/* Said here as well as on the preview, and in the past tense,
              because the preview is cleared the moment the import succeeds and
              this is the point at which the number is a fact. A member who
              exported 400 titles and imported 380 is owed the other twenty. */}
          {(result.excluded ?? 0) > 0 && (
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("import.excludedResult", { count: result.excluded ?? 0 })}
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
          <ReviewAdded added={result.created} onReview={onReviewUnconfirmed} />
        </ResultPanel>
      )}
    </div>
  );
}
