import { useRef, useState } from "react";

import type {
  ImportResultOut,
  MarcPreviewOut,
} from "../../../../api/generated/model";
import { errorText } from "../../../../components/ErrorState";
import { useTranslation } from "../../../../i18n";

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
 * Dumb: it owns the file input and the one checkbox. The mutations, the cache
 * invalidation and the results live in the page's hooks.
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
  const fileInput = useRef<HTMLInputElement>(null);

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

      <input
        ref={fileInput}
        type="file"
        accept=".xml,.marcxml,application/marcxml+xml,text/xml,application/xml"
        // Visually hidden but still in the tree, so it stays reachable by
        // keyboard and announced by name rather than as an unlabelled input.
        aria-label={t("marc.chooseFile")}
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
          {isPreviewing ? t("marc.reading") : t("marc.chooseFile")}
        </button>
      )}

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
              disabled={
                isImporting ||
                (createMissing
                  ? wouldBeAdded + preview.already_held === 0
                  : preview.already_held === 0)
              }
              onClick={() => onConfirm({ createMissing })}
              className="flex-1 py-2.5 rounded-xl bg-accent-fill text-sm font-semibold text-on-accent hover:bg-accent-fill-hover disabled:bg-accent-300"
            >
              {/* The count follows the switch. With it off nothing is created
                  and only the held records are filled in, so naming the whole
                  file there promised an import that would not happen. */}
              {isImporting
                ? t("marc.importing")
                : createMissing
                  ? t("marc.confirm", {
                      count: wouldBeAdded + preview.already_held,
                    })
                  : t("marc.confirmMatchedOnly", {
                      count: preview.already_held,
                    })}
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
