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
 * What a thrown value turns out to be, before anything decides what to show.
 *
 * Two answers and an absence. `unreachable` is the one this side has words
 * for; `said` is words somebody else wrote, the server's own `detail` through
 * `ApiError` or a string that was thrown, which nothing here can translate.
 */
export type RequestFailure =
  { kind: "unreachable" } | { kind: "said"; message: string };

/**
 * Which of those a thrown value is.
 *
 * **The classification is here and the wording is not**, because two callers
 * want different things from the same four branches and used to hold their own
 * copy of them: this renders a sentence for a reader, and `ScanPage`'s queue
 * keeps the answer as a name it can render later, in whatever language is being
 * read by then. A branch added to one copy diverged the other silently.
 *
 * `undefined` where nothing usable was thrown, which is the caller's fallback
 * rather than a third answer: what to say instead is the caller's to choose.
 */
export function classifyError(error: unknown): RequestFailure | undefined {
  // Before the generic Error branch below, which would otherwise print the
  // browser's own "Failed to fetch" to somebody on a phone.
  if (error instanceof NetworkError) return { kind: "unreachable" };
  if (error instanceof Error && error.message)
    return { kind: "said", message: error.message };
  if (typeof error === "string" && error)
    return { kind: "said", message: error };
  return undefined;
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
  const failure = classifyError(error);
  if (failure === undefined) return fallback;
  return failure.kind === "unreachable"
    ? t("common.cannotReachServer")
    : failure.message;
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
      className="text-sm text-danger-600 bg-danger-100 border border-danger-100 rounded-lg px-3 py-2 flex items-center justify-between gap-3 dark:text-danger-300 dark:bg-danger-700 dark:border-danger-700"
    >
      <span>
        {errorText(error, fallback ?? t("common.somethingWentWrong"), t)}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 text-xs font-medium text-danger-700 underline hover:no-underline"
        >
          {t("common.tryAgain")}
        </button>
      )}
    </div>
  );
}
