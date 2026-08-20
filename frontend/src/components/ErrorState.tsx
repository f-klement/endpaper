import { useTranslation } from "../i18n";

interface ErrorStateProps {
  /** Whatever the query or mutation rejected with. */
  error: unknown;
  /** Shown when the error carries no usable message of its own. */
  fallback?: string;
  onRetry?: () => void;
}

/** Turn an unknown thrown value into something displayable. */
export function errorText(error: unknown, fallback: string): string {
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
        {errorText(error, fallback ?? t("common.somethingWentWrong"))}
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
