import { NetworkError } from "../api/mutator";
import { useTranslation, type Translate } from "../i18n";

interface ErrorStateProps {
  /** Whatever the query or mutation rejected with. */
  error: unknown;
  /** Shown when the error carries no usable message of its own. */
  fallback?: string;
  onRetry?: () => void;
}

/**
 * Turn an unknown thrown value into something displayable.
 *
 * `t` is required rather than optional, and that is the enforcement: one of
 * the answers here has to be translated, and an optional parameter is one a
 * call site forgets.
 *
 * A `NetworkError` is the only case whose wording is chosen here. Everything
 * else already carries a sentence written for the reader: the server's own
 * `detail` through `ApiError`, or the page's fallback.
 */
export function errorText(
  error: unknown,
  fallback: string,
  t: Translate,
): string {
  // Before the generic Error branch below, which would otherwise print the
  // browser's own "Failed to fetch" to somebody on a phone.
  if (error instanceof NetworkError) return t("common.cannotReachServer");
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error) return error;
  return fallback;
}

/**
 * The one way a failed request is shown to the reader.
 *
 * Every page renders its query errors through this, so a failure looks the
 * same everywhere instead of being an `alert()` on one screen and red text on
 * another.
 */
export default function ErrorState({
  error,
  fallback,
  onRetry,
}: ErrorStateProps) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="text-sm text-bloom-600 bg-bloom-100 border border-bloom-100 rounded-lg px-3 py-2 flex items-center justify-between gap-3 dark:text-bloom-300 dark:bg-bloom-700 dark:border-bloom-700"
    >
      <span>
        {errorText(error, fallback ?? t("common.somethingWentWrong"), t)}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 text-xs font-medium text-bloom-700 underline hover:no-underline"
        >
          {t("common.tryAgain")}
        </button>
      )}
    </div>
  );
}
