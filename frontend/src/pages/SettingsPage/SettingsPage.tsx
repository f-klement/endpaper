import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  AuthMode,
  Locale,
  type SettingsUpdate,
  type UserOut,
} from "../../api/generated/model";
import { ErrorState, HelpButton, Spinner } from "../../components";
import { useTranslation, type Translate } from "../../i18n";
import { paletteEntry, useTheme, WALLPAPER_OFF } from "../../theme";
import { PATTERNS } from "../../theme/patterns";
import { MODE_LABELS } from "../types";
import GoogleBooksHelp from "../components/GoogleBooksHelp";
import BackupSection from "./components/BackupSection";
import LibraryImport from "./components/LibraryImport";
import TestAccounts from "./components/TestAccounts";
import ToggleField from "./components/ToggleField";
import {
  useBackup,
  useLibraryImport,
  useSettings,
  useSwitchToTestAccount,
  useTestAccounts,
} from "./hooks";
import { Icon } from "../../components";
import { Page, PageHeader, SettingsSection } from "../components";

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
  const backup = useBackup();
  // `settings` answering at all is what says this account is an admin: the
  // endpoint is admin only and a 403 is reported as `isForbidden`. Asking for
  // the test accounts on that same condition keeps every member off a route
  // that would only refuse them.
  const isAdmin = settings !== undefined;
  const testAccounts = useTestAccounts(isAdmin);
  const switching = useSwitchToTestAccount(onSignIn);

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

      {/* Language is per person and per device, so it works without an admin
          account and is rendered before anything the server has to authorise. */}
      <SettingsSection title={t("settings.language")} icon="globe">
        <div
          className="flex gap-2"
          role="group"
          aria-label={t("settings.language")}
        >
          {LANGUAGES.map((language) => (
            <button
              key={language.value}
              type="button"
              onClick={() => setLocale(language.value)}
              aria-pressed={locale === language.value}
              className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                locale === language.value
                  ? "bg-accent-50 border-accent-300 text-accent-800 "
                + "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                  : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
              }`}
            >
              {t(language.label)}
            </button>
          ))}
        </div>
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("settings.languageHint")}
        </p>
      </SettingsSection>

      {/* A link, not the controls. The picker previews a palette and a
          wallpaper on the page itself, which is the one thing a row in a
          settings list cannot do. What stays here is the summary, so somebody
          scanning this page still sees what is set. */}
      <SettingsSection title={t("theme.label")} icon="theme">
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
          <span aria-hidden="true" className="text-paper-600 dark:text-paper-400">
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
      </SettingsSection>

      {/* Outside the admin block, deliberately. Reading statuses are personal
          and an import only ever writes the importing member's own, which is
          the whole reason two people can bring their own histories across.
          Sitting inside that block meant a non-admin could not import theirs
          at all, while the endpoint had always allowed it. */}
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
          <SettingsSection title={t("settings.googleBooks")} icon="search">
            <ToggleField
              label={t("settings.googleBooksEnable")}
              hint={t("settings.googleBooksHint")}
              checked={settings.google_books_enabled}
              disabled={isSaving}
              onChange={(checked) => update({ google_books_enabled: checked })}
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
                    <span aria-hidden="true"><Icon name={showKey ? "eyeOff" : "eye"} className="w-4 h-4" /></span>
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
          </SettingsSection>

          {/* The lookup toggle only. The import moved out of the admin block
              above, because an import writes the importing member's own
              statuses and nobody else's. */}
          <SettingsSection title={t("settings.goodreads")} icon="book">
            <ToggleField
              label={t("settings.goodreadsEnable")}
              hint={t("settings.goodreadsHint")}
              checked={settings.goodreads_lookup_enabled}
              disabled={isSaving}
              onChange={(checked) =>
                update({ goodreads_lookup_enabled: checked })
              }
            />
          </SettingsSection>

          <SettingsSection title={t("settings.defaultLanguage")} icon="flag">
            <div
              className="flex gap-2"
              role="group"
              aria-label={t("settings.defaultLanguage")}
            >
              {LANGUAGES.map((language) => (
                <button
                  key={language.value}
                  type="button"
                  disabled={isSaving}
                  onClick={() => update({ default_locale: language.value })}
                  aria-pressed={settings.default_locale === language.value}
                  className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors disabled:opacity-50 ${
                    settings.default_locale === language.value
                      ? "bg-accent-50 border-accent-300 text-accent-800 "
                + "dark:bg-accent-950 dark:border-accent-800 dark:text-accent-200"
                      : "bg-paper-0 border-paper-200 text-paper-600 hover:bg-paper-50 "
                + "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:bg-paper-800"
                  }`}
                >
                  {t(language.label)}
                </button>
              ))}
            </div>
          </SettingsSection>

          {/* Admin only, and inside this block for that reason. Under a
              directory this is the only way an admin can see what an ordinary
              member sees: registration is refused and nobody's directory
              password is ours to type. */}
          <SettingsSection title={t("settings.testAccounts")} icon="user">
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
          </SettingsSection>

          <BackupSection
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
    </Page>
  );
}
