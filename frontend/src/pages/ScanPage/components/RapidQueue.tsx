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

  if (result) {
    return (
      <p
        role="status"
        className="text-sm text-green-700 bg-green-50 border border-green-100 rounded-xl px-3 py-2 mt-4 dark:text-green-300 dark:bg-green-950 dark:border-green-900"
      >
        {t("rapid.added", { count: result.added, failed: result.failed })}
      </p>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-400 text-center mt-4 dark:text-gray-500">
        {t("rapid.nothingScanned")}
      </p>
    );
  }

  return (
    <div className="mt-4 space-y-3">
      <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
        {t("rapid.queued", { count: entries.length })}
      </p>

      <ul className="space-y-1.5 max-h-64 overflow-y-auto">
        {entries.map((entry) => (
          <li
            key={entry.isbn}
            className="flex items-center gap-2 text-sm border border-gray-100 rounded-lg px-2.5 py-1.5 dark:border-gray-800"
          >
            <span className="min-w-0 flex-1 truncate">
              {entry.state === "looking-up" && (
                <span className="text-gray-400 dark:text-gray-500">
                  {t("rapid.lookingUp")}
                </span>
              )}
              {entry.state === "found" && (
                <span className="text-gray-800 dark:text-gray-100">
                  {entry.draft?.title}
                </span>
              )}
              {entry.state === "not-found" && (
                <span className="text-amber-700 dark:text-amber-300">
                  {t("rapid.notFound", { isbn: entry.isbn })}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => onRemove(entry.isbn)}
              aria-label={t("common.delete")}
              className="shrink-0 text-gray-400 hover:text-red-500 dark:text-gray-500"
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
          className="px-4 py-2.5 rounded-xl border border-gray-200 text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          {t("rapid.discard")}
        </button>
        <button
          type="button"
          onClick={onAddAll}
          disabled={isAdding}
          className="flex-1 py-2.5 rounded-xl bg-sky-500 text-white text-sm font-semibold hover:bg-sky-600 disabled:opacity-50"
        >
          {isAdding ? t("rapid.adding") : t("rapid.addAll")}
        </button>
      </div>
    </div>
  );
}
