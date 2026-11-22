import { useState } from "react";

import type {
  ImportResultOut,
  MarcPreviewOut,
} from "../../../../api/generated/model";
import { type MessageKey, useTranslation } from "../../../../i18n";
import {
  ConfirmRow,
  FilePicker,
  ImportError,
  RecordRows,
  ResultPanel,
  ReviewAdded,
  TitleList,
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
  // records has transferred nothing. Held here rather than in the preview step,
  // so a cancelled preview and the next file keep the choice.
  const [createMissing, setCreateMissing] = useState(true);

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
        <PreviewStep
          preview={preview}
          createMissing={createMissing}
          onCreateMissing={setCreateMissing}
          isImporting={isImporting}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )}

      <ImportError error={error} />

      {result && (
        <MarcResult result={result} onReviewUnconfirmed={onReviewUnconfirmed} />
      )}
    </div>
  );
}

/**
 * **Every record the import does not add, not one kind of it.** A record
 * already held is filled in rather than added; one whose ISBN belongs to a book
 * this account cannot see is refused, one whose ISBN only the trash holds waits
 * for it, and one two books answer is left alone. Counting only the first
 * promised records the import then refused, by exactly the number another
 * member holds privately.
 *
 * Exported for the harvest card, whose preview carries the same counts over
 * harvested records: one formula, so the two cards cannot promise different
 * numbers for the same records.
 */
export function wouldBeAddedBy(
  preview: Pick<
    MarcPreviewOut,
    "readable" | "already_held" | "blocked" | "in_trash" | "ambiguous"
  >,
): number {
  return (
    preview.readable -
    preview.already_held -
    (preview.blocked ?? 0) -
    (preview.in_trash ?? 0) -
    (preview.ambiguous ?? 0)
  );
}

/** The counts, the add switch and the confirm row, once a file is read. */
function PreviewStep({
  preview,
  createMissing,
  onCreateMissing,
  isImporting,
  onConfirm,
  onCancel,
}: {
  preview: MarcPreviewOut;
  createMissing: boolean;
  onCreateMissing: (createMissing: boolean) => void;
  isImporting: boolean;
  onConfirm: MarcImportProps["onConfirm"];
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const wouldBeAdded = wouldBeAddedBy(preview);
  // The count follows the switch. With it off nothing is created and only the
  // held records are filled in, so naming the whole file there promised an
  // import that would not happen.
  const toImport = createMissing
    ? wouldBeAdded + preview.already_held
    : preview.already_held;

  return (
    <>
      <PreviewCounts preview={preview} />

      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={createMissing}
          onChange={(event) => onCreateMissing(event.target.checked)}
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
        withheld={toImport === 0}
        confirmLabel={t(
          createMissing ? "marc.confirm" : "marc.confirmMatchedOnly",
          { count: toImport },
        )}
        importingLabel={t("marc.importing")}
        onConfirm={() => onConfirm({ createMissing })}
        onCancel={onCancel}
      />
    </>
  );
}

/** What the file holds, before anything is written. */
function PreviewCounts({ preview }: { preview: MarcPreviewOut }) {
  const { t } = useTranslation();
  const counts: [MessageKey, number][] = [
    ["marc.alreadyHeld", preview.already_held],
    ["marc.blocked", preview.blocked ?? 0],
    ["marc.inTrash", preview.in_trash ?? 0],
    ["marc.ambiguous", preview.ambiguous ?? 0],
    ["marc.skipped", preview.skipped],
  ];

  return (
    <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-1 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
      <p>
        {t("marc.previewTitle", {
          total: preview.total_records,
          readable: preview.readable,
        })}
      </p>
      {counts
        .filter(([, count]) => count > 0)
        .map(([key, count]) => (
          <p key={key} className="text-xs text-paper-600 dark:text-paper-400">
            {t(key, { count })}
          </p>
        ))}
      <RecordRows rows={preview.rows ?? []} />
    </div>
  );
}

function MarcResult({
  result,
  onReviewUnconfirmed,
}: {
  result: ImportResultOut;
  onReviewUnconfirmed: () => void;
}) {
  const { t } = useTranslation();
  return (
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
      <TitleList
        heading={t("marc.resultInTrash", { count: result.in_trash ?? 0 })}
        titles={result.in_trash_titles}
      />
      <TitleList
        heading={t("marc.resultAmbiguous", { count: result.ambiguous ?? 0 })}
        titles={result.ambiguous_titles}
      />
      <ReviewAdded added={result.created} onReview={onReviewUnconfirmed} />
    </ResultPanel>
  );
}
