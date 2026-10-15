import type { HighlightOut, UserOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { shortMonthDate } from "../../../lib/date";

/**
 * `QUOTE_TEXT_MAX`, which the API holds a highlight to before sharing it,
 * counted as the server counts: in code points, not UTF-16 units, so a passage
 * of astral characters is not called too long when the server would take it.
 */
const SHARE_MAX = 2000;

function codePoints(text: string): number {
  return [...text].length;
}

interface HighlightListProps {
  highlights: HighlightOut[];
  currentUser: UserOut;
  pendingIds: ReadonlySet<number>;
  onSetShared: (highlightId: number, isShared: boolean) => void;
  onDelete: (highlightId: number) => void;
}

/**
 * Passages marked in this book on a reading device. Used only by BookDetail.
 *
 * **Private until shared, and shared by its author alone.** The caller's own
 * rows carry the control and say which state they are in; another member's
 * row is here only because it was shared, so it carries their name instead.
 * There is no admin arm: sharing speaks for the author.
 *
 * **Deleting asks first**, because it is for good: the server remembers the
 * mark, so no later import brings it back.
 *
 * **The date is the device's own day**, read off its wall clock with no zone,
 * so only the date part is shown and nothing is converted.
 *
 * Drawn only when there is something to draw: highlights arrive by an import
 * on the library settings page, never by a form here.
 */
export default function HighlightList({
  highlights,
  currentUser,
  pendingIds,
  onSetShared,
  onDelete,
}: HighlightListProps) {
  const { t, locale } = useTranslation();
  if (highlights.length === 0) return null;

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-3 dark:text-paper-200">
        {t("highlights.title")}
      </p>
      <div className="space-y-3">
        {highlights.map((highlight) => {
          const isAuthor = highlight.user_id === currentUser.id;
          const tooLong = codePoints(highlight.text) > SHARE_MAX;
          const busy = pendingIds.has(highlight.id);
          const details = [
            highlight.chapter,
            highlight.page != null
              ? t("quotes.onPage", { page: highlight.page })
              : null,
            isAuthor ? null : (highlight.author?.username ?? null),
            highlight.highlighted_at
              ? shortMonthDate(highlight.highlighted_at.slice(0, 10), locale)
              : null,
          ].filter((part): part is string => Boolean(part));

          return (
            <div
              key={highlight.id}
              className="bg-paper-50 rounded-xl p-3 border border-paper-100 dark:bg-paper-900 dark:border-paper-800"
            >
              <blockquote className="border-l-2 border-accent-300 pl-3 text-sm text-paper-700 leading-relaxed whitespace-pre-line dark:border-accent-500 dark:text-paper-200">
                {highlight.text}
              </blockquote>
              {highlight.note != null && (
                <p className="text-sm text-paper-600 mt-2 whitespace-pre-line dark:text-paper-400">
                  {highlight.note}
                </p>
              )}
              <div className="flex items-center justify-between gap-2 mt-2">
                <span className="text-xs text-paper-600 dark:text-paper-400">
                  {details.join(" · ")}
                </span>
                {isAuthor && (
                  <span className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-paper-600 dark:text-paper-400">
                      {highlight.is_shared
                        ? t("highlights.shared")
                        : t("highlights.private")}
                    </span>
                    {highlight.is_shared ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onSetShared(highlight.id, false)}
                        className="text-xs text-accent-600 hover:text-accent-800 disabled:opacity-50 dark:text-accent-400 dark:hover:text-accent-300"
                      >
                        {t("highlights.unshare")}
                      </button>
                    ) : tooLong ? (
                      <span className="text-xs text-paper-600 italic dark:text-paper-400">
                        {t("highlights.tooLongToShare")}
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onSetShared(highlight.id, true)}
                        className="text-xs text-accent-600 hover:text-accent-800 disabled:opacity-50 dark:text-accent-400 dark:hover:text-accent-300"
                      >
                        {t("highlights.share")}
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        if (confirm(t("highlights.deleteConfirm")))
                          onDelete(highlight.id);
                      }}
                      // The rungs QuoteList's delete names, for its reason.
                      className="text-xs text-danger-500 hover:text-danger-600 disabled:opacity-50 dark:text-danger-300 dark:hover:text-danger-100"
                    >
                      {t("common.delete")}
                    </button>
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
