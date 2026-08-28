import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import ToggleField from "../components/ToggleField";
import { useSettings } from "../hooks";
import GoogleBooksSection from "./components/GoogleBooksSection";

/**
 * Where a book's details come from.
 *
 * Both cards are the same question asked of two services: may this library ask
 * them about a book, and with what credentials. Neither writes anything to a
 * book by itself, which is why they are one screen and not part of Your
 * library: that route is about the books already here.
 *
 * Admin only, all of it, so the whole page body sits inside `AdminSettings`.
 */
export default function CatalogueSettingsPage() {
  const { t } = useTranslation();
  const state = useSettings();

  return (
    <SettingsSubPage icon="search" title={t("settings.catalogue.title")}>
      <AdminSettings state={state}>
        {(settings) => (
          <>
            <GoogleBooksSection
              settings={settings}
              isSaving={state.isSaving}
              onSave={state.save}
            />

            {/* The lookup toggle only. Importing a Goodreads export is Your
                library's business: an import writes the importing member's own
                reading statuses and nobody else's, so it is not admin only. */}
            <SettingsSection title={t("settings.goodreads")} icon="book">
              <ToggleField
                label={t("settings.goodreadsEnable")}
                hint={t("settings.goodreadsHint")}
                checked={settings.goodreads_lookup_enabled}
                disabled={state.isSaving}
                onChange={(checked) =>
                  state.save({ goodreads_lookup_enabled: checked })
                }
              />
            </SettingsSection>
          </>
        )}
      </AdminSettings>
    </SettingsSubPage>
  );
}
