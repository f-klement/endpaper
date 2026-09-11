import { useRef } from "react";

import { errorText } from "../../../../components/ErrorState";
import { useTranslation, type MessageKey } from "../../../../i18n";
import {
  STORES,
  STORE_IDS,
  type StoreFailure,
  type StoreId,
} from "../../../../lib/stores";
import type { StorePreview, StoreSources } from "../hooks";
import {
  DUPLICATE_STATUS,
  FAILURES_SHOWN,
  type ImportOutcome,
  type ImportProgress,
} from "../importing";

interface StoreImportProps {
  /** What each picked source is doing, or turned out to be. */
  sources: StoreSources;
  /** What the sources that read hold together. `null` until one has. */
  preview: StorePreview | null;
  progress: ImportProgress | null;
  result: ImportOutcome | null;
  isReading: boolean;
  isImporting: boolean;
  onChoose: (id: StoreId, file: File) => void;
  onConfirm: () => void;
  onStop: () => void;
  onCancel: () => void;
}

/**
 * Bringing a library across from a device or a store's own export.
 *
 * **One card with a row per store, rather than a card per store.** The rule it
 * exists to make visible is about several sources at once: a member with a Kobo
 * and a Play Books export picks both here, and a source that cannot be read
 * costs that source and nothing else. Split into separate cards there would be
 * nowhere for "this one was skipped and the rest arrived" to be said.
 *
 * **The rows are drawn from `lib/stores.ts` and nothing here names a store.**
 * A store added there appears with its own sentence, its own picker and its own
 * caveat, and the only thing this file would have to grow is a sentence for a
 * failure name its readers did not already have, which is a compile error in
 * `STORE_FAILURES` rather than a silent gap.
 *
 * **Nothing is uploaded, and the card says so before the first picker.** The
 * files are somebody's own library and are read in the browser: `lib/stores.ts`
 * carries the same statement at the seam that keeps it true.
 *
 * Dumb: it owns a file input per store and the buttons. The reading and the
 * writes live in the page's hooks.
 */
export default function StoreImport({
  sources,
  preview,
  progress,
  result,
  isReading,
  isImporting,
  onChoose,
  onConfirm,
  onStop,
  onCancel,
}: StoreImportProps) {
  const { t } = useTranslation();
  // One input per store, kept by id rather than in a named ref each: the rows
  // are data, so the inputs have to be too.
  const inputs = useRef(new Map<StoreId, HTMLInputElement | null>());

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("stores.explain")}
      </p>

      {/*
        Named here because an import is where somebody arrives and this card is
        further down the page. A store export carries what the store knows,
        which for Play Books is a title, an author and a volume id, so a library
        imported from one is complete only after that card has been run. A
        sentence rather than a button: the lookup is metered and the card is
        where the run is explained and counted.
      */}
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("stores.thenLookThemUp")}
      </p>

      {STORE_IDS.map((id) => {
        const store = STORES[id];
        const source = sources[id];
        return (
          <div
            key={id}
            className="border border-paper-200 rounded-xl p-3 space-y-2 dark:border-paper-700"
          >
            <h3 className="text-sm font-medium text-paper-800 dark:text-paper-100">
              {t(store.name)}
            </h3>
            <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
              {t(store.explain)}
            </p>
            {store.caveat && (
              <p className="text-xs text-paper-600 bg-paper-50 border border-paper-200 rounded-lg px-3 py-2 leading-relaxed dark:text-paper-400 dark:bg-paper-900 dark:border-paper-700">
                {t(store.caveat)}
              </p>
            )}

            <input
              ref={(node) => {
                inputs.current.set(id, node);
              }}
              type="file"
              accept={store.accept}
              aria-label={t(store.choose)}
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                // Reset, so choosing the same file twice fires change again.
                event.target.value = "";
                if (file) onChoose(id, file);
              }}
            />
            <button
              type="button"
              disabled={isImporting}
              onClick={() => inputs.current.get(id)?.click()}
              className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 transition-colors dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
            >
              {t(store.choose)}
            </button>

            {source?.status === "reading" && (
              <p
                role="status"
                className="text-xs text-paper-600 dark:text-paper-400"
              >
                {t("stores.reading", { file: source.fileName })}
              </p>
            )}
            {source?.status === "read" && (
              <div className="text-xs text-paper-600 space-y-0.5 dark:text-paper-400">
                <p>
                  {t("stores.sourceRead", {
                    count: source.library.books.length,
                  })}
                </p>
                {source.library.skipped > 0 && (
                  <p>
                    {t("stores.sourceSkipped", {
                      count: source.library.skipped,
                    })}
                  </p>
                )}
                {source.library.refused > 0 && (
                  <p>
                    {t("stores.sourceRefused", {
                      count: source.library.refused,
                    })}
                  </p>
                )}
              </div>
            )}
            {/* **The store is named in the sentence and not only in the
                heading above it.** This is the one place a member meets the
                rule that a source which cannot be read costs that source
                alone, and "was skipped" with no name is what makes a member
                stop the whole import to find out which one. */}
            {source?.status === "failed" && (
              <p
                role="alert"
                className="text-sm text-danger-600 dark:text-danger-300"
              >
                {t("stores.sourceLost", {
                  store: t(store.name),
                  reason: t(STORE_FAILURES[source.failure]),
                })}
              </p>
            )}
            {source?.status === "error" && (
              <p
                role="alert"
                className="text-sm text-danger-600 dark:text-danger-300"
              >
                {t("stores.sourceLost", {
                  store: t(store.name),
                  reason: errorText(
                    source.error,
                    t("common.somethingWentWrong"),
                    t,
                  ),
                })}
              </p>
            )}
          </div>
        );
      })}

      {preview && (
        <>
          <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
            <p>
              {t("stores.previewTitle", {
                total: preview.total,
                importable: preview.importable,
              })}
            </p>
          </div>

          {progress && (
            <p
              role="status"
              className="text-xs text-paper-600 dark:text-paper-400"
            >
              {t("stores.progress", {
                done: progress.done,
                total: progress.total,
              })}
            </p>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={isImporting ? onStop : onCancel}
              className="flex-1 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
            >
              {isImporting ? t("stores.stop") : t("common.cancel")}
            </button>
            <button
              type="button"
              disabled={isImporting || isReading || preview.importable === 0}
              onClick={onConfirm}
              className="flex-1 py-2.5 rounded-xl bg-accent-fill text-sm font-semibold text-on-accent hover:bg-accent-fill-hover disabled:bg-accent-300"
            >
              {isImporting
                ? t("stores.importing")
                : t("stores.confirm", { count: preview.importable })}
            </button>
          </div>
        </>
      )}

      {result && (
        <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-2 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
          <p>
            {result.stopped
              ? t("stores.resultStopped", { added: result.added })
              : t("stores.result", { added: result.added })}
          </p>
          {result.failures.length > 0 && (
            <>
              <p className="text-xs text-paper-600 dark:text-paper-400">
                {t("stores.resultFailures", { count: result.failures.length })}
              </p>
              <ul className="text-xs text-paper-600 space-y-0.5 dark:text-paper-400">
                {result.failures.slice(0, FAILURES_SHOWN).map((row, index) => (
                  // The index keys these: a title is not a key, and two devices
                  // holding one book is the ordinary case here.
                  <li key={index} className="truncate">
                    {row.title}
                    {" · "}
                    {row.status === DUPLICATE_STATUS
                      ? t("stores.duplicate")
                      : t("stores.notAdded")}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * One sentence per refusal, over every store's reasons at once.
 *
 * A total `Record` rather than a switch, `CalibreImport`'s rule: a reader that
 * grows a reason is a type error here rather than a member being shown nothing.
 *
 * **The overlapping names carry one sentence each and it is store neutral**,
 * because `damaged` means the same thing to a member whichever reader said it
 * and the row it appears on already names the store. A sentence naming Kobo
 * under a name a Takeout can also answer would be wrong half the time.
 */
const STORE_FAILURES: Record<StoreFailure, MessageKey> = {
  "not-a-database": "stores.failureNotADatabase",
  "not-a-kobo-device": "stores.failureNotAKobo",
  "not-an-archive": "stores.failureNotAnArchive",
  "not-a-takeout": "stores.failureNotATakeout",
  "not-an-apple-books-library": "stores.failureNotAnAppleBooksLibrary",
  "not-a-kindle-library": "stores.failureNotAKindleLibrary",
  "not-a-digital-editions-catalogue":
    "stores.failureNotADigitalEditionsCatalogue",
  "not-a-moon-reader-backup": "stores.failureNotAMoonReaderBackup",
  damaged: "stores.failureDamaged",
  "too-large": "stores.failureTooLarge",
  "no-engine": "stores.failureNoEngine",
  "no-inflate": "stores.failureNoInflate",
  protected: "stores.failureProtected",
  unsupported: "stores.failureUnsupported",
  empty: "stores.failureEmpty",
};
