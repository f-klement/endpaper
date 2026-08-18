import { useRef, useState } from "react";

import type { GoodreadsImportOut } from "../../../api/generated/model";
import { errorText } from "../../../components/ErrorState";
import { useTranslation } from "../../../i18n";

interface GoodreadsImportProps {
  isUploading: boolean;
  result: GoodreadsImportOut | null;
  /** Whatever the upload rejected with, rendered through the shared reader. */
  error: unknown;
  onUpload: (file: File, createMissing: boolean) => void;
  /** Offered after an import that added books, which arrive unconfirmed. */
  onReviewUnconfirmed: () => void;
}

/**
 * Uploading a Goodreads CSV export.
 *
 * Dumb: it owns the file input and the create-missing checkbox, and hands the
 * chosen file upwards. The mutation, the cache invalidation and the result
 * live in the page's hooks.
 */
export default function GoodreadsImport({
  isUploading,
  result,
  error,
  onUpload,
  onReviewUnconfirmed,
}: GoodreadsImportProps) {
  const { t } = useTranslation();
  const [createMissing, setCreateMissing] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500 leading-relaxed dark:text-gray-400">
        {t("goodreads.importExplain")}
      </p>

      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={createMissing}
          onChange={(event) => setCreateMissing(event.target.checked)}
          className="rounded border-gray-300 text-sky-600 focus:ring-sky-400 dark:text-sky-400"
        />
        <span className="text-sm text-gray-700 dark:text-gray-200">
          {t("goodreads.createMissing")}
        </span>
      </label>
      {createMissing && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
          {t("goodreads.createMissingHint")}
        </p>
      )}

      <input
        ref={fileInput}
        type="file"
        accept=".csv,text/csv"
        // Visually hidden but still in the tree, so it stays reachable by
        // keyboard and announced by name rather than as an unlabelled input.
        aria-label={t("goodreads.chooseFile")}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onUpload(file, createMissing);
          // Reset, so choosing the same file twice fires change again.
          event.target.value = "";
        }}
      />
      <button
        type="button"
        disabled={isUploading}
        onClick={() => fileInput.current?.click()}
        className="w-full py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
      >
        {isUploading ? t("goodreads.importing") : t("goodreads.chooseFile")}
      </button>

      {error != null && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {errorText(error, t("common.somethingWentWrong"))}
        </p>
      )}

      {result && (
        <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3 space-y-2 dark:text-gray-200 dark:bg-gray-900 dark:border-gray-700">
          <p>
            {t("goodreads.result", {
              rowsRead: result.rows_read,
              matched: result.matched,
              created: result.created,
              statusesUpdated: result.statuses_updated,
            })}
          </p>
          {result.skipped > 0 && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {t("goodreads.skipped", { count: result.skipped })}
            </p>
          )}
          {result.unmatched_titles && result.unmatched_titles.length > 0 && (
            <div className="text-xs text-gray-500 dark:text-gray-400">
              <p className="font-medium">{t("goodreads.unmatched")}</p>
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
              className="text-sm font-medium text-sky-600 hover:text-sky-700 dark:text-sky-400"
            >
              {t("ownership.reviewThem")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
