import { useState, type FormEvent } from "react";

import {
  BookFormat,
  type BookOut,
  type ProgressOut,
} from "../../../api/generated/model";
import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";

/** Which unit a new entry is recorded in. */
type Unit = "page" | "percent";

interface ProgressPanelProps {
  book: BookOut;
  entries: ProgressOut[];
  isRecording: boolean;
  onRecord: (entry: {
    page?: number;
    percent?: number;
    minutes?: number;
  }) => void;
  onRemove: (progressId: number) => void;
}

/**
 * Which unit to offer first.
 *
 * A page count is the signal, not the format: a paperback nobody has enriched
 * has no page count either, and asking for a page number the reader cannot
 * check against anything is asking for a number that means nothing. An
 * audiobook is named as well because it can carry a page count from its print
 * edition, which is not a position anybody listening can report.
 *
 * Exported so its own test can state the rule rather than infer it from
 * rendered markup.
 */
export function defaultUnit(book: BookOut): Unit {
  if (book.format === BookFormat.audiobook) return "percent";
  return book.page_count ? "page" : "percent";
}

/**
 * Where this reader has got to, and how they got there.
 *
 * A log rather than a single editable number, because the questions the panel
 * exists for ("how much did I read in March", "how long did that take") are
 * about the history, and one number overwrites the history on every save.
 *
 * Sits below the status buttons for the same reason `ReadingPanel` does: the
 * first entry promotes an unstarted book to reading, so the control that does
 * it belongs next to the one that says so.
 */
export default function ProgressPanel({
  book,
  entries,
  isRecording,
  onRecord,
  onRemove,
}: ProgressPanelProps) {
  const { t, locale } = useTranslation();
  const [unit, setUnit] = useState<Unit>(() => defaultUnit(book));
  const [position, setPosition] = useState("");
  const [minutes, setMinutes] = useState("");

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = Number(position);
    if (!Number.isFinite(value) || position.trim() === "") return;

    const sitting = Number(minutes);
    onRecord({
      // Exactly one unit, which is what the API accepts and what the CHECK
      // constraint behind it enforces. Sending both is not expressible here.
      ...(unit === "page" ? { page: value } : { percent: value }),
      ...(minutes.trim() !== "" && Number.isFinite(sitting) && sitting > 0
        ? { minutes: sitting }
        : {}),
    });
    setPosition("");
    setMinutes("");
  }

  const percent = book.my_progress_percent ?? null;

  return (
    <div className="space-y-3">
      {/* h3, not h2: the section handle that folds this panel away is the
          h2 above it, so a flat h2 here would show a reader's heading list a
          page with no grouping in it at all. */}
      <h3 className="text-sm font-semibold text-paper-900 dark:text-paper-100">
        {t("progress.label")}
      </h3>

      {book.my_progress_page != null || book.my_progress_percent != null ? (
        <div className="space-y-1.5">
          <p className="text-sm text-paper-700 dark:text-paper-200">
            {book.my_progress_page != null
              ? book.page_count
                ? t("progress.onPageOf", {
                    page: book.my_progress_page,
                    total: book.page_count,
                  })
                : t("progress.onPage", { page: book.my_progress_page })
              : t("progress.atPercent", {
                  percent: book.my_progress_percent ?? 0,
                })}
          </p>
          {percent != null && (
            <div
              role="progressbar"
              aria-valuenow={percent}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={t("progress.label")}
              className="h-2 rounded-full bg-paper-100 overflow-hidden dark:bg-paper-800"
            >
              <div
                className="h-full rounded-full bg-accent-400"
                style={{ width: `${percent}%` }}
              />
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-paper-600 italic dark:text-paper-400">
          {t("progress.none")}
        </p>
      )}

      <form onSubmit={submit} className="space-y-2">
        {/* Both units are always offered, whichever one is preselected. A book
            with a page count can still be listened to, and a reader who knows
            they are halfway through should not have to work out which page
            that is. */}
        <div
          className="flex gap-2"
          role="group"
          aria-label={t("progress.unit")}
        >
          {(["page", "percent"] as const).map((choice) => (
            <button
              key={choice}
              type="button"
              onClick={() => setUnit(choice)}
              aria-pressed={unit === choice}
              className={`flex-1 py-1.5 rounded-xl text-xs font-medium border transition-colors ${
                unit === choice
                  ? "bg-accent-50 border-accent-300 text-accent-800 " +
                    "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                  : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 " +
                    "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
              }`}
            >
              {choice === "page"
                ? t("progress.unitPage")
                : t("progress.unitPercent")}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <input
            type="number"
            min={unit === "page" ? 1 : 0}
            max={unit === "page" ? undefined : 100}
            value={position}
            onChange={(event) => setPosition(event.target.value)}
            placeholder={
              unit === "page"
                ? t("progress.pagePlaceholder")
                : t("progress.percentPlaceholder")
            }
            aria-label={
              unit === "page"
                ? t("progress.unitPage")
                : t("progress.unitPercent")
            }
            className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
          <input
            type="number"
            min={1}
            value={minutes}
            onChange={(event) => setMinutes(event.target.value)}
            placeholder={t("progress.minutesPlaceholder")}
            aria-label={t("progress.minutes")}
            className="w-24 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
        </div>

        <button
          type="submit"
          disabled={isRecording || position.trim() === ""}
          className="w-full py-2 rounded-xl bg-accent-fill text-on-accent text-sm font-medium hover:bg-accent-fill-hover disabled:opacity-50 transition-colors"
        >
          {isRecording ? t("common.saving") : t("progress.record")}
        </button>
      </form>

      {entries.length > 0 && (
        <ul className="space-y-1.5">
          {entries.map((entry) => (
            <li
              key={entry.id}
              className="flex items-center gap-2 text-xs text-paper-600 dark:text-paper-400"
            >
              <span className="flex-1">
                {[
                  entry.page != null
                    ? t("progress.onPage", { page: entry.page })
                    : t("progress.atPercent", { percent: entry.percent ?? 0 }),
                  entry.minutes != null
                    ? t("progress.minutesRead", { minutes: entry.minutes })
                    : null,
                  formatDate(entry.recorded_at),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <button
                type="button"
                onClick={() => onRemove(entry.id)}
                aria-label={t("progress.removeEntry")}
                className="text-paper-600 hover:text-danger-600 dark:text-paper-400 dark:hover:text-danger-300"
              >
                <span aria-hidden="true">
                  <Icon name="close" className="w-3.5 h-3.5" />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
