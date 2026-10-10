import { useState } from "react";

import type {
  ImportResultOut,
  MarcPreviewOut,
} from "../../../../api/generated/model";
import { useTranslation } from "../../../../i18n";
import {
  ConfirmRow,
  FilePicker,
  ImportError,
  ResultPanel,
  ReviewAdded,
} from "./ImportChrome";

interface MarcImportProps {
  isPreviewing: boolean;
  isImporting: boolean;
  /** What the file turned out to hold. Shown before anything is written. */
  preview: MarcPreviewOut | null;
  result: ImportResultOut | null;
  /** Whatever the upload rejected with, rendered through the shared reader. */
  error: unknown;
  onChoose: (file: File) => void;
  onConfirm: (options: { createMissing: boolean }) => void;
  onCancel: () => void;
  /** Offered after an import that added records, which arrive unconfirmed. */
  onReviewUnconfirmed: () => void;
}

/**
 * Taking a catalogue across from another library.
 *
 * **The number this screen exists for is `already_held`.** Importing the same
 * file twice is the ordinary accident in a catalogue transfer, and the fix
 * afterwards is finding and deleting several hundred records. So the count of
 * what is already on this shelf is shown before the write, next to the count of
 * what would be added.
 *
 * Dumb: it owns the one checkbox, and draws the picker, the row and the panels
 * from `./ImportChrome`. The mutations, the cache invalidation and the results
 * live in the page's hooks.
 */
export default function MarcImport({
  isPreviewing,
  isImporting,
  preview,
  result,
  error,
  onChoose,
  onConfirm,
  onCancel,
  onReviewUnconfirmed,
}: MarcImportProps) {
  const { t } = useTranslation();
  // Defaulted on, where the CSV importer defaults it off. A reading history is
  // mostly books the household does not own; a catalogue transfer that adds no
  // records has transferred nothing.
  const [createMissing, setCreateMissing] = useState(true);

  // **Both refusals, not one.** A record already held is filled in rather than
  // added; a record whose ISBN belongs to a book this account cannot see is
  // refused outright. Counting only the first promised records the import then
  // refused, by exactly the number another member holds privately.
  const wouldBeAdded = preview
    ? preview.readable - preview.already_held - (preview.blocked ?? 0)
    : 0;

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("marc.explain")}
      </p>

      <FilePicker
        accept=".xml,.marcxml,application/marcxml+xml,text/xml,application/xml"
        label={t("marc.chooseFile")}
        busy={isPreviewing}
        busyLabel={t("marc.reading")}
        offered={!preview}
        onFile={onChoose}
      />

      {preview && (
        <>
          <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-1 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
            <p>
              {t("marc.previewTitle", {
                total: preview.total_records,
                readable: preview.readable,
              })}
            </p>
            {preview.already_held > 0 && (
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("marc.alreadyHeld", { count: preview.already_held })}
              </p>
            )}
            {(preview.blocked ?? 0) > 0 && (
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("marc.blocked", { count: preview.blocked ?? 0 })}
              </p>
            )}
            {preview.skipped > 0 && (
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("marc.skipped", { count: preview.skipped })}
              </p>
            )}
            {(preview.rows ?? []).length > 0 && (
              <ul className="text-xs text-paper-600 mt-1 space-y-0.5 dark:text-paper-400">
                {(preview.rows ?? []).map((row, index) => (
                  <li key={`${row.title}-${index}`}>
                    {row.title}
                    {row.author ? ` · ${row.author}` : ""}
                    {(row.classifications ?? []).length > 0
                      ? ` · ${(row.classifications ?? []).join(", ")}`
                      : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={createMissing}
              onChange={(event) => setCreateMissing(event.target.checked)}
              className="rounded border-paper-300 text-accent-700 dark:text-accent-400"
            />
            <span className="text-sm text-paper-700 dark:text-paper-200">
              {t("marc.createMissing", { count: wouldBeAdded })}
            </span>
          </label>
          {createMissing && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
              {t("marc.createMissingHint")}
            </p>
          )}

          <ConfirmRow
            isImporting={isImporting}
            withheld={
              createMissing
                ? wouldBeAdded + preview.already_held === 0
                : preview.already_held === 0
            }
            // The count follows the switch. With it off nothing is created
            // and only the held records are filled in, so naming the whole
            // file there promised an import that would not happen.
            confirmLabel={
              createMissing
                ? t("marc.confirm", {
                    count: wouldBeAdded + preview.already_held,
                  })
                : t("marc.confirmMatchedOnly", {
                    count: preview.already_held,
                  })
            }
            importingLabel={t("marc.importing")}
            onConfirm={() => onConfirm({ createMissing })}
            onCancel={onCancel}
          />
        </>
      )}

      <ImportError error={error} />

      {result && (
        <ResultPanel>
          <p>
            {t("marc.result", {
              rowsRead: result.rows_read,
              matched: result.matched,
              created: result.created,
            })}
          </p>
          {result.skipped > 0 && (
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("marc.resultSkipped", { count: result.skipped })}
            </p>
          )}
          <ReviewAdded added={result.created} onReview={onReviewUnconfirmed} />
        </ResultPanel>
      )}
    </div>
  );
}
