import type { DigitalReferenceOut } from "../../../api/generated/model";
import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import { shortMonthDate } from "../../../lib/date";
import { plainName } from "../../../lib/fileName";

interface DigitalReferencesPanelProps {
  references: DigitalReferenceOut[];
  /** Ids of the references being forgotten right now. */
  forgetting: ReadonlySet<number>;
  listError: unknown;
  error: unknown;
  onForget: (reference: DigitalReferenceOut, shownAs: string) => void;
}

/**
 * Where this book's files have been said to be.
 *
 * **Every value here is a claim a browser made, and the panel says so**: the
 * date is when this server was last *told*, never when anything looked, and a
 * missing flag is a browser that could not see the file rather than evidence
 * it is gone. Only a member's Forget removes a row.
 *
 * **Both halves of the location go through `plainName` before they are
 * drawn.** The stored text is the raw text the browser gave, which is right
 * for matching a file and wrong for a screen: a bidirectional override in a
 * folder name reorders everything printed after it. `lib/digitalReference.ts`
 * states the asymmetry at the site that sends.
 *
 * Draws nothing for a book with no references and no error, the shape
 * `CustomFieldsPanel` takes: the act that adds one is a folder pick on the
 * scan page, so an empty panel here would offer nothing.
 */
export default function DigitalReferencesPanel({
  references,
  forgetting,
  listError,
  error,
  onForget,
}: DigitalReferencesPanelProps) {
  const { t, locale } = useTranslation();
  if (references.length === 0 && listError == null) return null;

  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-1 dark:text-paper-200">
        {t("files.title")}
      </p>
      <p className="text-xs text-paper-600 mb-2 dark:text-paper-300">
        {t("files.hint")}
      </p>

      {references.length > 0 && (
        <ul className="space-y-1 mb-2">
          {references.map((reference) => {
            const root = plainName(reference.root_label);
            const path = plainName(reference.relative_path);
            const shownAs = `${root}/${path}`;
            return (
              <li
                key={reference.id}
                className="flex items-start justify-between gap-2 text-sm bg-paper-100 rounded-lg px-3 py-2 dark:bg-paper-800"
              >
                <div className="min-w-0">
                  <p className="text-paper-700 break-words dark:text-paper-200">
                    <span className="font-medium">{root}</span>/{path}
                  </p>
                  <p className="text-xs text-paper-600 dark:text-paper-300">
                    {t("files.reported", {
                      date: shortMonthDate(reference.confirmed_at, locale),
                    })}
                  </p>
                  {reference.missing_since != null && (
                    <p className="text-xs text-amber-700 dark:text-amber-300">
                      {t("files.missing", {
                        date: shortMonthDate(reference.missing_since, locale),
                      })}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => onForget(reference, shownAs)}
                  disabled={forgetting.has(reference.id)}
                  // The visible word is the same on every row and the
                  // accessible name is not, for the reason the queue's own
                  // per row buttons give.
                  aria-label={t("files.forgetFor", { path: shownAs })}
                  className="shrink-0 text-xs font-medium text-paper-600 hover:text-danger-500 disabled:opacity-50 dark:text-paper-300 dark:hover:text-danger-300"
                >
                  {t("files.forget")}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {listError != null && (
        <div className="mb-2">
          <ErrorState error={listError} fallback={t("files.loadFailed")} />
        </div>
      )}

      {error != null && (
        <div className="mb-2">
          <ErrorState error={error} fallback={t("files.forgetFailed")} />
        </div>
      )}
    </div>
  );
}
