import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  AuthMode,
  Locale,
  type SettingsUpdate,
  type UserOut,
} from "../../api/generated/model";
import {
  CollapsibleSection,
  ErrorState,
  HelpButton,
  Spinner,
} from "../../components";
import { useTranslation, type Translate } from "../../i18n";
import { paletteEntry, useTheme, WALLPAPER_OFF } from "../../theme";
import { PATTERNS } from "../../theme/patterns";
import { MODE_LABELS } from "../types";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import AboutSection from "./components/AboutSection";
import BackupSection from "./components/BackupSection";
import CoversSection from "./components/CoversSection";
import CustomFieldsSection from "./components/CustomFieldsSection";
import LibraryImport from "./components/LibraryImport";
import OverdueSection from "./components/OverdueSection";
import ReminderSendersSection from "./components/ReminderSendersSection";
import TestAccounts from "./components/TestAccounts";
import ToggleField from "./components/ToggleField";
import {
  useBackup,
  useCoverBackfill,
  useCustomFields,
  useLibraryImport,
  useOverdueDigest,
  useSettings,
  useSettingsSections,
  useSwitchToTestAccount,
  useTestAccounts,
} from "./hooks";
import { Icon } from "../../components";
import { Page, PageHeader } from "../components";

/**
 * The wallpaper choice, named.
 *
 * Three states in one field. The summary names the choice rather than what
 * happens to be on the page: somebody who picked Surprise me should read
 * "Surprise me" here, not this visit's pattern, which would read as pinned.
 *
 * Membership in `PATTERNS`, not `patternFor`, and the difference matters. An id
 * this build no longer has degrades to a random pattern on the page, and asking
 * `patternFor` for its name would print that pattern here as though it were the
 * one chosen. Both cases that end in a different wallpaper every visit are
 * named as such.
 */
function wallpaperName(wallpaper: string | null, t: Translate): string {
  if (wallpaper === WALLPAPER_OFF) return t("appearance.wallpaperNone");
  const named = PATTERNS.find((pattern) => pattern.id === wallpaper);
  return named ? named.name : t("appearance.wallpaperSurprise");
}

const LANGUAGES = [
  { value: Locale.en, label: "settings.language.en" },
  { value: Locale.de, label: "settings.language.de" },
] as const;

interface SettingsPageProps {
  /** Which sentence the test accounts section uses to say how to get back. */
  mode: AuthMode;
  /**
   * A switch lands here: it is a sign-in on another account, so it goes
   * through the same handler the login form uses.
   */
  onSignIn: (user: UserOut, token: string) => void;
}

export default function SettingsPage({ mode, onSignIn }: SettingsPageProps) {
  const { t, locale, setLocale } = useTranslation();
  const { appearance, wallpaperOff } = useTheme();
  const navigate = useNavigate();
  const {
    settings,
    isLoading,
    error,
    isForbidden,
    save,
    isSaving,
    saveError,
    hasSaved,
  } = useSettings();
  const libraryImport = useLibraryImport();
  const coverBackfill = useCoverBackfill();
  const backup = useBackup();
  const overdue = useOverdueDigest();
  // `settings` answering at all is what says this account is an admin: the
  // endpoint is admin only and a 403 is reported as `isForbidden`. Asking for
  // the test accounts on that same condition keeps every member off a route
  // that would only refuse them.
  const isAdmin = settings !== undefined;
  const testAccounts = useTestAccounts(isAdmin);
  const customFields = useCustomFields();
  const switching = useSwitchToTestAccount(onSignIn);
  const sections = useSettingsSections();

  // The API key is the one field the server never sends back, so it cannot be
  // a controlled mirror of `settings`. It is a write-only box: empty means
  // "leave the stored key alone".
  const [apiKey, setApiKey] = useState("");
  // The typed value, not the stored one: the server never returns a key, so
  // this only ever reveals what the admin has just entered themselves.
  const [showKey, setShowKey] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  const wallpaper = wallpaperName(appearance.wallpaper, t);

  const fromEnv = settings?.google_books_api_key_from_env === true;

  function update(patch: SettingsUpdate) {
    save(patch);
  }

  return (
    <Page width="narrow">
      <PageHeader icon="settings" title={t("settings.title")} />
      {/* The cards carry no margin of their own, so the rhythm is stated here.
          `AppearancePage` does the same, and the two screens are meant to look
          like one app. */}
      <div className="space-y-5">
        {/* Language is per person and per device, so it works without an admin
            account and is rendered before anything the server has to authorise. */}
        <CollapsibleSection
          variant="card"
          icon="globe"
          id="language"
          title={t("settings.language")}
          isOpen={sections.isOpen("language")}
          onToggle={() => sections.toggle("language")}
        >
          {/* No `role="group"` of its own: the folded section's panel is
              already a group labelled by this card's handle, and a second group
              with the same name would make two elements answer to it. */}
          <div className="flex gap-2">
            {LANGUAGES.map((language) => (
              <button
                key={language.value}
                type="button"
                onClick={() => setLocale(language.value)}
                aria-pressed={locale === language.value}
                className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                  locale === language.value
                    ? "bg-accent-50 border-accent-300 text-accent-800 " +
                      "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                    : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 " +
                      "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
                }`}
              >
                {t(language.label)}
              </button>
            ))}
          </div>
          <p className="text-xs text-paper-600 dark:text-paper-400">
            {t("settings.languageHint")}
          </p>
        </CollapsibleSection>

        {/* A link, not the controls. The picker previews a palette and a
            wallpaper on the page itself, which is the one thing a row in a
            settings list cannot do. What stays here is the summary, so somebody
            scanning this page still sees what is set. */}
        <CollapsibleSection
          variant="card"
          icon="theme"
          id="appearance"
          title={t("theme.label")}
          isOpen={sections.isOpen("appearance")}
          onToggle={() => sections.toggle("appearance")}
        >
          <Link
            to="/settings/appearance"
            className="flex items-center gap-3 rounded-xl border border-paper-200 bg-paper-0 px-3 py-2.5 hover:bg-paper-50 dark:border-paper-700 dark:bg-paper-900 dark:hover:bg-paper-800"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-paper-900 dark:text-paper-100">
                {t("theme.summary", {
                  palette: paletteEntry(appearance.palette).label,
                  mode: t(MODE_LABELS[appearance.mode]),
                  wallpaper,
                })}
              </span>
              <span className="block text-xs text-paper-600 dark:text-paper-400">
                {t("theme.change")}
              </span>
            </span>
            <span
              aria-hidden="true"
              className="text-paper-600 dark:text-paper-400"
            >
              <Icon name="chevron" className="w-4 h-4" />
            </span>
          </Link>
          {/* Said rather than left to be noticed. The wallpaper is decoration and
              goes first when somebody asks their system for more contrast, and a
              decoration that vanishes with no explanation reads as a fault in
              this app rather than as the setting being honoured. */}
          {wallpaperOff && (
            <p className="text-xs text-paper-600 dark:text-paper-400">
              {t("theme.wallpaperOff")}
            </p>
          )}
        </CollapsibleSection>

        {/* Outside the admin block, deliberately. Reading statuses are personal
            and an import only ever writes the importing member's own, which is
            the whole reason two people can bring their own histories across.
            Sitting inside that block meant a non-admin could not import theirs
            at all, while the endpoint had always allowed it. */}
        <CollapsibleSection
          variant="card"
          icon="book"
          id="import"
          title={t("import.title")}
          isOpen={sections.isOpen("import")}
          onToggle={() => sections.toggle("import")}
        >
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
        </CollapsibleSection>

        {/* Beside the import, and outside the admin block for the same reason it
            is: the backfill only ever touches books the caller can see, so it is
            each member's own shelf they are repairing. It is also what an import
            leaves undone, which is why it reads next. */}
        <CoversSection
          isOpen={sections.isOpen("covers")}
          onToggle={() => sections.toggle("covers")}
          result={coverBackfill.result}
          isRunning={coverBackfill.isRunning}
          error={coverBackfill.error}
          onRun={coverBackfill.run}
        />

        {/* Outside the admin block, like the import and the backfill above it,
            and for the same kind of reason: defining a field is additive and
            changes no book, so it is open to any member exactly as inventing a
            tag is. Only the delete is admin only, and the section is passed
            `isAdmin` so that control is drawn where it would work rather than
            answering 403 when it is pressed. */}
        <CustomFieldsSection
          isOpen={sections.isOpen("customFields")}
          onToggle={() => sections.toggle("customFields")}
          fields={customFields.fields}
          isAdmin={isAdmin}
          isBusy={customFields.isBusy}
          error={customFields.error}
          onDefine={customFields.define}
          onRename={customFields.rename}
          onRemove={customFields.remove}
        />

        {isLoading && <Spinner label={t("common.loading")} />}

        {/* A non-admin gets the language switch and nothing else. That is not an
            error worth showing an error page for, so it is stated plainly. */}
        {isForbidden && (
          <p className="text-sm text-paper-600 text-center dark:text-paper-400">
            {t("settings.adminOnly")}
          </p>
        )}

        {error != null && !isForbidden && (
          <ErrorState error={error} fallback={t("settings.couldNotLoad")} />
        )}

        {settings && (
          <>
            <CollapsibleSection
              variant="card"
              icon="search"
              id="googleBooks"
              title={t("settings.googleBooks")}
              isOpen={sections.isOpen("googleBooks")}
              onToggle={() => sections.toggle("googleBooks")}
            >
              <ToggleField
                label={t("settings.googleBooksEnable")}
                hint={t("settings.googleBooksHint")}
                checked={settings.google_books_enabled}
                disabled={isSaving}
                onChange={(checked) =>
                  update({ google_books_enabled: checked })
                }
              />

              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <label
                    htmlFor="google-books-key"
                    className="block text-xs font-medium text-paper-600 dark:text-paper-300"
                  >
                    {t("settings.apiKey")}
                  </label>
                  <HelpButton
                    label={t("settings.apiKeyHelp")}
                    onClick={() => setShowHelp(true)}
                  />
                </div>

                <div className="relative">
                  <input
                    id="google-books-key"
                    type={showKey ? "text" : "password"}
                    autoComplete="off"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={t("settings.apiKeyPlaceholder")}
                    // Managed outside the app, so there is nothing here to edit
                    // and nothing to unmask.
                    disabled={fromEnv}
                    className="w-full px-3 py-2 pr-10 rounded-xl border border-paper-200 text-sm disabled:bg-paper-50 disabled:text-paper-400 disabled:cursor-not-allowed dark:border-paper-700 dark:disabled:bg-paper-800"
                  />
                  {!fromEnv && (
                    <button
                      type="button"
                      onClick={() => setShowKey((shown) => !shown)}
                      aria-label={showKey ? t("field.hide") : t("field.show")}
                      aria-pressed={showKey}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-paper-600 hover:text-paper-800 text-sm leading-none dark:text-paper-400 dark:hover:text-paper-300"
                    >
                      <span aria-hidden="true">
                        <Icon
                          name={showKey ? "eyeOff" : "eye"}
                          className="w-4 h-4"
                        />
                      </span>
                    </button>
                  )}
                </div>
                <p className="text-xs text-paper-600 dark:text-paper-400">
                  {settings.has_google_books_api_key
                    ? t("settings.apiKeySet", {
                        preview: settings.google_books_api_key_preview,
                      })
                    : t("settings.apiKeyMissing")}
                </p>

                {fromEnv && (
                  <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-200 dark:bg-amber-950 dark:border-amber-900">
                    {t("settings.apiKeyFromEnv")}
                  </p>
                )}
                {!fromEnv && (
                  <div className="flex gap-2 pt-1">
                    <button
                      type="button"
                      disabled={isSaving || apiKey.trim() === ""}
                      onClick={() => {
                        update({ google_books_api_key: apiKey.trim() });
                        setApiKey("");
                      }}
                      className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
                    >
                      {isSaving ? t("common.saving") : t("common.save")}
                    </button>
                    {settings.has_google_books_api_key && (
                      <button
                        type="button"
                        disabled={isSaving}
                        // An empty string clears it; `undefined` would mean
                        // "leave alone", which is the opposite.
                        onClick={() => update({ google_books_api_key: "" })}
                        className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-danger-300"
                      >
                        {t("settings.apiKeyClear")}
                      </button>
                    )}
                  </div>
                )}
                <p className="text-xs text-paper-600 leading-relaxed pt-1 dark:text-paper-400">
                  {t("settings.apiKeyHint")}
                </p>
              </div>
            </CollapsibleSection>

            {/* The lookup toggle only. The import moved out of the admin block
                above, because an import writes the importing member's own
                statuses and nobody else's. */}
            <CollapsibleSection
              variant="card"
              icon="book"
              id="goodreads"
              title={t("settings.goodreads")}
              isOpen={sections.isOpen("goodreads")}
              onToggle={() => sections.toggle("goodreads")}
            >
              <ToggleField
                label={t("settings.goodreadsEnable")}
                hint={t("settings.goodreadsHint")}
                checked={settings.goodreads_lookup_enabled}
                disabled={isSaving}
                onChange={(checked) =>
                  update({ goodreads_lookup_enabled: checked })
                }
              />
            </CollapsibleSection>

            <CollapsibleSection
              variant="card"
              icon="flag"
              id="defaultLanguage"
              title={t("settings.defaultLanguage")}
              isOpen={sections.isOpen("defaultLanguage")}
              onToggle={() => sections.toggle("defaultLanguage")}
            >
              {/* The panel is the group, as above. */}
              <div className="flex gap-2">
                {LANGUAGES.map((language) => (
                  <button
                    key={language.value}
                    type="button"
                    disabled={isSaving}
                    onClick={() => update({ default_locale: language.value })}
                    aria-pressed={settings.default_locale === language.value}
                    className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors disabled:opacity-50 ${
                      settings.default_locale === language.value
                        ? "bg-accent-50 border-accent-300 text-accent-800 " +
                          "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                        : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 " +
                          "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
                    }`}
                  >
                    {t(language.label)}
                  </button>
                ))}
              </div>
            </CollapsibleSection>

            <OverdueSection
              isOpen={sections.isOpen("overdue")}
              onToggle={() => sections.toggle("overdue")}
              settings={settings}
              isSaving={isSaving}
              onSave={update}
              onSendNow={overdue.send}
              isSending={overdue.isSending}
              sendResult={overdue.result}
              sendError={overdue.error}
            />

            <ReminderSendersSection
              isOpen={sections.isOpen("reminderSenders")}
              onToggle={() => sections.toggle("reminderSenders")}
              settings={settings}
              isSaving={isSaving}
              onSave={update}
            />

            {/* Admin only, and inside this block for that reason. Under a
                directory this is the only way an admin can see what an ordinary
                member sees: registration is refused and nobody's directory
                password is ours to type. */}
            <CollapsibleSection
              variant="card"
              icon="user"
              id="testAccounts"
              title={t("settings.testAccounts")}
              isOpen={sections.isOpen("testAccounts")}
              onToggle={() => sections.toggle("testAccounts")}
            >
              <TestAccounts
                accounts={testAccounts.accounts}
                isLoading={testAccounts.isLoading}
                error={testAccounts.error}
                onCreate={testAccounts.create}
                isCreating={testAccounts.isCreating}
                createError={testAccounts.createError}
                onSwitch={switching.switchTo}
                isSwitching={switching.isSwitching}
                switchError={switching.switchError}
                mode={mode}
              />
            </CollapsibleSection>

            <BackupSection
              isOpen={sections.isOpen("backup")}
              onToggle={() => sections.toggle("backup")}
              isDownloading={backup.isDownloading}
              downloadError={backup.downloadError}
              onDownload={backup.download}
              isRestoring={backup.isRestoring}
              restoreError={backup.restoreError}
              restored={backup.restored}
              onRestore={backup.restore}
            />

            {showHelp && (
              <GoogleBooksHelp
                isUnconfigured={!settings.has_google_books_api_key}
                onClose={() => setShowHelp(false)}
              />
            )}

            {saveError != null && (
              <ErrorState
                error={saveError}
                fallback={t("common.somethingWentWrong")}
              />
            )}
            {hasSaved && saveError == null && (
              <p
                role="status"
                className="text-sm text-green-800 text-center dark:text-green-400"
              >
                {t("settings.saved")}
              </p>
            )}
          </>
        )}

        {/* Last, and outside the admin block: it is the same card for everybody,
            and a member who can change nothing else still gets it. */}
        <AboutSection
          isOpen={sections.isOpen("about")}
          onToggle={() => sections.toggle("about")}
        />
      </div>
    </Page>
  );
}
