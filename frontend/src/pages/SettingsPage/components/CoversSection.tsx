import { Button, ErrorState, Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";

interface CoversSectionProps {
  result: {
    examined: number;
    stored: number;
    unreachable: number;
    still_missing: number;
    remaining: number;
  } | null;
  isRunning: boolean;
  error: unknown;
  onRun: () => void;
}

/**
 * Fetch the covers of books that have none.
 *
 * The result is several numbers rather than one, because "fixed 12" cannot be
 * acted on: `remaining` is what tells the reader to press again, and
 * `still_missing` is what tells them pressing again will not help those books.
 *
 * `unreachable` is its own line rather than folded into either. A pod that
 * cannot reach the image services puts every book there, and folding it in
 * would report "looked at 100 books and stored 0. No service has one for 0",
 * which reads as a clean no-op in exactly the situation this exists for.
 */
export default function CoversSection({
  result,
  isRunning,
  error,
  onRun,
}: CoversSectionProps) {
  const { t } = useTranslation();

  return (
    <SettingsSection title={t("covers.title")} icon="book">
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("covers.explain")}
      </p>

      <Button
        variant="secondary"
        className="mt-3"
        isLoading={isRunning}
        onClick={onRun}
        icon={<Icon name="book" className="h-4 w-4" />}
      >
        {t("covers.backfill")}
      </Button>

      {error != null && (
        <div className="mt-2">
          <ErrorState error={error} fallback={t("covers.backfillFailed")} />
        </div>
      )}

      {result && (
        <div role="status" className="mt-3 space-y-1 text-sm">
          <p className="text-paper-700 dark:text-paper-300">
            {t("covers.result", {
              examined: result.examined,
              stored: result.stored,
              missing: result.still_missing,
            })}
          </p>
          {result.unreachable > 0 && (
            <p className="text-paper-700 dark:text-paper-300">
              {t("covers.unreachable", { count: result.unreachable })}
            </p>
          )}
          <p className="text-paper-600 dark:text-paper-400">
            {result.remaining > 0
              ? t("covers.remaining", { remaining: result.remaining })
              : t("covers.allDone")}
          </p>
        </div>
      )}
    </SettingsSection>
  );
}
