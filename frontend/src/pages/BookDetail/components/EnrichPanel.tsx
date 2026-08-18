import type { BookEnrichmentOut } from "../../../api/generated/model";
import { HelpButton } from "../../../components";
import { errorText } from "../../../components/ErrorState";
import { useTranslation, type MessageKey } from "../../../i18n";

interface EnrichPanelProps {
  /** False when no API key is stored: the button is shown but inert. */
  isConfigured: boolean;
  onOpenHelp: () => void;
  isWorking: boolean;
  result: BookEnrichmentOut | null;
  error: unknown;
  onEnrich: () => void;
  onDismiss: () => void;
}

/** Field names come back from the server; unknown ones are shown verbatim. */
function fieldLabel(field: string, t: (key: MessageKey) => string): string {
  const key = `enrich.field.${field}` as MessageKey;
  const translated = t(key);
  return translated === key ? field : translated;
}

/**
 * The "find more details" control and whatever the last run reported.
 *
 * Reports `updated_fields` rather than a bare success, because the common
 * outcome is that Google Books has the volume and nothing to add. Saying
 * "done" there would be indistinguishable from a broken button.
 */
export default function EnrichPanel({
  isConfigured,
  onOpenHelp,
  isWorking,
  result,
  error,
  onEnrich,
  onDismiss,
}: EnrichPanelProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onEnrich}
          disabled={!isConfigured || isWorking}
          className="flex-1 py-2.5 rounded-xl border border-sky-200 bg-sky-50 text-sm font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors dark:border-sky-800 dark:bg-sky-950 dark:text-sky-300"
        >
          {isWorking ? t("enrich.working") : t("enrich.button")}
        </button>
        <HelpButton label={t("help.aboutEnrich")} onClick={onOpenHelp} />
      </div>

      {/* Shown rather than hiding the button: a control that is visibly off and
          explains itself beats a feature nobody knows exists. */}
      {!isConfigured && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t("help.disabledEnrich")}
        </p>
      )}

      {error != null && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {errorText(error, t("common.somethingWentWrong"))}
        </p>
      )}

      {result && (
        <div
          role="status"
          className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-start justify-between gap-3 dark:text-gray-300 dark:bg-gray-900 dark:border-gray-700"
        >
          <span>
            {!result.found
              ? t("enrich.notFound")
              : result.updated_fields.length === 0
                ? t("enrich.nothingNew")
                : t("enrich.updated", {
                    fields: result.updated_fields
                      .map((field) => fieldLabel(field, t))
                      .join(", "),
                  })}
          </span>
          <button
            type="button"
            onClick={onDismiss}
            aria-label={t("common.close")}
            className="shrink-0 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
