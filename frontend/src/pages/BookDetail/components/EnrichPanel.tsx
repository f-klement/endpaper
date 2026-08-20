import type { BookEnrichmentOut } from "../../../api/generated/model";
import { HelpButton } from "../../../components";
import { errorText } from "../../../components/ErrorState";
import { useTranslation, type MessageKey } from "../../../i18n";
import { Icon } from "../../../components";

interface EnrichPanelProps {
  /**
   * Whether Google Books is configured. Not required: the button works
   * without it, so this only decides the note about what a key would add.
   */
  isConfigured: boolean;
  onOpenHelp: () => void;
  isWorking: boolean;
  result: BookEnrichmentOut | null;
  error: unknown;
  /** Opens the picker. Writes nothing on its own. */
  onBrowse: () => void;
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
 * The button opens a picker rather than writing: choosing the edition
 * automatically got the wrong printing often enough to matter. See
 * EnrichPicker.
 *
 * Reports `updated_fields` rather than a bare success, because the common
 * outcome is that the chosen edition has nothing this book lacks. Saying
 * "done" there would be indistinguishable from a broken button.
 */
export default function EnrichPanel({
  isConfigured,
  onOpenHelp,
  isWorking,
  result,
  error,
  onBrowse,
  onDismiss,
}: EnrichPanelProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onBrowse}
          disabled={isWorking}
          className="flex-1 py-2.5 rounded-xl border border-accent-200 bg-accent-50 text-sm font-medium text-accent-800 hover:bg-accent-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors dark:border-accent-900 dark:bg-accent-950 dark:text-accent-300"
        >
          {isWorking ? t("enrich.working") : t("enrich.button")}
        </button>
        <HelpButton label={t("help.aboutEnrich")} onClick={onOpenHelp} />
      </div>

      {/* Not a disabled state: the button works. This says what a key adds. */}
      {!isConfigured && (
        <p className="text-xs text-paper-500 dark:text-paper-400">
          {t("help.disabledEnrich")}
        </p>
      )}

      {error != null && (
        <p role="alert" className="text-xs text-bloom-600 dark:text-bloom-300">
          {errorText(error, t("common.somethingWentWrong"))}
        </p>
      )}

      {result && (
        <div
          role="status"
          className="text-xs text-paper-600 bg-paper-50 border border-paper-200 rounded-lg px-3 py-2 flex items-start justify-between gap-3 dark:text-paper-300 dark:bg-paper-900 dark:border-paper-700"
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
            className="shrink-0 text-paper-400 hover:text-paper-600 dark:text-paper-500 dark:hover:text-paper-300"
          >
            <Icon name="close" className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
