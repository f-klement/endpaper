import { useNavigate } from "react-router-dom";

import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";
import CoversSection from "./components/CoversSection";
import CustomFieldsSection from "./components/CustomFieldsSection";
import LibraryImport from "./components/LibraryImport";
import { useCoverBackfill, useCustomFields, useLibraryImport } from "./hooks";

/**
 * Bringing books in, and the shape this household gives them.
 *
 * **None of this is admin only, and that is deliberate on all three cards.** An
 * import writes the importing member's own reading statuses and nobody else's,
 * which is the whole reason two people can bring their own histories across;
 * the cover backfill only ever touches books the caller can see, so it is each
 * member's own shelf they are repairing; and defining a custom field is
 * additive and changes no book, exactly as inventing a tag is.
 *
 * Only the field **delete** is admin only, which is why the settings record is
 * asked for at all here: `isAdmin` decides whether that one control is drawn,
 * so it appears where it would work rather than answering 403 when pressed.
 *
 * The covers card reads next to the import because it is what an import leaves
 * undone: a CSV carries no cover, so a library that arrived that way has none.
 */
export default function LibrarySettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const libraryImport = useLibraryImport();
  const coverBackfill = useCoverBackfill();
  const customFields = useCustomFields();
  // `settings` answering at all is what says this account is an admin: the
  // endpoint is admin only and a 403 is reported as `isForbidden`. Nothing on
  // this page is refused to a member, so the record is read for that one fact
  // and the page renders the same either way.
  const { settings } = useSettings();

  return (
    <SettingsSubPage icon="book" title={t("settings.library.title")}>
      <SettingsSection title={t("import.title")} icon="book">
        <LibraryImport
          isPreviewing={libraryImport.isPreviewing}
          isImporting={libraryImport.isImporting}
          preview={libraryImport.preview}
          result={libraryImport.result}
          error={libraryImport.error}
          onChoose={libraryImport.choose}
          onConfirm={libraryImport.confirm}
          onCancel={libraryImport.reset}
          onReviewUnconfirmed={() => navigate("/?ownership=unknown")}
        />
      </SettingsSection>

      <CoversSection
        result={coverBackfill.result}
        isRunning={coverBackfill.isRunning}
        error={coverBackfill.error}
        onRun={coverBackfill.run}
      />

      <CustomFieldsSection
        fields={customFields.fields}
        isAdmin={settings !== undefined}
        isBusy={customFields.isBusy}
        error={customFields.error}
        onDefine={customFields.define}
        onRename={customFields.rename}
        onRemove={customFields.remove}
      />
    </SettingsSubPage>
  );
}
