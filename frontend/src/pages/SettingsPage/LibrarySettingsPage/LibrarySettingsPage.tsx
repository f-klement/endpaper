import { useNavigate } from "react-router-dom";

import type { SettingsOut } from "../../../api/generated/model";

import { useLibraryMode } from "../../../app/hooks";
import { useTranslation } from "../../../i18n";
import { FolderSweepNotice, SettingsSection } from "../../components";
import { useFolderSweep } from "../../hooks";
import SettingsSubPage from "../components/SettingsSubPage";
import { useSettings } from "../hooks";
import CalibreImport from "./components/CalibreImport";
import ClassificationSchemesSection from "./components/ClassificationSchemesSection";
import CoversSection from "./components/CoversSection";
import CustomFieldsSection from "./components/CustomFieldsSection";
import HarvestImport from "./components/HarvestImport";
import HarvestSection from "./components/HarvestSection";
import KoreaderHighlightImport from "./components/KoreaderHighlightImport";
import LibraryImport from "./components/LibraryImport";
import MarcImport from "./components/MarcImport";
import StoreIdentifiersSection from "./components/StoreIdentifiersSection";
import StoreImport from "./components/StoreImport";
import VocabulariesSection from "./components/VocabulariesSection";
import {
  useCalibreImport,
  useClassificationSchemes,
  useCoverBackfill,
  useCustomFields,
  useHarvestImport,
  useKoreaderHighlightImport,
  useLibraryImport,
  useMarcImport,
  useStoreIdentifierBackfill,
  useStoreImport,
  useVocabularies,
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
 * Only the field **delete**, the classification schemes card and the subject
 * vocabularies card are admin only, which is why the settings record is asked
 * for at all here: it decides whether those are drawn, so they appear where
 * they would work rather than answering 403 when pressed.
 *
 * The covers card reads next to the import because it is what an import leaves
 * undone: a CSV carries no cover, so a library that arrived that way has none.
 * The store identifiers card is the same argument one step earlier: a Google
 * Play Books export carries a volume id for every book and no ISBN at all, so
 * that library arrives with an exact key and nothing looked up from it. It sits
 * above the covers card because it is what fills a `cover_url` in for those
 * books, and the covers card is what then downloads one.
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
 * to do. What they do share is the write, in `./importing`, and the picker, the
 * confirm row and the outcome panel, in `./components/ImportChrome`.
 */
export default function LibrarySettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const libraryImport = useLibraryImport();
  const coverBackfill = useCoverBackfill();
  const storeIdentifiers = useStoreIdentifierBackfill();
  const customFields = useCustomFields();
  const marcImport = useMarcImport();
  const calibreImport = useCalibreImport();
  const folderSweep = useFolderSweep();
  const storeImport = useStoreImport();
  const highlightImport = useKoreaderHighlightImport();
  // **The card is drawn only in library mode, and the server refuses the route
  // in any case.** Hiding a control is advice to one client; the 403 is the
  // guarantee. What this decides is whether a household is shown an exchange
  // format nobody in it can use.
  const libraryMode = useLibraryMode();
  // `settings` answering at all is what says this account is an admin: the
  // endpoint is admin only and a 403 is reported as `isForbidden`. Nothing on
  // this page is refused to a member, so the record is read for that one fact
  // and the page renders the same either way.
  const settingsState = useSettings();
  const { settings } = settingsState;
  const schemes = useClassificationSchemes(settings !== undefined);
  const vocabularies = useVocabularies(settings !== undefined);
  const harvestImport = useHarvestImport(
    harvestRepositoryOf(libraryMode, settings),
  );

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
          onCrossCheck={(files) => {
            calibreImport.crossCheck(files);
            // The library folder is the scan page's Calibre door by another
            // way in: the same root, so the same sweep.
            folderSweep.sweep(files);
          }}
          onConfirm={calibreImport.confirm}
          onStop={calibreImport.stop}
          onCancel={calibreImport.reset}
        />
        <FolderSweepNotice
          swept={folderSweep.swept}
          failed={folderSweep.failed}
          isMarking={folderSweep.isMarking}
          onMarkMissing={folderSweep.markMissing}
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

      {/* After the book imports: a sidecar's marks land only on a Book that
          already holds the file, so the books come in first. */}
      <SettingsSection title={t("highlights.importTitle")} icon="book">
        <KoreaderHighlightImport
          rows={highlightImport.rows}
          isRunning={highlightImport.isRunning}
          onChoose={highlightImport.choose}
        />
      </SettingsSection>

      {libraryMode && (
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

      {/* Library mode and admin only, like the MARC card above it: the
          harvester runs only in library mode, and the switch is a settings
          write. */}
      {libraryMode && settings !== undefined && (
        <HarvestSection
          settings={settings}
          isSaving={settingsState.isSaving}
          saveError={settingsState.saveError}
          onSave={settingsState.save}
        />
      )}

      {/* Only once the switch is on: the routes answer 404 until then, so a
          card offered before it could do nothing but be refused. */}
      {harvestIsOn(libraryMode, settings) && (
        <SettingsSection title={t("harvestRun.title")} icon="library">
          <HarvestImport
            isPreviewing={harvestImport.isPreviewing}
            isImporting={harvestImport.isImporting}
            preview={harvestImport.preview}
            result={harvestImport.result}
            readError={harvestImport.readError}
            harvestError={harvestImport.harvestError}
            onRead={harvestImport.read}
            onConfirm={harvestImport.confirm}
            onCancel={harvestImport.reset}
          />
        </SettingsSection>
      )}

      <StoreIdentifiersSection
        result={storeIdentifiers.result}
        isRunning={storeIdentifiers.isRunning}
        error={storeIdentifiers.error}
        onRun={storeIdentifiers.run}
      />

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

      {/* Admin only, unlike the fields above: every write to a scheme is, and
          a scheme's rule orders the whole library's shelves. */}
      {settings !== undefined && (
        <ClassificationSchemesSection
          schemes={schemes.schemes}
          isBusy={schemes.isBusy}
          error={schemes.error}
          onDefine={schemes.define}
          onRename={schemes.rename}
          onRemove={schemes.remove}
        />
      )}

      {/* Admin only too: a download replaces the copy every member's subject
          lookup reads. Beside the schemes, as the other half of what a
          heading may quote. */}
      {settings !== undefined && (
        <VocabulariesSection
          vocabularies={vocabularies.vocabularies}
          isStarting={vocabularies.isStarting}
          error={vocabularies.error}
          onDownload={vocabularies.download}
        />
      )}
    </SettingsSubPage>
  );
}

/** Whether a harvest can run: library mode, and the switch an admin reads on. */
function harvestIsOn(
  libraryMode: boolean,
  settings: SettingsOut | undefined,
): boolean {
  return libraryMode && settings?.oai_harvest_enabled === true;
}

/**
 * The repository a harvest would read, or null while none can be: what the
 * hook keys its preview on, so a corrected address discards it.
 */
function harvestRepositoryOf(
  libraryMode: boolean,
  settings: SettingsOut | undefined,
): string | null {
  if (!harvestIsOn(libraryMode, settings)) return null;
  return settings?.oai_harvest_base_url ?? null;
}
