import { useRef } from "react";

import { useTranslation, type MessageKey } from "../../../../i18n";
import type {
  CalibreIntakeFailure,
  CalibrePreview,
  CalibreProgress,
  CalibreResult,
} from "../hooks";
import {
  ConfirmRow,
  FilePicker,
  ImportAlert,
  ImportError,
  OutcomePanel,
  type OutcomeMessages,
} from "./ImportChrome";

interface CalibreImportProps {
  isReading: boolean;
  isImporting: boolean;
  /** What the library turned out to hold. Shown before anything is written. */
  preview: CalibrePreview | null;
  progress: CalibreProgress | null;
  result: CalibreResult | null;
  /** Why the file yielded no library, in the closed vocabulary the readers use. */
  failure: CalibreIntakeFailure | null;
  /** Anything else that was thrown, rendered through the shared reader. */
  error: unknown;
  onChoose: (file: File) => void;
  onCrossCheck: (files: readonly File[]) => void;
  onConfirm: () => void;
  onStop: () => void;
  onCancel: () => void;
}

/**
 * Bringing a Calibre library across.
 *
 * **The first thing on this card is the safety rule**, and it is there rather
 * than in a document because the member is the one who can break it: a Calibre
 * library has exactly one writer, and the way to read one is to copy the index
 * out and point this at the copy. Nothing here can enforce that, so it says it
 * where the decision is made. What this app can guarantee it does guarantee, in
 * `lib/sqlite.ts`: a picked file is a snapshot the page cannot write back to,
 * and a copy taken mid write is refused rather than read.
 *
 * **The counts are the screen.** This route was chosen over the network one for
 * the identifiers it carries, so the number of books carrying one is what says
 * whether the choice paid on this library. A library reporting no ISBNs is one
 * that should have arrived through the feed.
 *
 * Dumb: it holds the cross check's folder input and nothing else; the file
 * picker, the row and the panels are `./ImportChrome`'s. The reading, the cross
 * check and the writes live in the page's hooks.
 */
export default function CalibreImport({
  isReading,
  isImporting,
  preview,
  progress,
  result,
  failure,
  error,
  onChoose,
  onCrossCheck,
  onConfirm,
  onStop,
  onCancel,
}: CalibreImportProps) {
  const { t } = useTranslation();
  const folderInput = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("calibre.explain")}
      </p>
      <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
        {t("calibre.safety")}
      </p>

      <FilePicker
        accept=".db,application/vnd.sqlite3,application/x-sqlite3"
        label={t("calibre.chooseFile")}
        busy={isReading}
        busyLabel={t("calibre.reading")}
        offered={!preview}
        onFile={onChoose}
      />
      <input
        ref={(node) => {
          // The cross check button clicks `folderInput`, and this callback is
          // the input's only ref, so it fills that itself: without this line
          // the button clicks nothing.
          folderInput.current = node;
          // `webkitdirectory` is set here rather than written as a prop: it is
          // not in React's attribute table, so the prop spelling either fails
          // the type check or is dropped depending on the version, and both
          // failures are a picker that quietly offers one file.
          if (node) node.setAttribute("webkitdirectory", "");
        }}
        type="file"
        multiple
        aria-label={t("calibre.crossCheck")}
        className="sr-only"
        // Its button's state: absent before a library is read and while the
        // import runs, disabled while reading. Left enabled, a keyboard reaches
        // it where a pointer cannot, and starts a cross check under a running
        // write.
        disabled={!preview || isImporting || isReading}
        onChange={(event) => {
          const files = [...(event.target.files ?? [])];
          event.target.value = "";
          if (files.length > 0) onCrossCheck(files);
        }}
      />

      {failure && <ImportAlert>{t(FAILURE_MESSAGES[failure])}</ImportAlert>}

      {preview && (
        <>
          <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-1 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
            <p>
              {t("calibre.previewTitle", {
                total: preview.total,
                importable: preview.importable,
              })}
            </p>
            {/* Said at zero as well, deliberately. This is the number the route
                was chosen for, and a count shown only when it is above zero
                cannot be told apart from a screen that never counted. */}
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("calibre.withIsbn", { count: preview.withIsbn })}
            </p>
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("calibre.withSeries", { count: preview.withSeries })}
            </p>
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("calibre.withFile", { count: preview.withFile })}
            </p>
            {preview.crossChecked > 0 && (
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("calibre.crossCheckResult", {
                  checked: preview.crossChecked,
                  filled: preview.filled,
                  disagreed: preview.disagreed,
                })}
              </p>
            )}
            {preview.rows.length > 0 && (
              <ul className="text-xs text-paper-600 mt-1 space-y-0.5 dark:text-paper-400">
                {preview.rows.map((row, index) => (
                  // The index keys these: a title is not a key, and a library
                  // holding two copies of one book is ordinary.
                  <li key={index} className="truncate">
                    {row.title}
                    {row.author ? ` · ${row.author}` : ""}
                    {row.isbn ? ` · ${row.isbn}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {!isImporting && (
            <>
              <button
                type="button"
                disabled={isReading}
                onClick={() => folderInput.current?.click()}
                className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
              >
                {t("calibre.crossCheck")}
              </button>
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("calibre.crossCheckHint")}
              </p>
            </>
          )}

          {progress && (
            <p
              role="status"
              className="text-xs text-paper-600 dark:text-paper-400"
            >
              {t("calibre.progress", {
                done: progress.done,
                total: progress.total,
              })}
            </p>
          )}

          <ConfirmRow
            isImporting={isImporting}
            withheld={isReading || preview.importable === 0}
            confirmLabel={t("calibre.confirm", { count: preview.importable })}
            importingLabel={t("calibre.importing")}
            onConfirm={onConfirm}
            onCancel={onCancel}
            stop={{ label: t("calibre.stop"), onStop }}
          />
        </>
      )}

      <ImportError error={error} />

      {result && <OutcomePanel outcome={result} messages={OUTCOME_MESSAGES} />}
    </div>
  );
}

/**
 * One sentence per refusal.
 *
 * A `Record` rather than a switch, so a failure added to either closed union is
 * a type error here rather than a member being shown nothing.
 */
const FAILURE_MESSAGES: Record<CalibreIntakeFailure, MessageKey> = {
  "not-a-database": "calibre.failureNotADatabase",
  damaged: "calibre.failureDamaged",
  "too-large": "calibre.failureTooLarge",
  "no-engine": "calibre.failureNoEngine",
  "not-a-calibre-library": "calibre.failureNotCalibre",
  empty: "calibre.failureEmpty",
};

/** The outcome panel's sentences, in this card's words. */
const OUTCOME_MESSAGES: OutcomeMessages = {
  result: "calibre.result",
  resultStopped: "calibre.resultStopped",
  resultFailures: "calibre.resultFailures",
  duplicate: "calibre.duplicate",
  notAdded: "calibre.notAdded",
};
