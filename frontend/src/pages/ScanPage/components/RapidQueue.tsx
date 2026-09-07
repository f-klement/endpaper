import { useTranslation } from "../../../i18n";
import type { BookMatch } from "../../../api/generated/model";
import type { ScannedEntry } from "../hooks";

interface RapidQueueProps {
  entries: ScannedEntry[];
  isAdding: boolean;
  result: { added: number; failed: number } | null;
  onRemove: (key: string) => void;
  onAddAll: () => void;
  onDiscard: () => void;
  /** How many entries have only their name left to go on. */
  waiting: number;
  /**
   * How many have records offered and neither taken nor refused.
   *
   * **Said, because the batch no longer takes these and that used to be
   * silent**: a row still being decided keeps its file name draft, so adding it
   * would throw away the records the catalogue found with nothing on screen.
   *
   * **Taken from the hook rather than counted here**, because the batch excludes
   * exactly this set and a predicate written twice is a screen able to report
   * something the page did not do.
   */
  deciding: number;
  /** Roughly how long looking all of those up would take, in minutes. */
  paceMinutes: number;
  isLookingUp: boolean;
  onLookUp: () => void;
  onStopLookUp: () => void;
  onChoose: (key: string, match: BookMatch) => void;
  onKeepName: (key: string) => void;
}

/**
 * What the scanner has caught and the file picker has read so far.
 *
 * Deliberately shows the failures alongside the hits. A book whose ISBN
 * matched nothing is still a book on the shelf, an EPUB that would not open is
 * still a book on somebody's disk, and silently dropping either is how a
 * catalogue ends up quietly incomplete.
 *
 * **Entries are identified by `key`, never by ISBN**, because a picked file
 * usually has none: see `ScannedEntry.key`.
 */
export default function RapidQueue({
  entries,
  isAdding,
  result,
  onRemove,
  onAddAll,
  onDiscard,
  waiting,
  deciding,
  paceMinutes,
  isLookingUp,
  onLookUp,
  onStopLookUp,
  onChoose,
  onKeepName,
}: RapidQueueProps) {
  const { t } = useTranslation();

  // **Said once, and only for the rows it is true of.** Explaining before the
  // fact would be a page apologising for something that may not happen, and
  // explaining per row would say it thirty times. A member who was offered
  // records and preferred the name is not a member the catalogues had nothing
  // for, so `answered` carries the two apart.
  const anyEmptyAnswer = entries.some((entry) => entry.answered === "nothing");
  const busy = isAdding || isLookingUp;

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

      {/* Offered, never automatic. A folder of several hundred files is
          several hundred catalogue fan outs, which is not something a page may
          spend because somebody pointed at a directory. */}
      {waiting > 0 && !isLookingUp && (
        <div>
          <button
            type="button"
            onClick={onLookUp}
            disabled={isAdding}
            className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
          >
            {t("fallback.lookUp", { count: waiting })}
          </button>
          <p className="text-xs text-paper-600 mt-1.5 leading-relaxed dark:text-paper-400">
            {t("fallback.pace", { minutes: paceMinutes })}
          </p>
        </div>
      )}

      {isLookingUp && (
        <button
          type="button"
          onClick={onStopLookUp}
          className="w-full py-2 rounded-xl border border-paper-200 text-sm font-medium text-paper-700 hover:bg-paper-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
        >
          {t("fallback.stop")}
        </button>
      )}

      {anyEmptyAnswer && (
        <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
          {t("fallback.aboutEbooks")}
        </p>
      )}

      <ul className="space-y-1.5 max-h-64 overflow-y-auto">
        {entries.map((entry) => (
          <li
            key={entry.key}
            className="text-sm border border-paper-100 rounded-lg px-2.5 py-1.5 dark:border-paper-800"
          >
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate">
                {entry.state === "looking-up" && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {t("rapid.lookingUp")}
                  </span>
                )}
                {entry.state === "reading" && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {t("rapid.reading", { name: entry.label })}
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
                {entry.state === "searching" && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {t("fallback.searching")}
                  </span>
                )}
                {/* A book, not a failure: it carries what its name said and the
                  batch adds it like any other. The note beside it says where
                  the title came from and what the file itself could not say. */}
                {(entry.state === "derived" || entry.state === "choosing") && (
                  <span className="text-paper-800 dark:text-paper-100">
                    {entry.draft?.title}
                    <span className="text-paper-600 dark:text-paper-400">
                      {" "}
                      {t("fallback.fromTheName")}
                      {entry.reason ? ` ${entry.reason}` : ""}
                    </span>
                  </span>
                )}
                {/* Named, not counted. After a shelf of thirty, "six could not
                  be added" is unrecoverable: this says which six and why, and
                  they stay in the queue so they can be retried or dropped. */}
                {entry.state === "failed" && (
                  <span className="text-danger-600 dark:text-danger-300">
                    {entry.draft?.title || entry.label}
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
                onClick={() => onRemove(entry.key)}
                aria-label={t("rapid.removeFromQueue", { label: entry.label })}
                className="shrink-0 text-paper-600 hover:text-danger-500 dark:text-paper-400 dark:hover:text-danger-300"
              >
                ×
              </button>
            </div>

            {/* Accept or reject, per file. The ranking already put the likeliest
                record first, and the rest are here to be disagreed with. */}
            {entry.state === "choosing" && entry.matches && (
              <div className="mt-2 space-y-1">
                <p className="text-xs text-paper-600 dark:text-paper-400">
                  {t("fallback.matches", { count: entry.matches.length })}
                </p>
                <ul className="space-y-1">
                  {entry.matches.map((match, index) => (
                    <li
                      key={`${match.google_books_id ?? match.isbn13 ?? ""}:${index}`}
                      className="flex items-center gap-2 text-xs"
                    >
                      <span className="min-w-0 flex-1 truncate text-paper-700 dark:text-paper-200">
                        {match.title}
                        {match.author ? `, ${match.author}` : ""}
                        {match.year ? ` (${match.year})` : ""}
                      </span>
                      <button
                        type="button"
                        // The visible word is the same on every row and the
                        // accessible name is not: a screen reader in a queue of
                        // thirty files would otherwise meet a hundred and fifty
                        // buttons called "Use".
                        aria-label={t("fallback.useFor", {
                          title: match.title ?? entry.label,
                        })}
                        onClick={() => onChoose(entry.key, match)}
                        className="shrink-0 px-2 py-1 rounded-lg border border-paper-200 font-medium text-paper-700 hover:bg-paper-50 dark:border-paper-700 dark:text-paper-200 dark:hover:bg-paper-800"
                      >
                        {t("fallback.use")}
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={() => onKeepName(entry.key)}
                  className="text-xs text-paper-600 underline hover:text-paper-800 dark:text-paper-400 dark:hover:text-paper-200"
                >
                  {t("fallback.keep")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>

      {deciding > 0 && (
        <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
          {t("fallback.stillToDecide", { count: deciding })}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDiscard}
          disabled={busy}
          className="px-4 py-2.5 rounded-xl border border-paper-200 text-sm font-medium text-paper-600 hover:bg-paper-50 disabled:opacity-50 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
        >
          {t("rapid.discard")}
        </button>
        <button
          type="button"
          onClick={onAddAll}
          disabled={busy}
          className="flex-1 py-2.5 rounded-xl bg-accent-fill text-on-accent text-sm font-semibold hover:bg-accent-fill-hover disabled:opacity-50"
        >
          {isAdding ? t("rapid.adding") : t("rapid.addAll")}
        </button>
      </div>
    </div>
  );
}
