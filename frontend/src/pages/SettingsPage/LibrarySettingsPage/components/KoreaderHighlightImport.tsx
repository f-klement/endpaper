import { useRef } from "react";

import { useTranslation, type MessageKey } from "../../../../i18n";
import type { SidecarOutcome, SidecarRow } from "../hooks";

interface KoreaderHighlightImportProps {
  rows: readonly SidecarRow[] | null;
  isRunning: boolean;
  onChoose: (files: readonly File[]) => void;
}

/** The sentence for each outcome that is not an import. */
const REFUSED: Record<
  Exclude<SidecarOutcome["kind"], "imported">,
  MessageKey
> = {
  unmatched: "highlights.outcomeUnmatched",
  ambiguous: "highlights.outcomeAmbiguous",
  unreadable: "highlights.outcomeUnreadable",
  "too-large": "highlights.outcomeTooLarge",
  "no-fingerprint": "highlights.outcomeNoFingerprint",
  empty: "highlights.outcomeEmpty",
  failed: "highlights.outcomeFailed",
};

/**
 * Picking KOReader sidecars and saying what became of each one.
 *
 * **Several files at once, and no preview.** A sidecar is one book's marks and
 * an import writes only the member's own private rows, which a second run
 * finds rather than doubles, so there is nothing a confirm step would protect.
 * Every file gets its own line, because an unmatched one is the member's to
 * fix (add the book's file from the scan page) and must not vanish into a
 * total.
 */
export default function KoreaderHighlightImport({
  rows,
  isRunning,
  onChoose,
}: KoreaderHighlightImportProps) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-3">
      <p className="text-sm text-paper-600 dark:text-paper-300">
        {t("highlights.importIntro")}
      </p>
      <input
        ref={input}
        type="file"
        accept=".lua"
        multiple
        aria-label={t("highlights.importChoose")}
        className="sr-only"
        disabled={isRunning}
        onChange={(event) => {
          const files = [...(event.target.files ?? [])];
          // Reset, so choosing the same files again fires change again.
          event.target.value = "";
          onChoose(files);
        }}
      />
      <button
        type="button"
        disabled={isRunning}
        onClick={() => input.current?.click()}
        className="w-full py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 transition-colors dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
      >
        {isRunning
          ? t("highlights.importReading")
          : t("highlights.importChoose")}
      </button>
      {rows !== null && (
        <ul className="space-y-2" aria-live="polite">
          {rows.map((row) => (
            <li
              key={row.key}
              className="text-sm text-paper-700 dark:text-paper-200"
            >
              <span className="font-medium">{row.title ?? row.name}</span>
              <span className="block text-paper-600 dark:text-paper-400">
                {row.outcome.kind === "imported"
                  ? [
                      t("highlights.outcomeImported", {
                        created: row.outcome.created,
                        updated: row.outcome.updated,
                        unchanged: row.outcome.unchanged,
                      }),
                      row.outcome.left_deleted > 0
                        ? t("highlights.outcomeLeftDeleted", {
                            count: row.outcome.left_deleted,
                          })
                        : null,
                      row.outcome.oversized > 0
                        ? t("highlights.outcomeOversized", {
                            count: row.outcome.oversized,
                          })
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" ")
                  : t(REFUSED[row.outcome.kind])}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
