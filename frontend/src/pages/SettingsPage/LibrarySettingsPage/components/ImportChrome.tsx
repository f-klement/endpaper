import { useRef, type ReactNode } from "react";

import { errorText } from "../../../../components/ErrorState";
import { useTranslation, type MessageKey } from "../../../../i18n";
import {
  DUPLICATE_STATUS,
  FAILURES_SHOWN,
  type ImportOutcome,
} from "../importing";

/**
 * The parts every import card on this page draws the same way: the picker, the
 * cancel and confirm row, the refusal, and the panel saying what happened.
 *
 * What each card reads, counts and warns about stays in the card. These take
 * finished strings, so no card's wording passes through here.
 */

interface FilePickerProps {
  /** The input's `accept`, which is what the system picker filters by. */
  accept: string;
  /** Names the input, and the button while it is not busy. */
  label: string;
  onFile: (file: File) => void;
  /** Disables the button, and the input with it. */
  busy?: boolean;
  /** The button's text while busy. Without one it keeps `label`. */
  busyLabel?: string;
  /** False withdraws the button and disables the input, which stays mounted. */
  offered?: boolean;
  /** The shorter button a store's row uses inside its own box. */
  compact?: boolean;
}

/**
 * A hidden file input and the button that opens it.
 *
 * The input is visually hidden but still in the tree, so it stays reachable by
 * keyboard and is announced by name rather than as an unlabelled input.
 *
 * **The input follows its button**: disabled whenever the button is disabled or
 * withdrawn. Left enabled, a keyboard user tabs onto it and picks a file mid
 * import, which no pointer user can do; on the Calibre card that clears the
 * preview, and Stop with it, while books are still being written.
 */
export function FilePicker({
  accept,
  label,
  onFile,
  busy = false,
  busyLabel = label,
  offered = true,
  compact = false,
}: FilePickerProps) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={accept}
        aria-label={label}
        className="sr-only"
        disabled={busy || !offered}
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Reset, so choosing the same file twice fires change again.
          event.target.value = "";
          if (file) onFile(file);
        }}
      />
      {offered && (
        <button
          type="button"
          disabled={busy}
          onClick={() => input.current?.click()}
          className={`w-full ${compact ? "py-2" : "py-2.5"} rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 transition-colors dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800`}
        >
          {busy ? busyLabel : label}
        </button>
      )}
    </>
  );
}

interface ConfirmRowProps {
  isImporting: boolean;
  /** Withholds the confirm. An import already running always withholds it. */
  withheld: boolean;
  confirmLabel: string;
  importingLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  /**
   * For an import the card can stop part way: while it runs, the cancel is
   * this instead. Without it the cancel is disabled while the import runs.
   */
  stop?: { label: string; onStop: () => void };
}

/** Cancel on the left, confirm on the right, under a preview. */
export function ConfirmRow({
  isImporting,
  withheld,
  confirmLabel,
  importingLabel,
  onConfirm,
  onCancel,
  stop,
}: ConfirmRowProps) {
  const { t } = useTranslation();
  const stopping = isImporting && stop !== undefined;
  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={stopping ? stop.onStop : onCancel}
        disabled={isImporting && !stopping}
        className="flex-1 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
      >
        {stopping ? stop.label : t("common.cancel")}
      </button>
      <button
        type="button"
        disabled={isImporting || withheld}
        onClick={onConfirm}
        className="flex-1 py-2.5 rounded-xl bg-accent-fill text-sm font-semibold text-on-accent hover:bg-accent-fill-hover disabled:bg-accent-300"
      >
        {isImporting ? importingLabel : confirmLabel}
      </button>
    </div>
  );
}

/** A refusal, said in the card where the member is looking. */
export function ImportAlert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-sm text-danger-600 dark:text-danger-300">
      {children}
    </p>
  );
}

/**
 * Whatever an upload rejected with, through the shared reader, so a refusal
 * naming its fault reads the same here as everywhere else. Nothing when
 * nothing was thrown.
 */
export function ImportError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error == null) return null;
  return (
    <ImportAlert>
      {errorText(error, t("common.somethingWentWrong"), t)}
    </ImportAlert>
  );
}

/** The box a finished import reports in. */
export function ResultPanel({ children }: { children: ReactNode }) {
  return (
    <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-2 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
      {children}
    </div>
  );
}

/** Offered after an import that added books, which arrive unconfirmed. */
export function ReviewAdded({
  added,
  onReview,
}: {
  added: number;
  onReview: () => void;
}) {
  const { t } = useTranslation();
  if (added <= 0) return null;
  return (
    <button
      type="button"
      onClick={onReview}
      className="text-sm font-medium text-accent-700 hover:text-accent-800 dark:text-accent-400 dark:hover:text-accent-300"
    >
      {t("ownership.reviewThem")}
    </button>
  );
}

/** One card's sentences for what an import run in the browser did. */
export interface OutcomeMessages {
  readonly result: MessageKey;
  readonly resultStopped: MessageKey;
  readonly resultFailures: MessageKey;
  readonly duplicate: MessageKey;
  readonly notAdded: MessageKey;
}

/**
 * What a book by book import did: how many arrived, whether the member stopped
 * it, and which books did not arrive and why.
 */
export function OutcomePanel({
  outcome,
  messages,
}: {
  outcome: ImportOutcome;
  messages: OutcomeMessages;
}) {
  const { t } = useTranslation();
  return (
    <ResultPanel>
      <p>
        {t(outcome.stopped ? messages.resultStopped : messages.result, {
          added: outcome.added,
        })}
      </p>
      {outcome.failures.length > 0 && (
        <>
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {t(messages.resultFailures, { count: outcome.failures.length })}
          </p>
          <ul className="text-xs text-paper-600 space-y-0.5 dark:text-paper-400">
            {outcome.failures.slice(0, FAILURES_SHOWN).map((row, index) => (
              // The index keys these: a title is not a key, and two copies of
              // one book, in one library or on two devices, are ordinary.
              <li key={index} className="truncate">
                {row.title}
                {" · "}
                {t(
                  row.status === DUPLICATE_STATUS
                    ? messages.duplicate
                    : messages.notAdded,
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </ResultPanel>
  );
}
