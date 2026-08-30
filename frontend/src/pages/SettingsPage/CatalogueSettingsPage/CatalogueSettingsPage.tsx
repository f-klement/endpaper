import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import AdminSettings from "../components/AdminSettings";
import SettingsSubPage from "../components/SettingsSubPage";
import ToggleField from "../components/ToggleField";
import { useSettings } from "../hooks";
import GoogleBooksSection from "./components/GoogleBooksSection";
import ProviderSection from "./components/ProviderSection";

/**
 * Where a book's details come from.
 *
 * Every card here is the same question asked of a service: may this library ask
 * it about a book, in what order, and with what credentials. None of them
 * writes anything to a book by itself, which is why they are one screen and not
 * part of Your library: that route is about the books already here.
 *
 * **The provider list comes first**, because it is the one that decides whether
 * the two below it are consulted at all. Google Books keeps its own card under
 * it, and the two are not a duplicate: the list says whether and in what order
 * Google is asked, the card holds the key that lets it answer. The server
 * conjoins them in one place (`settings_store.catalogue_sources`), so a source
 * switched on in the list with no key is shown as not ready rather than
 * silently asked.
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
            <ProviderSection settings={settings} onSave={state.save} />

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
