import { Button, ErrorState, Icon } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { SettingsSection } from "../../../components";

interface StoreIdentifiersSectionProps {
  result: {
    examined: number;
    enriched: number;
    not_found: number;
    unavailable: number;
    unresolvable: number;
    remaining: number;
  } | null;
  isRunning: boolean;
  error: unknown;
  onRun: () => void;
}

/**
 * Fill in books a store import left with an identifier and nothing else.
 *
 * **What it repairs is a Google Play Books import.** That export carries a
 * Google Books volume id for every book and no ISBN anywhere, so such a library
 * arrives with a title, an author and an exact key, and until this existed the
 * key was the one thing nothing ever asked about.
 *
 * The result is four numbers for the reason the covers card below gives: they
 * are four different things to do next. `unavailable` means press again;
 * `not_found` means Google has no such volume, so pressing will not help;
 * `unresolvable` means the stored value is not a Google id at all, so nothing
 * was ever asked about it. That last one is kept apart from `not_found`
 * deliberately: saying Google had no record of a book nobody asked Google about
 * is a sentence a member cannot act on.
 *
 * Deliberately not looped here, exactly as the cover backfill is not: an
 * automatic retry would spend a metered quota from a button nobody is watching.
 */
export default function StoreIdentifiersSection({
  result,
  isRunning,
  error,
  onRun,
}: StoreIdentifiersSectionProps) {
  const { t } = useTranslation();

  return (
    <SettingsSection title={t("storeIdentifiers.title")} icon="book">
      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("storeIdentifiers.explain")}
      </p>

      <Button
        variant="secondary"
        className="mt-3"
        isLoading={isRunning}
        onClick={onRun}
        icon={<Icon name="book" className="h-4 w-4" />}
      >
        {t("storeIdentifiers.run")}
      </Button>

      {error != null && (
        <div className="mt-2">
          <ErrorState error={error} fallback={t("storeIdentifiers.failed")} />
        </div>
      )}

      {result && (
        <div role="status" className="mt-3 space-y-1 text-sm">
          <p className="text-paper-700 dark:text-paper-300">
            {t("storeIdentifiers.result", {
              examined: result.examined,
              enriched: result.enriched,
            })}
          </p>
          {result.not_found > 0 && (
            <p className="text-paper-700 dark:text-paper-300">
              {t("storeIdentifiers.notFound", { count: result.not_found })}
            </p>
          )}
          {result.unavailable > 0 && (
            <p className="text-paper-700 dark:text-paper-300">
              {t("storeIdentifiers.unavailable", {
                count: result.unavailable,
              })}
            </p>
          )}
          {result.unresolvable > 0 && (
            <p className="text-paper-700 dark:text-paper-300">
              {t("storeIdentifiers.unresolvable", {
                count: result.unresolvable,
              })}
            </p>
          )}
          <p className="text-paper-600 dark:text-paper-400">
            {result.remaining > 0
              ? t("storeIdentifiers.remaining", { remaining: result.remaining })
              : t("storeIdentifiers.allDone")}
          </p>
        </div>
      )}
    </SettingsSection>
  );
}
