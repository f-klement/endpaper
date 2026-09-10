import { useNavigate } from "react-router-dom";

import { useFeatureFlags } from "../../../app/hooks";
import { useTranslation } from "../../../i18n";
import { SettingsSection } from "../../components";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";
import CalibreImport from "./components/CalibreImport";
import CoversSection from "./components/CoversSection";
import CustomFieldsSection from "./components/CustomFieldsSection";
import LibraryImport from "./components/LibraryImport";
import MarcImport from "./components/MarcImport";
import StoreImport from "./components/StoreImport";
import {
  useCalibreImport,
  useCoverBackfill,
  useCustomFields,
  useLibraryImport,
  useMarcImport,
  useStoreImport,
} from "./hooks";

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
 *
 * **The Calibre card sits with the other imports and not on the scan page**,
 * which is the other place a file is read in this app. A Calibre library is a
 * library, not a book: what the scan page reads is one file a member is holding,
 * and what this reads is somebody's whole shelf. The store card is here for the
 * same reason, and it sits after Calibre because Calibre is the richer route:
 * whoever has both should meet the one that carries the identifiers first.
 *
 * **Two import cards and not one, and they are not merging.** The Calibre card
 * has a preview and a cross check the store card has nothing to offer, and the
 * store card reads several sources at once, which Calibre has no second library
 * to do. What they do share, the write, is `./importing`.
 */
export default function LibrarySettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const libraryImport = useLibraryImport();
  const coverBackfill = useCoverBackfill();
  const customFields = useCustomFields();
  const marcImport = useMarcImport();
  const calibreImport = useCalibreImport();
  const storeImport = useStoreImport();
  // **The card is drawn only in library mode, and the server refuses the route
  // in any case.** Hiding a control is advice to one client; the 403 is the
  // guarantee. What this decides is whether a household is shown an exchange
  // format nobody in it can use.
  const flags = useFeatureFlags();
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

      <SettingsSection title={t("calibre.title")} icon="book">
        <CalibreImport
          isReading={calibreImport.isReading}
          isImporting={calibreImport.isImporting}
          preview={calibreImport.preview}
          progress={calibreImport.progress}
          result={calibreImport.result}
          failure={calibreImport.failure}
          error={calibreImport.error}
          onChoose={calibreImport.choose}
          onCrossCheck={calibreImport.crossCheck}
          onConfirm={calibreImport.confirm}
          onStop={calibreImport.stop}
          onCancel={calibreImport.reset}
        />
      </SettingsSection>

      <SettingsSection title={t("stores.title")} icon="book">
        <StoreImport
          sources={storeImport.sources}
          preview={storeImport.preview}
          progress={storeImport.progress}
          result={storeImport.result}
          isReading={storeImport.isReading}
          isImporting={storeImport.isImporting}
          onChoose={storeImport.choose}
          onConfirm={storeImport.confirm}
          onStop={storeImport.stop}
          onCancel={storeImport.reset}
        />
      </SettingsSection>

      {flags?.library_mode && (
        <SettingsSection title={t("marc.title")} icon="book">
          <MarcImport
            isPreviewing={marcImport.isPreviewing}
            isImporting={marcImport.isImporting}
            preview={marcImport.preview}
            result={marcImport.result}
            error={marcImport.error}
            onChoose={marcImport.choose}
            onConfirm={marcImport.confirm}
            onCancel={marcImport.reset}
            onReviewUnconfirmed={() => navigate("/?ownership=unknown")}
          />
        </SettingsSection>
      )}

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
