import { useTranslation } from "../../../i18n";
import type { ScannedEntry } from "../hooks";

interface RapidQueueProps {
  entries: ScannedEntry[];
  isAdding: boolean;
  result: { added: number; failed: number } | null;
  onRemove: (isbn: string) => void;
  onAddAll: () => void;
  onDiscard: () => void;
}

/**
 * What the rapid scanner has caught so far.
 *
 * Deliberately shows the failures alongside the hits. A book whose ISBN
 * matched nothing is still a book on the shelf, and silently dropping it is
 * how a catalogue ends up quietly incomplete.
 */
export default function RapidQueue({
  entries,
  isAdding,
  result,
  onRemove,
  onAddAll,
  onDiscard,
}: RapidQueueProps) {
  const { t } = useTranslation();

  // The banner sits above whatever is left rather than replacing it. Anything
  // still in the queue after a run is a book that did not go in.
  const banner = result ? (
    <p
      role="status"
      className={`text-sm rounded-xl px-3 py-2 mt-4 border ${
        result.failed > 0
          ? "text-amber-800 bg-amber-50 border-amber-100 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900"
          : "text-green-700 bg-green-50 border-green-100 dark:text-green-300 dark:bg-green-950 dark:border-green-900"
      }`}
    >
      {t("rapid.added", { count: result.added, failed: result.failed })}
    </p>
  ) : null;

  if (entries.length === 0) {
    if (banner) return banner;
    return (
      <p className="text-sm text-paper-600 text-center mt-4 dark:text-paper-400">
        {t("rapid.nothingScanned")}
      </p>
    );
  }

  return (
    <div className="mt-4 space-y-3">
      {banner}
      <p className="text-sm font-medium text-paper-700 dark:text-paper-200">
        {t("rapid.queued", { count: entries.length })}
      </p>

      <ul className="space-y-1.5 max-h-64 overflow-y-auto">
        {entries.map((entry) => (
          <li
            key={entry.isbn}
            className="flex items-center gap-2 text-sm border border-paper-100 rounded-lg px-2.5 py-1.5 dark:border-paper-800"
          >
            <span className="min-w-0 flex-1 truncate">
              {entry.state === "looking-up" && (
                <span className="text-paper-600 dark:text-paper-400">
                  {t("rapid.lookingUp")}
                </span>
              )}
              {entry.state === "found" && (
                <span className="text-paper-800 dark:text-paper-100">
                  {entry.draft?.title}
                </span>
              )}
              {entry.state === "not-found" && (
                <span className="text-amber-700 dark:text-amber-300">
                  {t("rapid.notFound", { isbn: entry.isbn })}
                </span>
              )}
              {/* Named, not counted. After a shelf of thirty, "six could not
                  be added" is unrecoverable: this says which six and why, and
                  they stay in the queue so they can be retried or dropped. */}
              {entry.state === "failed" && (
                <span className="text-danger-600 dark:text-danger-300">
                  {entry.draft?.title || entry.isbn}
                  {entry.reason && (
                    <span className="text-paper-600 dark:text-paper-400">
                      {" "}
                      {entry.reason}
                    </span>
                  )}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => onRemove(entry.isbn)}
              aria-label={t("rapid.removeFromQueue", { isbn: entry.isbn })}
              className="shrink-0 text-paper-600 hover:text-danger-500 dark:text-paper-400 dark:hover:text-danger-300"
            >
              ×
            </button>
          </li>
        ))}
      </ul>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDiscard}
          disabled={isAdding}
          className="px-4 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
        >
          {t("rapid.discard")}
        </button>
        <button
          type="button"
          onClick={onAddAll}
          disabled={isAdding}
          className="flex-1 py-2.5 rounded-xl bg-accent-fill text-on-accent text-sm font-semibold hover:bg-accent-fill-hover disabled:opacity-50"
        >
          {isAdding ? t("rapid.adding") : t("rapid.addAll")}
        </button>
      </div>
    </div>
  );
}
