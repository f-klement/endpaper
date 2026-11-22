import { ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { numericDate } from "../../../../lib/date";
import { SettingsSection } from "../../../components";
import ToggleField from "../../components/ToggleField";
import { useCatalogueRegistry } from "../hooks";
import SourceTest, { DISPOSITION_TEXT } from "./SourceTest";

/**
 * The curated catalogues this build ships, to pick from rather than type.
 *
 * **Each entry shows the evidence it shipped on**, the date it was probed, the
 * ISBN asked and how it answered, so an admin can compare it with a test of
 * their own. A pick records the choice and is not asked on a scan yet, which
 * the hint says, so nobody picks one and wonders why nothing changed.
 */
export default function RegistrySection() {
  const { t, locale } = useTranslation();
  const { registry, setPicked, isWorking, error } = useCatalogueRegistry();

  return (
    <SettingsSection title={t("registry.title")} icon="search">
      <p className="mb-3 text-sm text-paper-600 dark:text-paper-400">
        {t("registry.hint")}
      </p>
      {registry?.aged && (
        <p className="mb-3 text-sm text-amber-700 dark:text-amber-400">
          {t("registry.aged", {
            date: numericDate(registry.taken_on, locale),
          })}
        </p>
      )}
      {error != null && (
        <ErrorState error={error} fallback={t("settings.couldNotLoad")} />
      )}
      <ul className="space-y-3">
        {registry?.entries.map((entry) => (
          <li
            key={entry.source}
            className="border-t border-paper-200 pt-3 first:border-0 first:pt-0 dark:border-paper-800"
          >
            <ToggleField
              label={entry.name}
              hint={t("registry.evidence", {
                country: entry.country,
                host: entry.host,
                date: numericDate(entry.evidence.probed_on, locale),
                answer: t(DISPOSITION_TEXT[entry.evidence.disposition], {
                  isbn: entry.evidence.isbn,
                }),
              })}
              checked={entry.picked}
              disabled={isWorking}
              onChange={(checked) => setPicked(entry.source, checked)}
            />
            <SourceTest source={entry.source} name={entry.name} />
          </li>
        ))}
      </ul>
    </SettingsSection>
  );
}
